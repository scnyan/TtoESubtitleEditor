import csv
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "subtitles_data.json"
CSV_PATH = ROOT / "subtitles_data.csv"
WORKING_CSV_PATH = ROOT / "translation_working_precise_ja.csv"
REPORT_PATH = ROOT / "shorts_split_round9_report.csv"

MIN_MS = 850
TARGET_CHARS = 24
MAX_CHARS = 34
MERGE_LIMIT = 52

QUOTE_PAIRS = {"「": "」", "『": "』", "“": "”", '"': '"'}
PROTECTED_PHRASES = [
    "Time to Explain",
    "Brawl Pass",
    "Brawl Pass Plus",
    "ブロスタパスPlus",
    "ブロスタパス",
    "ストレンジャー・シングス",
    "スター・パーク",
    "Supercell Make",
    "League of Legends",
    "Brawl Talk",
    "Brawlies",
    "ゲームプレイ側",
    "ゲームプレイ",
    "ジュエルチップ",
]

SHORT_WORDS = {
    "うん。",
    "そうだね。",
    "その通り。",
    "OK。",
    "よし。",
    "いや。",
    "でも…",
    "だから、",
    "それで、",
    "じゃあ、",
    "（笑）",
    "（鼻で笑う）",
}

CONNECTOR_STARTS = [
    "だから、",
    "ただ、",
    "でも、",
    "それで、",
    "じゃあ、",
    "そして、",
    "つまり、",
    "たとえば、",
    "ちなみに、",
    "一方で、",
]

PREFERRED_BREAKS = [
    "、",
    "ということ",
    "という話",
    "という感じ",
    "というのは",
    "だから",
    "なので",
    "だけど",
    "けど",
    "でも",
    "なら",
    "時に",
    "場合",
    "理由",
    "ために",
    "ように",
    "から",
    "まで",
    "には",
    "では",
    "とは",
    "ても",
]

BAD_ENDINGS = (
    "の",
    "に",
    "を",
    "が",
    "は",
    "で",
    "と",
    "も",
    "や",
    "こと",
    "もの",
    "ため",
    "場合",
    "時",
    "理由",
    "可能性",
    "重要なこと",
    "側と",
    "要素を",
    "報酬を",
    "質問を",
)


def strip_rich_text(text):
    return re.sub(r"\[color=#[0-9a-fA-F]{6}\]([\s\S]*?)\[/color\]", r"\1", text or "")


def normalize_laughter(text):
    output = text or ""
    output = re.sub(r"\[laughter(?: and screaming)?\]", "（笑）", output, flags=re.I)
    output = re.sub(r"\[snorts?\]", "（鼻で笑う）", output, flags=re.I)
    output = re.sub(r"\(\s*（笑）\s*\)", "（笑）", output)
    output = re.sub(r"（\s*（笑）\s*）", "（笑）", output)
    output = re.sub(r"[\(（]+笑[\)）]+", "（笑）", output)
    output = output.replace("（笑）と叫び）", "（笑いと叫び）")
    return output


def protect_text(text):
    mapping = {}

    def store(value, prefix):
        key = chr(0xE000 + len(mapping))
        mapping[key] = value
        return key

    for phrase in PROTECTED_PHRASES:
        text = text.replace(phrase, store(phrase, "PHRASE"))

    result = []
    i = 0
    while i < len(text):
        char = text[i]
        closer = QUOTE_PAIRS.get(char)
        if closer:
            end = text.find(closer, i + 1)
            if end != -1:
                result.append(store(text[i : end + 1], "QUOTE"))
                i = end + 1
                continue
        result.append(char)
        i += 1
    return "".join(result), mapping


def restore_text(text, mapping):
    output = text
    for _ in range(len(mapping) + 1):
        before = output
        for key, value in mapping.items():
            output = output.replace(key, value)
        if output == before:
            break
    return output


