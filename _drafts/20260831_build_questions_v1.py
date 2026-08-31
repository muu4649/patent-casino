# -*- coding: utf-8 -*-
"""取得した請求項から、出題用JSON（data/questions_real.json）を生成する。

オッズは実測のDF（その語がコーパス中の何件の請求項に出るか）から決める。
    odds = 1 / p     p = df / N
ありふれた語ほど低オッズ、固有の語ほど高オッズになる。

罠語は「同じテーマの他特許の請求項には出るが、この特許には出ない語」から選ぶ。
同分野で実際に使われている語なので「出そうなのに無い」という質の高い罠になり、
DFから算出したオッズが正解語と同じ帯に自然に分布するため、
オッズを見ても正解が割れない。

    python3 _drafts/20260831_build_questions_v1.py
"""
import io
import json
import math
import os
import re
from collections import Counter, defaultdict

from janome.tokenizer import Tokenizer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(HERE, "20260830_1010_claims_v1.jsonl")
OUT = os.path.join(ROOT, "data", "questions_real.json")

# ゲーム側の要件（template.html と揃える）
NEED_HIT = 4
NEED_MIS = 8
TITLE_MAX = 40      # 名称が長すぎると読む負担が大きく、カードでも崩れる

THEME_JA = {
    "sushi": "回転寿司", "gate": "自動改札", "toilet": "温水洗浄便座",
    "noodle": "即席麺", "gamepad": "ゲームコントローラ", "drone": "ドローン",
    "washer": "洗濯乾燥機", "ebike": "電動アシスト自転車", "cat": "ペット用トイレ",
    "umbrella": "傘", "karaoke": "カラオケ", "vending": "自動販売機",
    "qrcode": "二次元コード", "foldable": "折り畳み表示装置", "coffee": "コーヒー抽出",
    "aircon": "空気調和機", "razor": "電気かみそり", "diaper": "使い捨ておむつ",
}
# 余裕をもって収録する（毎回同じボードにならないように）
WANT_HIT = 8
WANT_MIS = 12

# 明細書に頻出するが単語として面白くないもの
# 「装置」「手段」「部材」などの汎用語は除外しない。
# これらは低オッズ帯を埋める重要な語で、消すとオッズ分布が高い側に偏り、
# 「安いオッズは必ず当たる」状態になってしまう。
# 除くのは指示語・体裁語だけにする。
STOP = set("""
前記 上記 当該 該 これら それら もの こと ため 場合 際 とき 両者 以下 以上 未満
少なくとも いずれか および 並びに 又は 若しくは ここで なお また さらに ただし
本発明 発明 実施 形態 特徴 記載 請求項 明細書 図面
第一 第二 第三 第１ 第２ 第３ 一つ 二つ 単数
""".split())

# 1文字語はノイズになりやすいが、意味のあるものは残す
KEEP_SHORT = set("皿 傘 靴 蓋 軸 弁 管 板 棒 網 膜 液 粉 熱 光 音 風 水 油 泡 糸 鍵 錠 爪 歯 溝 孔 穴".split())

PREFIX_RE = re.compile(r"^(前記|上記|当該|該|本)")
TAIL_RE = re.compile(r"(可能|的|性|化|時|後|前|中|上|下|内|外)$")

t = Tokenizer()


def extract_words(text):
    """名詞の連続を複合語として取り出す。"""
    words, buf = [], []
    for tok in t.tokenize(text):
        ps = tok.part_of_speech.split(",")
        surface = tok.surface
        is_noun = (ps[0] == "名詞" and ps[1] not in ("数", "代名詞", "非自立", "接尾"))
        if is_noun and not re.match(r"^[0-9０-９a-zA-Z]+$", surface):
            buf.append(surface)
        else:
            # 接尾辞（〜部、〜体、〜機構）は直前の語にくっつける
            if ps[0] == "名詞" and ps[1] == "接尾" and buf:
                buf.append(surface)
                continue
            if buf:
                words.append("".join(buf))
                buf = []
    if buf:
        words.append("".join(buf))

    out = []
    for w in words:
        # 「前記コンベヤレーン」のように指示語がくっついた複合語になるので剥がす
        w = PREFIX_RE.sub("", w)
        if not w or w in STOP:
            continue
        # 「回収可能」「自動的」などは語として据わりが悪い
        if TAIL_RE.search(w):
            continue
        if len(w) == 1 and w not in KEEP_SHORT:
            continue
        if len(w) > 12:
            continue
        if re.search(r"[0-9０-９]", w):
            continue
        out.append(w)
    return out


ODDS_MIN, ODDS_MAX = 1.2, 30.0


def make_odds_fn(df):
    """DFの「順位」からオッズを決める関数を返す。

    生の 1/p を使うとコーパスが小さいときに高オッズ側へ全部寄ってしまい、
    低オッズ帯が空になる（＝オッズを見れば正解が分かる状態を作れない）。
    出現頻度の順位を 0〜1 に正規化し、指数的に 1.2〜30 倍へ写像する。
    """
    ordered = sorted(df.items(), key=lambda x: (-x[1], x[0]))
    last = max(1, len(ordered) - 1)
    rank = {}
    for i, (w, _c) in enumerate(ordered):
        rank[w] = i / float(last)      # 0=最頻出 → 1=最もレア

    def odds_of(w, in_title=False):
        r = rank.get(w, 1.0)
        o = ODDS_MIN * math.pow(ODDS_MAX / ODDS_MIN, r)
        if in_title:
            o *= 0.55                  # 名称に出ている語は予想しやすい
        return round(max(ODDS_MIN, min(ODDS_MAX, o)), 1)

    return odds_of


