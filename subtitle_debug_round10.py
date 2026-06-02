import csv
import json
from pathlib import Path

from shorts_split_round9 import DATA_PATH, REPORT_PATH, write_csv


ROOT = Path(__file__).resolve().parent
DEBUG_REPORT_PATH = ROOT / "subtitle_debug_round10_report.csv"


def ms_to_ts(ms):
    total = int(ms) // 1000
    return f"{total // 3600}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def main():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    rows = sorted(data["segments"], key=lambda row: (row["start_ms"], row["end_ms"], str(row["id"])))
    report = []

    for prev, current in zip(rows, rows[1:]):
        overlap = prev["end_ms"] - current["start_ms"]
        if current["start_ms"] > prev["start_ms"] and overlap > 0:
            old_end = prev["end_ms"]
            prev["end_ms"] = current["start_ms"]
            prev["end"] = ms_to_ts(prev["end_ms"])
            for unit in prev.get("shorts_segments", []):
                if unit.get("end_ms", 0) > prev["end_ms"]:
                    unit["end_ms"] = prev["end_ms"]
            prev["shorts_units"] = prev.get("shorts_segments", prev.get("shorts_units", []))
            report.append(
                {
                    "type": "trim_tiny_overlap",
                    "id": prev.get("id"),
                    "next_id": current.get("id"),
                    "old_end_ms": old_end,
                    "new_end_ms": prev["end_ms"],
                    "overlap_ms": overlap,
                }
            )

    mojibake_tokens = ["縺", "繧", "譁", "蛻", "陦", "蜍", "\ufffd", "???"]
    for row in rows:
        for key in ("original", "translation_raw"):
            value = row.get(key, "") or ""
            if any(token in value for token in mojibake_tokens):
                report.append({"type": "mojibake_like_text", "id": row.get("id"), "field": key, "value": value[:120]})
        for index, unit in enumerate(row.get("shorts_segments", [])):
            if unit["end_ms"] <= unit["start_ms"]:
                report.append({"type": "invalid_shorts_time", "id": row.get("id"), "unit": index})
            for key in ("text", "en"):
                value = unit.get(key, "") or ""
                if any(token in value for token in mojibake_tokens):
                    report.append({"type": "mojibake_like_shorts", "id": row.get("id"), "unit": index, "field": key, "value": value[:120]})

    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(data)
    with DEBUG_REPORT_PATH.open("w", encoding="utf-8-sig", newline="") as file:
        fields = ["type", "id", "next_id", "field", "unit", "old_end_ms", "new_end_ms", "overlap_ms", "value"]
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in fields} for row in report])
    print("debug report rows", len(report), "path", DEBUG_REPORT_PATH)


if __name__ == "__main__":
    main()
