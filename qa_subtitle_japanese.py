import csv
import sys
from pathlib import Path


sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROWS = list(csv.DictReader(Path("subtitles_data.csv").open(encoding="utf-8-sig", newline="")))

TERMS = {
    "polite": ["です", "ます", "ました", "ません", "ください", "でしょう", "ございます", "いたします"],
    "broken": ["思ういます", "ありる", "しるよ", "だよだよ", "ますよ", "ましたよ", "でしょうか", "何ですか", "お話したい", "見られますか", "できますか", "しています", "ニース"],
    "machine": ["示唆", "投じ", "取得", "実行", "提供", "非常に", "文脈", "象が", "煮詰める", "投票", "皆さん", "あなた", "私たち", "みなさん"],
    "terms": ["喧嘩屋", "乱闘者", "宝石", "ブロールスターズ", "ブロウル", "乱闘パス", "特徴", "キャラクター", "華麗さ", "熟練", "ビュッフェ", "クレーンゲーム", "ウルトラレジェンド"],
    "bad_end": ["、", "で", "と", "の", "。の", "、。"],
}


def is_long(row):
    return len(row["ja"]) > max(38, int(len(row["original"]) * 1.45))


def main():
    for name, terms in TERMS.items():
        hits = []
        for row in ROWS:
            if name == "bad_end":
                if any(row["ja"].endswith(term) for term in terms):
                    hits.append(row)
            elif any(term in row["ja"] for term in terms):
                hits.append(row)
        print(f"\n{name}: {len(hits)}")
        for row in hits[:120]:
            print(row["id"], row["start"], row["original"], "=>", row["ja"])

    pairs = []
    for index in range(1, len(ROWS)):
        if ROWS[index]["ja"] and ROWS[index]["ja"] == ROWS[index - 1]["ja"]:
            pairs.append((ROWS[index - 1], ROWS[index]))
    print(f"\nadjacent duplicates: {len(pairs)}")
    for a, b in pairs[:80]:
        print(a["id"], b["id"], a["ja"])

    long = [row for row in ROWS if is_long(row)]
    print(f"\nlong: {len(long)}")
    for row in long[:120]:
        print(row["id"], row["start"], row["original"], "=>", row["ja"])


if __name__ == "__main__":
    main()
