import csv
import json
import re
import subprocess
import uuid
from pathlib import Path

import imageio_ffmpeg
from flask import Flask, jsonify, request, send_file, send_from_directory, Response


ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "subtitles_data.json"
CSV_PATH = ROOT / "subtitles_data.csv"
ORIGINAL_CSV_PATH = ROOT / "original_subtitles.csv"
SPEAKER_AUDIT_PATH = ROOT / "speaker_review_report.csv"
EXPORT_DIR = ROOT / "exports"
EXPORT_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder="webapp", static_url_path="")


def ass_time(ms):
    cs = max(0, int(ms)) // 10
    return f"{cs // 360000}:{(cs % 360000) // 6000:02d}:{(cs % 6000) // 100:02d}.{cs % 100:02d}"


def parse_ts(value):
    parts = [int(part) for part in value.strip().split(":")]
    if len(parts) == 2:
        parts = [0] + parts
    return ((parts[0] * 60 + parts[1]) * 60 + parts[2]) * 1000


def ass_color(hex_color):
    return ass_color_alpha(hex_color, 0)


def ass_color_alpha(hex_color, alpha):
    value = (hex_color or "#000000").lstrip("#")
    if len(value) < 6:
        value = "000000"
    r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def ffmpeg_color(value):
    value = (value or "#000000").strip()
    if value.startswith("#"):
        color = value.lstrip("#")
        return f"0x{color}" if len(color) in (6, 8) else "0x000000"
    match = re.match(r"rgba?\(([^)]+)\)", value, flags=re.I)
    if match:
        parts = [part.strip() for part in match.group(1).split(",")]
        if len(parts) >= 3:
            try:
                r, g, b = [max(0, min(255, int(float(part)))) for part in parts[:3]]
                return f"0x{r:02x}{g:02x}{b:02x}"
            except ValueError:
                pass
    return "0x000000"


def escape_ass(text):
    return re.sub(r"[{}]", "", text or "").replace("\n", r"\N")


def strip_rich_text(text):
    return re.sub(r"\[color=#[0-9a-fA-F]{6}\]([\s\S]*?)\[/color\]", r"\1", text or "")


def rich_text_to_ass(text):
    text = re.sub(r"[{}]", "", text or "")
    pattern = re.compile(r"\[color=(#[0-9a-fA-F]{6})\]([\s\S]*?)\[/color\]")
    output = []
    pos = 0
    for match in pattern.finditer(text):
        output.append(text[pos : match.start()].replace("\n", r"\N"))
        output.append(r"{\c" + ass_color(match.group(1)) + "}")
        output.append(match.group(2).replace("\n", r"\N"))
        output.append(r"{\c}")
        pos = match.end()
    output.append(text[pos:].replace("\n", r"\N"))
    return "".join(output)


def pop_ass(text, enabled):
    if not enabled:
        return text
    return r"{\fscx84\fscy84\t(0,140,\fscx110\fscy110)\t(140,240,\fscx100\fscy100)}" + text


def wrap_plain_text(text, lang, max_chars):
    text = re.sub(r"\s+", " ", strip_rich_text(text or "")).strip()
    if not text:
        return ""
    if lang == "en":
        return wrap_english(text, max_chars)
    return wrap_japanese(text, max_chars)