def split_japanese_for_shorts(text):
    text = normalize_laughter(strip_rich_text(text).strip())
    if not text:
        return []
    if text in SHORT_WORDS:
        return [text]

    protected, mapping = protect_text(text)
    raw = split_on_sentence_edges(protected)
    pieces = []
    for chunk in raw:
        pieces.extend(split_long_chunk(chunk))

    restored = [restore_text(piece, mapping).strip().lstrip("、") for piece in pieces if piece.strip(" 、")]
    return merge_bad_edges(merge_tiny(restored))


def split_on_sentence_edges(text):
    raw = []
    current = ""
    i = 0
    while i < len(text):
        matched = next((word for word in CONNECTOR_STARTS if text.startswith(word, i)), None)
        if matched and current:
            raw.append(current)
            current = matched
            i += len(matched)
            continue
        current += text[i]
        if text[i] in "。！？!?" or (text[i] == "、" and visible_len(current) >= 18):
            raw.append(current)
            current = ""
        i += 1
    if current:
        raw.append(current)
    return raw


def split_long_chunk(chunk):
    if visible_len(chunk) <= MAX_CHARS:
        return [chunk]
    output = []
    rest = chunk
    while visible_len(rest) > MAX_CHARS:
        cut = best_cut(rest)
        output.append(rest[:cut].strip())
        rest = rest[cut:].lstrip(" 、")
    if rest:
        output.append(rest.strip())
    return output


def best_cut(text):
    window = text[: min(len(text), MAX_CHARS + 1)]
    cuts = []
    for word in PREFERRED_BREAKS:
        start = 0
        while True:
            pos = window.find(word, start)
            if pos == -1:
                break
            cut = pos + len(word)
            if cut >= 14 and not has_bad_boundary(text[:cut], text[cut:]):
                cuts.append(cut)
            start = pos + 1
    if cuts:
        return min(cuts, key=lambda value: abs(visible_len(text[:value]) - TARGET_CHARS))

    for cut in range(min(len(text) - 1, MAX_CHARS), 13, -1):
        if has_bad_boundary(text[:cut], text[cut:]):
            continue
        if re.match(r"[ぁ-んァ-ンー一-龥A-Za-z0-9]", text[cut - 1]) and re.match(r"[ぁ-んァ-ンー一-龥A-Za-z0-9]", text[cut]):
            continue
        return cut
    return len(text)


def has_bad_boundary(left, right):
    left = left.strip(" 、")
    right = right.strip(" 、")
    if not left or not right:
        return False
    if left.endswith(BAD_ENDINGS):
        return True
    if right.startswith(("」", "』", "）", ")", "、", "。")):
        return True
    return quote_unbalanced(left)


def quote_unbalanced(text):
    return text.count("「") > text.count("」") or text.count("『") > text.count("』")


def merge_tiny(pieces):
    output = []
    for piece in pieces:
        if not output:
            output.append(piece)
            continue
        if (visible_len(piece) <= 4 or visible_len(output[-1]) <= 4) and piece not in SHORT_WORDS:
            output[-1] = f"{output[-1]}{piece}"
        else:
            output.append(piece)
    return output


def merge_bad_edges(pieces):
    output = []
    for piece in pieces:
        if not output:
            output.append(piece)
            continue
        prev = output[-1]
        merged = f"{prev}{piece}"
        should_merge = has_bad_boundary(prev, piece) or (
            (visible_len(prev) < 12 or visible_len(piece) < 9) and visible_len(merged) <= MERGE_LIMIT
        )
        if should_merge and visible_len(merged) <= MERGE_LIMIT:
            output[-1] = merged
        else:
            output.append(piece)
    return output


def visible_len(text):
    return sum(6 if 0xE000 <= ord(char) <= 0xF8FF else 1 for char in (text or ""))


def split_english_for_shorts(text):
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return []
    parts = re.split(
        r"(?<=[.!?])\s+|,\s+(?=(?:and|but|so|because|when|if|then|like|you|we|I|that|which|or)\b)",
        clean,
        flags=re.I,
    )
    return [part.strip().rstrip(",") for part in parts if part.strip()]