def band(o):
    return 0 if o < 2.5 else (1 if o <= 7 else 2)


def pick_assignee(names):
    """DC.contributor には発明者と出願人が混在するので企業らしいものを選ぶ。

    個人出願（Individual）はヒントにならないので空欄にする。
    """
    pat = re.compile(r"(株式会社|有限会社|Co Ltd|Corp|Inc|KK|Ltd|GmbH|SA|AS|University|大学|工業|製作所|電気|電機|公司)")
    for n in reversed(names):
        if pat.search(n):
            return n
    return ""


def main():
    if not os.path.exists(SRC):
        raise SystemExit("取得データがありません: " + SRC)

    recs = []
    for line in io.open(SRC, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not r.get("claims"):
            continue
        body = "\n".join(c["text"] for c in r["claims"])
        # 短すぎ・長すぎる請求項は出題に向かない
        if not (120 <= len(body) <= 1400):
            continue
        if len(r.get("title", "")) > TITLE_MAX:
            continue
        r["body"] = body
        r["wordset"] = set(extract_words(body))
        recs.append(r)
    print("読み込み {} 件（請求項の長さで絞り込み済み）".format(len(recs)))

    N = len(recs)
    df = Counter()
    for r in recs:
        df.update(r["wordset"])
    odds_of = make_odds_fn(df)

    # 罠語は「語彙が似ている特許」から取る。
    # 検索クエリのテーマ名は当てにならない（無関係な特許が検索に混ざるため、
    # 電力制御の特許に「便座」が罠として付くといった事故が起きる）。
    NEIGHBOR = 6
    neighbors = {}
    for r in recs:
        a = r["wordset"]
        sims = []
        for o in recs:
            if o is r:
                continue
            b = o["wordset"]
            inter = len(a & b)
            if not inter:
                continue
            sims.append((inter / float(len(a | b)), o))
        sims.sort(key=lambda x: -x[0])
        c = Counter()
        for _sc, o in sims[:NEIGHBOR]:
            c.update(o["wordset"])
        neighbors[r["num"]] = c

    items, skipped = [], []
    for r in recs:
        body, mine = r["body"], r["wordset"]
        th = r["theme"]
        title_words = set(extract_words(r.get("title", "")))

        # --- 正解語: この特許の請求項に出る語 ---
        hits = []
        for w in mine:
            if df[w] < 1:
                continue
            hits.append({"w": w, "odds": odds_of(w, w in title_words),
                         "tier": "real", "df": df[w]})
        # オッズ帯がばらけるように、帯ごとに拾う
        hits.sort(key=lambda x: x["odds"])

        # --- 罠語: 同テーマの他特許には出るが、この特許には出ない語 ---
        cand = []
        for w, c in neighbors[r["num"]].items():
            if w in mine:
                continue
            cand.append({"w": w, "odds": odds_of(w), "tier": "trap",
                         "df": df[w], "themedf": c})
        # 近い特許で何件にも出ている語ほど「出そうなのに無い」良い罠になる
        cand.sort(key=lambda x: (-x["themedf"], -x["df"]))
        miss = cand

        def take_balanced(pool, want):
            """低・中・高の各帯からなるべく均等に取る。"""
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

        def bands_filled(sel):
            return all(any(band(w["odds"]) == b for w in sel) for b in (0, 1, 2))

        hsel = take_balanced(hits, WANT_HIT)
        # 同テーマで2件以上に出る語のほうが「出そうなのに無い」罠として効く。
        # それで帯が埋まらないときだけ、1件しか出ない語まで広げる。
        strong = [c for c in miss if c["themedf"] >= 2]
        msel = take_balanced(strong, WANT_MIS)
        if len(msel) < WANT_MIS or not bands_filled(msel):
            msel = take_balanced(miss, WANT_MIS)

        ok_band = bands_filled(hsel) and bands_filled(msel)
        if len(hsel) < NEED_HIT or len(msel) < NEED_MIS or not ok_band:
            skipped.append((r["num"], r.get("title", ""), len(hsel), len(msel), ok_band))
            continue

        words = [{"w": w["w"], "odds": w["odds"], "tier": w["tier"]}
                 for w in (hsel + msel)]
        words.sort(key=lambda x: x["odds"])

        items.append({
            "id": r["num"],
            "source": "real",
            "num": r["num"],
            "title": r.get("title", ""),
            "assignee": pick_assignee(r.get("assignee", [])),
            "date": (r.get("date") or "")[:4],
            "ipc": "",
            "theme": th,
            "hint": "分野のヒント：" + THEME_JA.get(th, th),
            "url": r.get("url", ""),
            "claims": r["claims"],
            "words": words,
        })

    print("採用 {} 件 / 除外 {} 件".format(len(items), len(skipped)))
    for s in skipped[:8]:
        print("  除外 {} 正解{}語 罠{}語 帯バランス{} {}".format(
            s[0], s[2], s[3], "OK" if s[4] else "NG", s[1][:24]))

    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "schema_version": 2,
            "note": "Google Patents から取得した実在特許。請求項1〜2の本文と、"
                    "コーパス中の出現頻度から算出したオッズを持つ。"
                    "罠語は同テーマの他特許に出るがこの特許には出ない語。",
            "items": items,
        }, ensure_ascii=False, indent=1))
    print("出力: {}".format(OUT))


if __name__ == "__main__":
    main()