def wrap_japanese(text, max_chars):
    protected = []

    def keep(match):
        key = f"__Q{len(protected)}__"
        protected.append((key, match.group(0)))
        return key

    text = re.sub(r"「[^」]*」|『[^』]*』|“[^”]*”|\"[^\"]*\"", keep, text)
    chunks = []
    current = ""
    for char in text:
        current += char
        if char in "。！？!?" or (char == "、" and len(current) >= max(8, max_chars // 2)):
            chunks.append(current.strip())
            current = ""
    if current.strip():
        chunks.append(current.strip())

    lines = []
    for chunk in chunks:
        while len(chunk) > max_chars:
            cut = best_jp_line_cut(chunk, max_chars)
            lines.append(chunk[:cut].strip())
            chunk = chunk[cut:].lstrip("、 ")
        if chunk:
            lines.append(chunk)

    lines = balance_last_line(lines, max_chars)
    output = r"\N".join(lines)
    for key, value in protected:
        output = output.replace(key, value)
    return output


def best_jp_line_cut(text, max_chars):
    if len(text) <= max_chars + 3 and re.fullmatch(r"[、。！？!?]+", text[max_chars:]):
        return len(text)
    window = text[: max_chars + 1]
    preferred = ["、", "という", "ことに", "だから", "なので", "だけど", "けど", "でも", "なら", "から", "まで", "には", "では", "とは"]
    bad_endings = ("の", "に", "を", "が", "は", "で", "と", "も", "や", "こと", "もの", "ため", "場合")
    candidates = []
    for token in preferred:
        start = 0
        while True:
            pos = window.find(token, start)
            if pos < 0:
                break
            cut = pos + len(token)
            allowed_particle_cut = token in {"ことに", "には", "では", "とは"}
            if cut >= 8 and (allowed_particle_cut or not text[:cut].rstrip("、").endswith(bad_endings)):
                candidates.append(cut)
            start = pos + 1
    if candidates:
        return min(candidates, key=lambda cut: abs(cut - max_chars * 0.72))
    for cut in range(min(max_chars, len(text) - 1), 8, -1):
        if text[:cut].endswith(bad_endings):
            continue
        if re.match(r"[ぁ-んァ-ンー一-龯A-Za-z0-9]", text[cut - 1]) and re.match(r"[ぁ-んァ-ンー一-龯A-Za-z0-9]", text[cut]):
            continue
        return cut + 1 if cut < len(text) and text[cut] in "、。！？!?" else cut
    for cut in range(min(max_chars + 1, len(text) - 1), min(max_chars + 10, len(text))):
        if re.match(r"[ぁ-んァ-ンー一-龯A-Za-z0-9]", text[cut - 1]) and re.match(r"[ぁ-んァ-ンー一-龯A-Za-z0-9]", text[cut]):
            continue
        return cut + 1 if cut < len(text) and text[cut] in "、。！？!?" else cut
    return len(text)


def wrap_english(text, max_chars):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return r"\N".join(balance_last_line(lines, max_chars))


def balance_last_line(lines, max_chars):
    if len(lines) < 2:
        return lines
    if len(lines[-1]) >= max(5, max_chars // 4):
        return lines
    prev = lines[-2]
    if " " in prev:
        words = prev.split()
        if len(words) > 1:
            moved = words.pop()
            lines[-2] = " ".join(words)
            lines[-1] = f"{moved} {lines[-1]}".strip()
    elif len(prev) > max_chars // 2:
        cut = max(max_chars // 2, len(prev) - max(5, max_chars // 4))
        lines[-2] = prev[:cut]
        lines[-1] = prev[cut:] + lines[-1]
    return [line for line in lines if line]


def rich_wrapped_text_to_ass(text, lang, max_chars):
    # Inline color editing is preserved before wrapping only when no color tag is
    # present. Colored runs can span arbitrary ranges, so keep them unwrapped.
    if "[color=" in (text or ""):
        return rich_text_to_ass(text)
    return escape_ass(wrap_plain_text(text, lang, max_chars))


def one_line_ass(text):
    clean = re.sub(r"\s+", " ", text or "").strip()
    if "[color=" in clean:
        return rich_text_to_ass(clean).replace(r"\N", " ")
    return escape_ass(clean).replace(r"\N", " ")


def fitted_font_size(text, lang, base_size, text_area):
    clean = strip_rich_text(text or "")
    jp_units = sum(1.0 if ord(char) > 255 else 0.62 for char in clean)
    factor = 1.03 if lang == "ja" else 0.62
    estimated = max(1, jp_units * base_size * factor)
    if estimated <= text_area:
        return base_size
    return max(10, int(base_size * text_area / estimated))


def load_data():
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def json_response(payload):
    return Response(
        json.dumps(payload, ensure_ascii=False),
        content_type="application/json; charset=utf-8",
    )


def save_data(data):
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = ["id", "start", "end", "speaker", "topic", "original", "ja", "translation", "subtitle_ja", "subtitle_en", "ja_clauses"]
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            [
                {
                    **{key: row.get(key, "") for key in fields},
                    "ja": row.get("translation_raw", row.get("subtitle_ja", "")),
                    "ja_clauses": " / ".join(row.get("ja_clauses", [])),
                }
                for row in data["segments"]
            ]
        )
    with ORIGINAL_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["id", "start", "end", "speaker", "topic", "original"])
        writer.writeheader()
        writer.writerows([{key: row.get(key, "") for key in ["id", "start", "end", "speaker", "topic", "original"]} for row in data["segments"]])


def build_export_rows(data, settings, start_ms, end_ms):
    rows = [
        row
        for row in data["segments"]
        if not (row["end_ms"] <= start_ms or row["start_ms"] >= end_ms)
    ]
    if settings.get("format") != "short" or not settings.get("shortsClauseMode", True):
        return trim_tiny_overlaps(rows)

    chunked_rows = []
    for row in rows:
        units = row.get("shorts_segments") or row.get("shorts_units") or []
        if not units:
            chunked_rows.append(row)
            continue
        for index, unit in enumerate(units):
            unit_start = max(int(unit.get("start_ms", row["start_ms"])), row["start_ms"])
            unit_end = min(int(unit.get("end_ms", row["end_ms"])), row["end_ms"])
            if unit_end <= start_ms or unit_start >= end_ms or unit_end <= unit_start:
                continue
            chunked = dict(row)
            chunked["id"] = f"{row.get('id')}.short.{index}"
            chunked["start_ms"] = unit_start
            chunked["end_ms"] = unit_end
            chunked["translation_raw"] = unit.get("text", row.get("translation_raw", ""))
            chunked["original"] = unit.get("en", "")
            chunked_rows.append(chunked)
    return trim_tiny_overlaps(chunked_rows)


def trim_tiny_overlaps(rows):
    output = [dict(row) for row in sorted(rows, key=lambda item: (item["start_ms"], item["end_ms"], str(item["id"])))]
    for index, row in enumerate(output[:-1]):
        next_row = output[index + 1]
        overlap = row["end_ms"] - next_row["start_ms"]
        if next_row["start_ms"] > row["start_ms"] and overlap > 0:
            row["end_ms"] = next_row["start_ms"]
    for index, row in enumerate(output):
        if row["end_ms"] - row["start_ms"] >= 650:
            continue
        if index + 1 < len(output) and output[index + 1]["start_ms"] - row["end_ms"] >= 250:
            row["end_ms"] = min(row["start_ms"] + 650, output[index + 1]["start_ms"])
        elif index > 0 and row["start_ms"] - output[index - 1]["end_ms"] >= 250:
            row["start_ms"] = max(row["end_ms"] - 650, output[index - 1]["end_ms"])
    return [row for row in output if row["end_ms"] > row["start_ms"]]


def render_subtitle_asset(export_rows, settings, start_ms, end_ms, lang):
    width, height = (1920, 420) if settings["format"] == "long" else (1080, 620)
    uid = uuid.uuid4().hex[:8]
    out_name = f"subtitle_asset_{lang}_{uid}.mp4"
    ass_path = EXPORT_DIR / f"{out_name}.ass"
    out_path = EXPORT_DIR / out_name
    scale = 1.0 if width <= 1080 else width / 1920
    ja_size = max(12, int(settings["fontSize"] * scale * int(settings.get("videoJaScale", 100)) / 100))
    en_size = max(12, int(settings["fontSize"] * scale * int(settings.get("videoEnScale", 72)) / 100))
    font_size = ja_size if lang == "ja" else en_size
    outline_size = max(0, int(settings.get("outlineSize", 4) * scale))
    if lang == "en":
        outline_size = max(0, int(outline_size * 0.78))
    shadow_x = int(settings.get("shadowX", 2) * scale * (0.8 if lang == "en" else 1.0))
    shadow_y = max(0, int(settings.get("shadowY", 4) * scale * (0.85 if lang == "en" else 1.0)))
    shadow_alpha = int(255 * (100 - int(settings.get("shadowOpacity", 100))) / 100)
    overlay_width = int(settings.get("overlayWidth", settings.get("textWidth", 92)))
    overlay_x = int(settings.get("overlayX", 50))
    overlay_bottom = int(settings.get("overlayBottom", 7))
    overlay_gap = int(settings.get("overlayGap", 10) * scale)
    left_pct = max(0, overlay_x - overlay_width / 2)
    right_pct = max(0, 100 - (overlay_x + overlay_width / 2))
    margin_l = int(width * left_pct / 100)
    margin_r = int(width * right_pct / 100)
    bottom_base = int(height * overlay_bottom / 100)
    bottom_margin = bottom_base if lang == "en" else bottom_base + int(en_size * 1.28) + overlay_gap
    bg = ffmpeg_color(settings["bgColor"])
    font_name = "Noto Sans CJK JP Black" if lang == "ja" else "Lilita One"
    primary = ass_color(settings["jpColor"] if lang == "ja" else settings["enColor"])
    outline = ass_color(settings.get("outlineColor", "#050505"))
    shadow = ass_color_alpha(settings.get("shadowColor", "#000000"), shadow_alpha)
    text_area = max(120, width - margin_l - margin_r)

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Shadow,{font_name},{font_size},{shadow},&H000000FF,{shadow},&H00000000,-1,0,0,0,100,100,0,0,1,0,0,2,{max(0, margin_l + shadow_x)},{max(0, margin_r - shadow_x)},{bottom_margin + shadow_y},1",
        f"Style: Main,{font_name},{font_size},{primary},&H000000FF,{outline},&H00000000,-1,0,0,0,100,100,0,0,1,{outline_size},0,2,{margin_l},{margin_r},{bottom_margin},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for row in sorted(export_rows, key=lambda item: (item["start_ms"], item["end_ms"], str(item["id"]))):
        st_abs = max(row["start_ms"], start_ms)
        en_abs = min(row["end_ms"], end_ms)
        if en_abs <= st_abs:
            continue
        st = st_abs - start_ms
        en = en_abs - start_ms
        text = row.get("translation_raw", "") if lang == "ja" else row.get("original", "")
        if not text:
            continue
        if lang == "ja" and settings["speakerMode"] == "name" and row.get("speaker") != "SFX":
            text = f"({row.get('speaker', 'Team')}) {text}"
        max_chars = max(8, int(text_area / max(1, font_size) * (1.25 if lang == "ja" else 1.65)))
        ass_text = rich_wrapped_text_to_ass(text, lang, max_chars)
        ass_text = pop_ass(ass_text, settings.get("popAnimation", True))
        lines.append(f"Dialogue: 0,{ass_time(st)},{ass_time(en)},Shadow,,{max(0, margin_l + shadow_x)},{max(0, margin_r - shadow_x)},{bottom_margin + shadow_y},,{ass_text}")
        lines.append(f"Dialogue: 1,{ass_time(st)},{ass_time(en)},Main,,{margin_l},{margin_r},{bottom_margin},,{ass_text}")

    ass_path.write_text("\n".join(lines), encoding="utf-8-sig")
    duration = (end_ms - start_ms) / 1000
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={bg}:s={width}x{height}:r=30:d={duration}",
        "-vf",
        f"subtitles={ass_path.name}:fontsdir=..:charenc=UTF-8",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(out_path),
    ]
    proc = subprocess.run(cmd, cwd=EXPORT_DIR, text=True, capture_output=True)
    if proc.returncode:
        raise RuntimeError(proc.stderr[-3000:])
    return out_name


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/data")
def api_data():
    return json_response(load_data())


@app.post("/api/save")
def api_save():
    payload = request.get_json(force=True)
    save_data(payload)
    return json_response({"ok": True})


@app.get("/video")
def video():
    preview = ROOT / "video_preview.mp4"
    source = preview if preview.exists() else ROOT / "video.webm"
    return send_file(source, conditional=True)


@app.get("/fonts/<name>")
def font(name):
    allowed = {"LilitaOne-Regular.ttf", "NotoSansCJKjp-Black.otf"}
    if name not in allowed:
        return ("not found", 404)
    return send_file(ROOT / name)


@app.get("/original_subtitles.csv")
def original_csv():
    return send_file(
        ORIGINAL_CSV_PATH,
        as_attachment=True,
        download_name="original_subtitles.csv",
        mimetype="text/csv",
    )


@app.get("/subtitles_data.csv")
def translated_csv():
    return send_file(
        CSV_PATH,
        as_attachment=True,
        download_name="subtitles_data_utf8.csv",
        mimetype="text/csv",
    )


@app.get("/subtitles_data_excel.csv")
def translated_csv_excel():
    text = CSV_PATH.read_text(encoding="utf-8-sig")
    return Response(
        text.encode("cp932", errors="replace"),
        headers={"Content-Disposition": "attachment; filename=subtitles_data_excel_cp932.csv"},
        content_type="text/csv; charset=shift_jis",
    )


@app.get("/speaker_review_report.csv")
def speaker_review_report():
    return send_file(
        SPEAKER_AUDIT_PATH,
        as_attachment=True,
        download_name="speaker_review_report.csv",
        mimetype="text/csv",
    )


@app.post("/api/export")
def api_export():
    payload = request.get_json(force=True)
    data = payload["data"]
    settings = payload["settings"]
    start_ms = parse_ts(settings["start"])
    end_ms = parse_ts(settings["end"])
    export_rows = build_export_rows(data, settings, start_ms, end_ms)
    try:
        jp_name = render_subtitle_asset(export_rows, settings, start_ms, end_ms, "ja")
        en_name = render_subtitle_asset(export_rows, settings, start_ms, end_ms, "en")
    except RuntimeError as error:
        return jsonify({"ok": False, "error": str(error)}), 500
    return jsonify(
        {
            "ok": True,
            "jp_url": f"/exports/{jp_name}",
            "en_url": f"/exports/{en_name}",
            "url": f"/exports/{jp_name}",
        }
    )


@app.get("/exports/<name>")
def exports(name):
    return send_from_directory(EXPORT_DIR, name, as_attachment=True)


if __name__ == "__main__":
    app.run("127.0.0.1", 8787, debug=False)
