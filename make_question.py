# -*- coding: utf-8 -*-
"""請求項を貼り付けるだけで、出題データ（JSON）を1問作るツール。

    python3 make_question.py

対話形式で 発明の名称 → 出願人 → 請求項1 → 請求項2 を入力すると、
  - 請求項に出る語（正解語）を形態素解析で抜き出し
  - 収録済みの特許から「似た分野なのにこの請求項には出ない語」を罠語として選び
  - どちらにも出現頻度からオッズを付けて
data/questions_custom.json に追記する。

オッズや罠語は後から手で直してよい。最終的な正解判定は
「その語が請求項本文に含まれるか」の文字列マッチなので、
words をどう並べ替えても答え合わせは自動で正しく動く。
"""
import io
import json
import math
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
OUT = os.path.join(DATA_DIR, "questions_custom.json")
CORPUS = os.path.join(HERE, "_drafts", "20260830_1010_claims_v1.jsonl")

NEED_HIT, NEED_MIS = 4, 8       # ゲームがボードを作るのに必要な数
WANT_HIT, WANT_MIS = 8, 12      # 余裕をもって収録する数
ODDS_MIN, ODDS_MAX = 1.2, 30.0

PREFIX_RE = re.compile(r"^(前記|上記|当該|該|本)")
TAIL_RE = re.compile(r"(可能|的|性|化|時|後|前|中|上|下|内|外)$")
STOP = set("""
前記 上記 当該 該 これら それら もの こと ため 場合 際 とき 両者 以下 以上 未満
少なくとも いずれか および 並びに 又は 若しくは ここで なお また さらに ただし
本発明 発明 実施 形態 特徴 記載 請求項 明細書 図面
第一 第二 第三 第１ 第２ 第３ 一つ 二つ 単数
""".split())
KEEP_SHORT = set("皿 傘 靴 蓋 軸 弁 管 板 棒 網 膜 液 粉 熱 光 音 風 水 油 泡 糸 鍵 錠 爪 歯 溝 孔 穴".split())

try:
    from janome.tokenizer import Tokenizer
except ImportError:
    sys.exit("janome が必要です:  pip install janome")

_t = Tokenizer()


def extract_words(text):
    words, buf = [], []
    for tok in _t.tokenize(text):
        ps = tok.part_of_speech.split(",")
        sf = tok.surface
        if ps[0] == "名詞" and ps[1] not in ("数", "代名詞", "非自立", "接尾") \
                and not re.match(r"^[0-9０-９a-zA-Z]+$", sf):
            buf.append(sf)
        else:
            if ps[0] == "名詞" and ps[1] == "接尾" and buf:
                buf.append(sf)
                continue
            if buf:
                words.append("".join(buf))
                buf = []
    if buf:
        words.append("".join(buf))

    out = []
    for w in words:
        w = PREFIX_RE.sub("", w)
        if not w or w in STOP or TAIL_RE.search(w):
            continue
        if len(w) == 1 and w not in KEEP_SHORT:
            continue
        if len(w) > 12 or re.search(r"[0-9０-９]", w):
            continue
        out.append(w)
    return out