def align_english_parts(en_parts, ja_parts):
    if not ja_parts:
        return []
    clean_parts = [part for part in en_parts if part]
    if not clean_parts:
        return [""] * len(ja_parts)
    if len(clean_parts) == len(ja_parts):
        return clean_parts
    full = " ".join(clean_parts)
    words = full.split()
    if len(ja_parts) == 1:
        return [full]
    weights = [max(4, len(part)) for part in ja_parts]
    total = sum(weights)
    output = []
    cursor = 0
    for index, weight in enumerate(weights):
        if index == len(weights) - 1:
            output.append(" ".join(words[cursor:]))
            break
        target = round(len(words) * sum(weights[: index + 1]) / total)
        target = max(cursor + 1, min(target, len(words) - (len(weights) - index - 1)))
        output.append(" ".join(words[cursor:target]))
        cursor = target
    return output


def build_segments(row, ja_parts, en_parts):
    start = int(row.get("start_ms", 0))
    end = max(start + MIN_MS, int(row.get("end_ms", start + MIN_MS)))
    duration = end - start
    ja_parts = list(ja_parts)
    max_units = max(1, duration // MIN_MS)
    while len(ja_parts) > max_units:
        merged = []
        for index in range(0, len(ja_parts), 2):
            merged.append("".join(part for part in ja_parts[index : index + 2] if part))
        ja_parts = merged
    weights = [max(4, len(part)) for part in ja_parts]
    total = sum(weights) or len(ja_parts)
    aligned_en = align_english_parts(en_parts, ja_parts)
    cursor = start
    segments = []
    for index, part in enumerate(ja_parts):
        if index == len(ja_parts) - 1:
            seg_end = end
        else:
            seg_end = start + round(duration * sum(weights[: index + 1]) / total)
            seg_end = min(end, max(cursor + MIN_MS, seg_end))
        segments.append(
            {
                "text": part,
                "en": aligned_en[index] if index < len(aligned_en) else "",
                "start_ms": cursor,
                "end_ms": seg_end,
            }
        )
        cursor = segments[-1]["end_ms"]
    return segments


def refresh_row(row):
    row["translation_raw"] = normalize_laughter(row.get("translation_raw", ""))
    row["subtitle_ja"] = row["translation_raw"]
    row["translation"] = row["translation_raw"] if row.get("speaker") == "SFX" else f"({row.get('speaker', 'Group')}) {row['translation_raw']}"
    ja_parts = split_japanese_for_shorts(row["translation_raw"])
    en_parts = split_english_for_shorts(row.get("original", ""))
    row["shorts_segments"] = build_segments(row, ja_parts or [row["translation_raw"]], en_parts)
    row["ja_clauses"] = ja_parts
    row["en_clauses"] = en_parts
    row["shorts_units"] = row["shorts_segments"]


def write_csv(data):
    fields = ["id", "start", "end", "speaker", "topic", "original", "ja", "translation", "subtitle_ja", "subtitle_en", "shorts_split"]
    for path in (CSV_PATH, WORKING_CSV_PATH):
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            for row in data["segments"]:
                writer.writerow(
                    {
                        **{field: row.get(field, "") for field in fields},
                        "ja": row.get("translation_raw", ""),
                        "shorts_split": " / ".join(seg.get("text", "") for seg in row.get("shorts_segments", [])),
                    }
                )


def main():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    report = []
    for row in data["segments"]:
        refresh_row(row)
        parts = row.get("shorts_segments", [])
        if len(parts) > 1 or any(visible_len(part["text"]) > MAX_CHARS for part in parts):
            report.append(
                {
                    "id": row.get("id"),
                    "start": row.get("start"),
                    "end": row.get("end"),
                    "speaker": row.get("speaker"),
                    "count": len(parts),
                    "split": " / ".join(part["text"] for part in parts),
                }
            )
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(data)
    with REPORT_PATH.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["id", "start", "end", "speaker", "count", "split"])
        writer.writeheader()
        writer.writerows(report)
    print("shorts split rows", len(data["segments"]), "split rows", len(report), "segments", sum(len(r.get("shorts_segments", [])) for r in data["segments"]))


if __name__ == "__main__":
    main()
