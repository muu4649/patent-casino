# -*- coding: utf-8 -*-
"""data/*.json の設問をマージして src/template.html に埋め込み、index.html を生成する。

file:// で開くと fetch が使えないため、問題データはHTMLに直接埋め込む方式にしている。
実データを追加したら data/ に置いて再実行するだけでよい。

    python3 build.py
"""
import glob
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(HERE, "src", "template.html")
OUT = os.path.join(HERE, "index.html")
DATA_DIR = os.path.join(HERE, "data")


def load_items():
    items, seen = [], set()
    # _ で始まるファイルはテンプレートや下書き扱いで読み込まない
    files = [p for p in sorted(glob.glob(os.path.join(DATA_DIR, "*.json")))
             if not os.path.basename(p).startswith("_")]
    if not files:
        sys.exit("data/ に JSON がありません")
    for p in files:
        with io.open(p, encoding="utf-8") as f:
            d = json.load(f)
        n = 0
        for it in d.get("items", []):
            if it["id"] in seen:
                print("  重複スキップ: {}".format(it["id"]))
                continue
            seen.add(it["id"])
            items.append(it)
            n += 1
        print("  {:40s} {:3d}問".format(os.path.basename(p), n))
    return items


# template.html の BOARD_HIT / BOARD_MIS と揃えること
NEED_HIT = 4
NEED_MIS = 8


def check(items):
    """埋め込む前に最低限の妥当性を見る。"""
    ng = 0
    for it in items:
        body = "\n".join(c["text"] for c in it["claims"])
        hit = [w for w in it["words"] if w["w"] in body]
        mis = [w for w in it["words"] if w["w"] not in body]
        if len(hit) < NEED_HIT or len(mis) < NEED_MIS:
            print("  ! {} 正解{}語/罠{}語 — ボード生成に必要な 正解{}・罠{} を下回ります".format(
                it["id"], len(hit), len(mis), NEED_HIT, NEED_MIS))
            ng += 1
        elif len(hit) < NEED_HIT + 2 or len(mis) < NEED_MIS + 2:
            print("  - {} 正解{}語/罠{}語 — 動くが毎回ほぼ同じボードになります".format(
                it["id"], len(hit), len(mis)))
    return ng


def main():
    print("data を読み込み:")
    items = load_items()
    print("合計 {} 問".format(len(items)))

    print("妥当性チェック:")
    ng = check(items)
    if ng:
        print("  {} 問に問題があります（そのまま埋め込みます）".format(ng))
    else:
        print("  OK")

    with io.open(TPL, encoding="utf-8") as f:
        html = f.read()
    if "__QUESTIONS_JSON__" not in html:
        sys.exit("テンプレートに __QUESTIONS_JSON__ がありません")

    payload = json.dumps({"items": items}, ensure_ascii=False, separators=(",", ":"))
    # </script> がデータ中にあるとHTMLが壊れるため無害化
    payload = payload.replace("</", "<\\/")
    html = html.replace("__QUESTIONS_JSON__", payload)

    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print("生成: {} ({:,} bytes)".format(OUT, os.path.getsize(OUT)))


if __name__ == "__main__":
    main()