def load_corpus():
    """収録済みの請求項。罠語の出所とオッズの基準に使う。"""
    recs = []
    if os.path.exists(CORPUS):
        for line in io.open(CORPUS, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if not r.get("claims"):
                continue
            body = "\n".join(c["text"] for c in r["claims"])
            recs.append(set(extract_words(body)))
    for p in (sorted(os.listdir(DATA_DIR)) if os.path.isdir(DATA_DIR) else []):
        if not p.endswith(".json") or p.startswith("_"):
            continue
        try:
            d = json.load(io.open(os.path.join(DATA_DIR, p), encoding="utf-8"))
        except Exception:
            continue
        for it in d.get("items", []):
            body = "\n".join(c["text"] for c in it.get("claims", []))
            if body:
                recs.append(set(extract_words(body)))
    return recs


def band(o):
    return 0 if o < 2.5 else (1 if o <= 7 else 2)


def take_balanced(pool, want):
    by = [[], [], []]
    for w in pool:
        by[band(w["odds"])].append(w)
    out, i = [], 0
    while len(out) < want and any(by):
        b = by[i % 3]
        if b:
            out.append(b.pop(0))
        i += 1
        if i > want * 6:
            break
    return out


def read_block(prompt):
    """複数行を読む。空行2回、または . だけの行で終了。"""
    print(prompt)
    print("  （貼り付けたら、空行を2回入れるか . だけの行で確定）")
    lines, blank = [], 0
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == ".":
            break
        if line.strip() == "":
            blank += 1
            if blank >= 2:
                break
            lines.append("")
            continue
        blank = 0
        lines.append(line)
    return "\n".join(lines).strip()


def main():
    print("=" * 58)
    print(" 特許カジノ - 問題づくり")
    print("=" * 58)

    title = input("発明の名称: ").strip()
    if not title:
        sys.exit("発明の名称は必須です")
    assignee = input("出願人（任意、Enterで空欄）: ").strip()
    date = input("出願年（任意 例 2023）: ").strip()
    ipc = input("IPC（任意 例 A47F 10/06）: ").strip()
    hint = input("ヒント（任意。画面に出る一言）: ").strip()
    num = input("公開番号など（任意 例 JP6935980B2）: ").strip()

    c1 = read_block("\n請求項1の本文:")
    if not c1:
        sys.exit("請求項1は必須です")
    c2 = read_block("\n請求項2の本文（無ければ空行2回でスキップ）:")

    claims = [{"num": "1", "text": c1}]
    if c2:
        claims.append({"num": "2", "text": c2})
    body = "\n".join(c["text"] for c in claims)

    mine = set(extract_words(body))
    if len(mine) < NEED_HIT:
        sys.exit("請求項から十分な語を抽出できませんでした（{}語）".format(len(mine)))

    corpus = load_corpus()
    corpus.append(mine)
    N = len(corpus)
    df = Counter()
    for ws in corpus:
        df.update(ws)

    ordered = sorted(df.items(), key=lambda x: (-x[1], x[0]))
    last = max(1, len(ordered) - 1)
    rank = dict((w, i / float(last)) for i, (w, _c) in enumerate(ordered))
    title_words = set(extract_words(title))

    def odds_of(w, in_title=False):
        o = ODDS_MIN * math.pow(ODDS_MAX / ODDS_MIN, rank.get(w, 1.0))
        if in_title:
            o *= 0.55
        return round(max(ODDS_MIN, min(ODDS_MAX, o)), 1)

    hits = [{"w": w, "odds": odds_of(w, w in title_words), "tier": "real"} for w in mine]
    hits.sort(key=lambda x: x["odds"])

    # 罠語: 語彙が似ている収録済み特許に出るが、この請求項には出ない語
    sims = []
    for ws in corpus:
        if ws is mine:
            continue
        inter = len(mine & ws)
        if inter:
            sims.append((inter / float(len(mine | ws)), ws))
    sims.sort(key=lambda x: -x[0])
    near = Counter()
    for _s, ws in sims[:6]:
        near.update(ws)
    miss = [{"w": w, "odds": odds_of(w), "tier": "trap", "n": c}
            for w, c in near.items() if w not in mine]
    miss.sort(key=lambda x: (-x["n"], -df[x["w"]]))

    hsel = take_balanced(hits, WANT_HIT)
    msel = take_balanced(miss, WANT_MIS)

    def bands_filled(sel):
        return all(any(band(w["odds"]) == b for w in sel) for b in (0, 1, 2))

    BAND_NAME = ["低（1.2〜2.4倍）", "中（2.5〜7.0倍）", "高（7.1倍〜）"]

    print("\n" + "-" * 58)
    print("正解語 {} 語 / 罠語 {} 語".format(len(hsel), len(msel)))
    for w in sorted(hsel + msel, key=lambda x: x["odds"]):
        print("  {:5.1f}倍  {}  {}".format(
            w["odds"], "出る  " if w["tier"] == "real" else "出ない", w["w"]))
    print("-" * 58)

    problems = []
    if len(hsel) < NEED_HIT:
        problems.append("正解語が {} 語しかありません（{}語必要）".format(len(hsel), NEED_HIT))
    if len(msel) < NEED_MIS:
        problems.append("罠語が {} 語しかありません（{}語必要）".format(len(msel), NEED_MIS))
    for b in (0, 1, 2):
        h = [w["w"] for w in hsel if band(w["odds"]) == b]
        m = [w["w"] for w in msel if band(w["odds"]) == b]
        if not h:
            problems.append("{} に正解語がありません".format(BAND_NAME[b]))
        if not m:
            problems.append("{} に罠語がありません".format(BAND_NAME[b]))
    if problems:
        print("このままでは遊べません:")
        for msg in problems:
            print("  - " + msg)
        print("")
        print("直し方:")
        print("  ・帯に語が足りない → 保存したJSONの words に、その帯のオッズで語を足す")
        print("    （請求項に出る語なら正解語、出ない語なら罠語として扱われます）")
        print("  ・罠語そのものが少ない → 収録済みデータを増やすと候補が広がります")
        print("  片方の帯だけ正解語で埋まっていると、オッズを見ただけで正解が分かってしまいます。")
        if input("それでも保存しますか? [y/N]: ").strip().lower() != "y":
            sys.exit("中止しました")

    item = {
        "id": num or re.sub(r"\s+", "_", title)[:40],
        "source": "real" if num else "custom",
        "num": num or "",
        "title": title,
        "assignee": assignee,
        "date": date,
        "ipc": ipc,
        "theme": "",
        "hint": hint,
        "url": "https://patents.google.com/patent/{}/ja".format(num) if num else "",
        "claims": claims,
        "words": sorted(
            [{"w": w["w"], "odds": w["odds"], "tier": w["tier"]} for w in (hsel + msel)],
            key=lambda x: x["odds"]),
    }

    doc = {"schema_version": 2, "items": []}
    if os.path.exists(OUT):
        try:
            doc = json.load(io.open(OUT, encoding="utf-8"))
        except Exception:
            pass
    doc.setdefault("items", [])
    doc["items"] = [x for x in doc["items"] if x.get("id") != item["id"]]
    doc["items"].append(item)

    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write(json.dumps(doc, ensure_ascii=False, indent=1))

    print("\n保存しました: {}（合計 {} 問）".format(OUT, len(doc["items"])))
    print("次のコマンドでゲームに反映されます:")
    print("    python3 build.py")


if __name__ == "__main__":
    main()
