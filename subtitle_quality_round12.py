import csv
import json
import re
from pathlib import Path

from shorts_split_round9 import refresh_row, write_csv


ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "subtitles_data.json"
REPORT_PATH = ROOT / "subtitle_quality_round12_report.csv"

MANUAL_TRANSLATION_FIXES = {
    "2": "前回から1年以上経ったから、今回はバフィーや価格、ランダム性まで、みんなが気になっている質問に全部答えるために来たよ。",
}

TERM_FIXES = [
    ("ブローラー", "キャラ"),
    ("ナーフ", "弱体化"),
    ("リード", "リーダー"),
    ("ピアース", "ピアス"),
    ("Brawl Pass", "ブロスタパス"),
    ("Brawlパス", "ブロスタパス"),
    ("Brawl Pass Plus", "ブロスタパスPlus"),
    ("Charlie", "チャーリー"),
    ("Bling", "ジュエルチップ"),
    ("ロア", "世界観"),
]

BAD_JA_ENDINGS = (
    "は。",
    "が。",
    "を。",
    "に。",
    "で。",
    "と。",
    "の。",
    "から。",
    "ので。",
    "ため。",
    "こと。",
    "もの。",
    "、",
)


def word_count(text):
    return len(re.findall(r"[A-Za-z0-9']+", text or ""))


def ja_len(text):
    return len(re.sub(r"\s+", "", text or ""))


def normalize_translation(text):
    output = text or ""
    output = output.replace("(((（笑）)))", "（笑）").replace("((（笑）))", "（笑）")
    output = re.sub(r"[（(]+\s*笑\s*[）)]+", "（笑）", output)
    output = output.replace("思ういます", "思うよ")
    output = output.replace("ブロスタ が", "ブロスタが")
    output = output.replace("  ", " ")
    for old, new in TERM_FIXES:
        output = output.replace(old, new)
    return output.strip()


def likely_undertranslated(row):
    en_words = word_count(row.get("original", ""))
    length = ja_len(row.get("translation_raw", ""))
    if en_words >= 18 and length < en_words * 1.15:
        return True
    if en_words >= 30 and length < en_words * 1.35:
        return True
    return False


def likely_fragment(row):
    ja = row.get("translation_raw", "").strip()
    if not ja:
        return True
    return ja.endswith(BAD_JA_ENDINGS)


def has_connector_gap(row):
    original = row.get("original", "")
    ja = row.get("translation_raw", "")
    connectors = len(re.findall(r"\b(?:and|but|so|because|when|if|then|also|or)\b|,", original, flags=re.I))
    if connectors >= 3 and ja_len(ja) < word_count(original) * 1.5:
        return True
    return False


def main():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    rows = data["segments"]
    report = []

    for row in rows:
        row["quality_flags"] = []
        if row.get("translation_status") == "needs_quality_review":
            row["translation_status"] = "reviewed"
        row_id = str(row.get("id"))
        old = row.get("translation_raw", "")
        fixed = MANUAL_TRANSLATION_FIXES.get(row_id, old)
        fixed = normalize_translation(fixed)
        if fixed != old:
            row["translation_raw"] = fixed
            report.append({"id": row_id, "type": "translation_normalized", "old": old, "new": fixed})

    # Remove exact consecutive duplicates by shortening the previous duplicate.
    for prev, current in zip(rows, rows[1:]):
        if (
            normalize_translation(prev.get("translation_raw", "")) == normalize_translation(current.get("translation_raw", ""))
            and (prev.get("original", "").strip().lower() == current.get("original", "").strip().lower() or ja_len(current.get("translation_raw", "")) > 0)
        ):
            if current["start_ms"] > prev["start_ms"]:
                old_end = prev["end_ms"]
                prev["end_ms"] = min(prev["end_ms"], current["start_ms"])
                report.append({"id": prev.get("id"), "type": "consecutive_duplicate_trim", "old": old_end, "new": prev["end_ms"]})

    for row in rows:
        refresh_row(row)

    for row in rows:
        issue_types = []
        if likely_undertranslated(row):
            issue_types.append("likely_undertranslated")
        if likely_fragment(row):
            issue_types.append("likely_fragment")
        if has_connector_gap(row):
            issue_types.append("connector_gap_risk")
        shorts = row.get("shorts_segments", [])
        for first, second in zip(shorts, shorts[1:]):
            if first["text"] == second["text"] or first.get("en") == second.get("en"):
                issue_types.append("shorts_duplicate")
            if first["end_ms"] > second["start_ms"]:
                issue_types.append("shorts_overlap")
        for unit in shorts:
            if unit["end_ms"] - unit["start_ms"] < 360:
                issue_types.append("too_fast")
        for issue in sorted(set(issue_types)):
            row.setdefault("quality_flags", [])
            if issue not in row["quality_flags"]:
                row["quality_flags"].append(issue)
            row["translation_status"] = "needs_quality_review"
            report.append(
                {
                    "id": row.get("id"),
                    "start": row.get("start"),
                    "end": row.get("end"),
                    "type": issue,
                    "original": row.get("original", ""),
                    "ja": row.get("translation_raw", ""),
                    "shorts": " / ".join(unit.get("text", "") for unit in shorts),
                }
            )

    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(data)

    fields = ["id", "start", "end", "type", "original", "ja", "shorts", "old", "new"]
    with REPORT_PATH.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows([{field: item.get(field, "") for field in fields} for item in report])
    print("round12 report", len(report), REPORT_PATH)


if __name__ == "__main__":
    main()
