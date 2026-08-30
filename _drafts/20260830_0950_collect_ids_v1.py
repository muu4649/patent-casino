# -*- coding: utf-8 -*-
"""Google Patents 検索XHRから日本語特許のID一覧を収集する。

出題候補とオッズ算出用コーパスの両方に使う母集団を作る。
"""
import json
import time
import urllib.parse
import urllib.request
import os

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# テーマ: (テーマID, 検索語) — 身近で「発明の名称から中身を想像したくなる」領域を選定
THEMES = [
    ("sushi",      "回転寿司 コンベヤ"),
    ("gate",       "自動改札機"),
    ("toilet",     "温水洗浄便座"),
    ("noodle",     "即席麺 容器"),
    ("gamepad",    "ゲームコントローラ 振動"),
    ("drone",      "無人航空機 配送"),
    ("washer",     "洗濯乾燥機"),
    ("ebike",      "電動アシスト自転車"),
    ("cat",        "ペット用トイレ 猫"),
    ("umbrella",   "傘"),
    ("karaoke",    "カラオケ 採点"),
    ("vending",    "自動販売機"),
    ("qrcode",     "二次元コード 読取"),
    ("foldable",   "折り畳み式 表示装置 ヒンジ"),
    ("coffee",     "コーヒー抽出装置"),
    ("aircon",     "空気調和機 気流"),
    ("razor",      "電気かみそり"),
    ("diaper",     "使い捨ておむつ"),
    ("shoe",       "運動靴 ソール"),
    ("robot",      "掃除ロボット 自律走行"),
]

PAGES = 2   # 1ページ10件 → テーマあたり最大20件
OUT = os.path.join(os.path.dirname(__file__), "20260830_0950_ids_v1.json")


def fetch_page(query, page):
    inner = "q={}&country=JP&language=JAPANESE&page={}".format(
        urllib.parse.quote(query), page)
    url = "https://patents.google.com/xhr/query?url=" + urllib.parse.quote(inner, safe="")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    out = {}
    for theme, query in THEMES:
        hits = []
        for page in range(PAGES):
            try:
                data = fetch_page(query, page)
            except Exception as e:
                print("  ! {} page{} failed: {}".format(theme, page, e))
                continue
            clusters = data.get("results", {}).get("cluster", [])
            for c in clusters:
                for r in c.get("result", []):
                    pid = r.get("id", "")           # 例: patent/JP2010526375A/ja
                    pat = r.get("patent", {})
                    if not pid.startswith("patent/JP"):
                        continue
                    num = pid.split("/")[1]
                    hits.append({
                        "num": num,
                        "title": (pat.get("title") or "").strip(),
                        "assignee": (pat.get("assignee") or "").strip(),
                        "date": (pat.get("publication_date") or "").strip(),
                    })
            time.sleep(0.6)
        # 重複除去
        seen, uniq = set(), []
        for h in hits:
            if h["num"] in seen:
                continue
            seen.add(h["num"])
            uniq.append(h)
        out[theme] = {"query": query, "hits": uniq}
        print("{:10s} {:3d}件  {}".format(theme, len(uniq), query))

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    total = sum(len(v["hits"]) for v in out.values())
    print("---\n合計 {} 件 -> {}".format(total, OUT))


if __name__ == "__main__":
    main()
