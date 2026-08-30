# -*- coding: utf-8 -*-
"""特許カジノ — Streamlit版

    streamlit run app.py

ゲームの仕様は casino/game.py に集約してある（index.html のJS実装と同一）。
問題データは data/*.json を読み込む。サイドバーからJSONを差し替えることもできる。
"""
import glob
import io
import json
import os
import random

import streamlit as st

from casino import game as G

def rerun():
    """st.rerun / st.experimental_rerun のどちらでも動くようにする。

    ローカルの 1.23 は experimental_rerun のみ、Streamlit Cloud の新しい版は
    rerun のみ（experimental_rerun は削除済み）。
    """
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        getattr(st, "experimental_rerun")()


HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")

st.set_page_config(page_title="特許カジノ", page_icon="🎰", layout="wide")

CSS = """
<style>
.stApp { background: radial-gradient(ellipse at 50% 0%, #14513e 0%, #0d3b2e 45%, #0a2f24 100%); }
h1, h2, h3, h4, p, label, span, div[data-testid="stMarkdownContainer"] { color: #f4efe2; }
.pc-title { font-size: 30px; letter-spacing:.14em; text-align:center; color:#d4af37;
  text-shadow:0 2px 0 #5b4a17, 0 0 22px rgba(212,175,55,.35); margin:4px 0 0; font-weight:700; }
.pc-sub { text-align:center; color:#9fb8ae; font-size:11px; letter-spacing:.24em; margin-bottom:16px; }
.pc-card { background:linear-gradient(180deg,rgba(255,255,255,.05),rgba(0,0,0,.18));
  border:1px solid rgba(212,175,55,.34); border-radius:12px; padding:16px 20px; margin-bottom:14px; }
.pc-qtitle { font-family:"Hiragino Mincho ProN",serif; font-size:30px; font-weight:600;
  text-align:center; margin:6px 0 10px; letter-spacing:.05em; }
.pc-meta { text-align:center; margin-bottom:6px; }
.pc-meta span { font-size:11px; padding:4px 11px; border-radius:999px; margin:0 3px;
  border:1px solid rgba(212,175,55,.34); background:rgba(0,0,0,.26); color:#cfe0d8; }
.pc-hint { text-align:center; font-size:12.5px; color:#a9c2b8; font-style:italic; }
.pc-fic { font-size:10.5px; letter-spacing:.1em; padding:3px 9px; border-radius:4px;
  background:rgba(179,32,46,.28); border:1px solid rgba(179,32,46,.6); color:#ffc9c9; }
.pc-claim { font-family:"Hiragino Mincho ProN","Yu Mincho",serif; background:#f6f3e9; color:#1a1a1a;
  border-radius:8px; padding:14px 18px; margin-bottom:10px; line-height:2.0; font-size:14.5px;
  white-space:pre-wrap; border-left:4px solid #8a7328; }
.pc-claim .cn { display:inline-block; font-family:system-ui,sans-serif; font-size:11px; font-weight:700;
  letter-spacing:.16em; color:#6b5a1e; background:#e8dfc0; padding:3px 10px; border-radius:4px; margin-bottom:8px; }
.pc-claim mark { background:#ffe066; color:#000; padding:1px 2px; border-radius:3px; font-weight:700;
  box-shadow:0 0 0 1px #d4af37; }
.pc-claim mark.bet { background:#1f8a4c; color:#fff; box-shadow:0 0 0 2px #0d3b2e; }
.pc-odds { color:#d4af37; font-weight:700; font-size:12px; letter-spacing:.06em; }
.pc-hit { border:1px solid #1f8a4c; background:linear-gradient(180deg,rgba(31,138,76,.26),rgba(31,138,76,.09));
  border-radius:9px; padding:9px 11px; margin-bottom:8px; }
.pc-mis { border:1px solid rgba(179,32,46,.6); background:linear-gradient(180deg,rgba(179,32,46,.18),rgba(0,0,0,.32));
  border-radius:9px; padding:9px 11px; margin-bottom:8px; opacity:.75; }
.pc-w { font-size:16px; font-weight:700; }
.pc-turn { text-align:center; padding:20px 0; }
.pc-turn .nm { font-size:28px; font-weight:800; }
.pc-rank { display:flex; align-items:center; gap:14px; padding:12px 16px; border-radius:10px;
  background:rgba(0,0,0,.28); border:1px solid rgba(255,255,255,.11); margin-bottom:8px; }
.pc-rank.win { border-color:#d4af37; background:linear-gradient(90deg,rgba(212,175,55,.2),rgba(0,0,0,.28)); }
.pc-rank .rk { font-size:22px; font-weight:800; color:#d4af37; min-width:40px; font-family:serif; }
.pc-rank .nm { font-size:17px; font-weight:700; flex:1; }
.pc-rank .ch { font-size:22px; font-weight:800; color:#d4af37; }
div.stButton > button { background:linear-gradient(180deg,#1b6b50,#124a37); color:#f4efe2;
  border:1px solid rgba(212,175,55,.5); border-radius:8px; font-weight:600; }
div.stButton > button:hover { background:linear-gradient(180deg,#238263,#16583f); color:#fff;
  border-color:#d4af37; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------- データ読み込み
@st.cache_data(show_spinner=False)
def load_bundled():
    items, seen = [], set()
    for p in sorted(glob.glob(os.path.join(DATA_DIR, "*.json"))):
        with io.open(p, encoding="utf-8") as f:
            d = json.load(f)
        for it in d.get("items", []):
            if it["id"] not in seen:
                seen.add(it["id"])
                items.append(it)
    return items


def show_table(rows):
    """hide_index は 1.28+ の引数なので、古い版では黙って落とす。"""
    try:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    except TypeError:
        st.dataframe(rows, use_container_width=True)


def usable(items):
    """ボード生成に足りる設問だけを残す。"""
    ok, ng = [], []
    for it in items:
        hit, mis = G.split_words(it)
        (ok if len(hit) >= G.BOARD_HIT and len(mis) >= G.BOARD_MIS else ng).append(
            (it, len(hit), len(mis)))
    return [x[0] for x in ok], ng


S = st.session_state
if "phase" not in S:
    S.phase = "setup"
    S.questions = load_bundled()
    S.data_label = "同梱データ"


# ---------------------------------------------------------------- サイドバー
with st.sidebar:
    st.markdown("### 問題データ")
    ok_items, ng_items = usable(S.questions)
    st.caption("{}：{} 問（うち使用可 {} 問）".format(S.data_label, len(S.questions), len(ok_items)))
    for it, nh, nm in ng_items:
        st.warning("{} は正解{}語/罠{}語で不足（要 正解{}・罠{}）".format(
            it["id"], nh, nm, G.BOARD_HIT, G.BOARD_MIS), icon="⚠️")

    st.info("問題データは **JSON形式のみ** 対応しています。"
            "PDF・CSV・Excel からの取り込みには対応していないため、"
            "下記スキーマのJSONに整形してから読み込んでください。", icon="📋")
    with st.expander("JSONスキーマを見る"):
        st.caption("`words` に正解フラグは持たせません。各語が請求項本文に含まれるかを"
                   "実行時に文字列マッチで判定するため、実データを入れればそのまま答え合わせが効きます。")
        st.code(json.dumps({
            "schema_version": 2,
            "items": [{
                "id": "JP6935980B2", "source": "real", "num": "JP6935980B2",
                "title": "発明の名称", "assignee": "出願人", "date": "2019",
                "ipc": "B62D 25/08", "theme": "自動車",
                "hint": "画面に出るヒント（任意）",
                "claims": [{"num": "1", "text": "請求項1の全文"},
                           {"num": "2", "text": "請求項2の全文"}],
                "words": [{"w": "搬送", "odds": 1.4, "tier": "title"},
                          {"w": "レーン", "odds": 2.8, "tier": "trap"}],
            }],
        }, ensure_ascii=False, indent=2), language="json")
        st.caption("**必須要件**：請求項本文に含まれる語が {} 語以上、含まれない語が {} 語以上。"
                   "さらに各オッズ帯（低<2.5／中2.5-7／高>7）に正解語と罠語の両方を置くこと"
                   "（片方に寄るとオッズを見ただけで正解が割れます）。".format(
                       G.BOARD_HIT, G.BOARD_MIS))

    up = st.file_uploader("JSONを読み込む", type=["json"])
    if up is not None and st.button("このデータに差し替える"):
        try:
            d = json.loads(up.getvalue().decode("utf-8"))
            if not d.get("items"):
                raise ValueError("items がありません")
            S.questions = d["items"]
            S.data_label = up.name
            S.phase = "setup"
            rerun()
        except Exception as e:
            st.error("読み込み失敗: {}".format(e))

    if S.data_label != "同梱データ" and st.button("同梱データに戻す"):
        S.questions = load_bundled()
        S.data_label = "同梱データ"
        S.phase = "setup"
        rerun()

    st.markdown("---")
    st.markdown("### ルール")
    st.markdown(
        "- ボード12語のうち**請求項に出るのは4語**、残り8語は罠\n"
        "- 賭けは**3ワードまで**、合計は**所持チップの半分**まで\n"
        "- 的中で **枚数 × オッズ**（切り捨て）、外れは没収\n"
        "- 0枚になったら次ラウンド開始時に{}枚支給\n"
        "- 罠にも正解と同じ帯のオッズが振ってある".format(G.BAILOUT))


st.markdown('<div class="pc-title">特 許 カ ジ ノ</div>', unsafe_allow_html=True)
st.markdown('<div class="pc-sub">CLAIM BETTING GAME</div>', unsafe_allow_html=True)


def question_header(it, ri, rounds):
    """出題カード。Streamlitは st.markdown ごとに div でラップするため、
    囲みたい要素は1回の呼び出しにまとめないと枠が正しく閉じない。"""
    fic = ('<span class="pc-fic">架空・動作確認用</span>'
           if it.get("source") == "fictional" else "")
    meta = "".join("<span>{}</span>".format(t) for t in [
        "出願人：" + it["assignee"] if it.get("assignee") else "",
        "出願年：" + str(it["date"]) if it.get("date") else "",
        "IPC：" + it["ipc"] if it.get("ipc") else "",
        it["num"] if it.get("num") and it["num"] != "架空" else "",
    ] if t)
    hint = ('<div class="pc-hint">{}</div>'.format(it["hint"])
            if it.get("hint") else "")
    st.markdown(
        '<div class="pc-card">'
        '<div style="text-align:center;font-size:11px;letter-spacing:.3em;color:#8a7328">'
        'ROUND {} / {}</div>'
        '<div class="pc-qtitle">{} {}</div>'
        '<div class="pc-meta">{}</div>'
        '{}</div>'.format(ri + 1, rounds, it["title"], fic, meta, hint),
        unsafe_allow_html=True)


def chip_bar(players, now=None):
    cols = st.columns(len(players))
    for i, (c, p) in enumerate(zip(cols, players)):
        mark = "▶ " if now == i else ""
        c.markdown(
            '<div style="text-align:center;padding:7px;border-radius:999px;'
            'background:rgba(0,0,0,.3);border:1px solid {};">'
            '<span style="color:{}">● </span>{}{} '
            '<b style="color:#d4af37">{}</b></div>'.format(
                "#d4af37" if now == i else "rgba(255,255,255,.14)",
                p["color"], mark, p["name"], p["chips"]),
            unsafe_allow_html=True)


# ---------------------------------------------------------------- setup
if S.phase == "setup":
    ok_items, _ = usable(S.questions)
    if not ok_items:
        st.error("使用できる設問がありません。サイドバーからJSONを読み込んでください。")
        st.stop()

    c1, c2, c3 = st.columns(3)
    n = c1.selectbox("人数", [2, 3, 4], index=0)
    chips = c2.selectbox("初期チップ", [20, 30, 50], index=0)
    rounds = c3.selectbox("ラウンド数", list(range(1, len(ok_items) + 1)),
                          index=min(2, len(ok_items) - 1))
    names = []
    ncols = st.columns(n)
    for i in range(n):
        names.append(ncols[i].text_input("プレイヤー{}".format(i + 1),
                                         value="", key="nm{}".format(i),
                                         placeholder="プレイヤー{}".format(i + 1)))

    if st.button("ゲーム開始", type="primary"):
        names = [nm.strip() or "プレイヤー{}".format(i + 1) for i, nm in enumerate(names)]
        if len(set(names)) != len(names):
            st.error("名前が重複しています")
        else:
            S.players = [{"name": nm, "chips": chips, "color": G.PCOLOR[i], "hist": []}
                         for i, nm in enumerate(names)]
            S.start_chips = chips
            S.rounds = rounds
            S.order = random.sample(ok_items, len(ok_items))
            S.ri = 0
            S.turn = 0
            S.bets = [{} for _ in names]
            S.board = G.make_board(S.order[0])
            S.phase = "bet"
            rerun()


# ---------------------------------------------------------------- 交代画面
elif S.phase == "pass":
    it = S.order[S.ri]
    question_header(it, S.ri, S.rounds)
    p = S.players[S.turn]
    st.markdown('<div class="pc-card"><div class="pc-turn">'
                '<div class="nm" style="color:{}">{}</div>'
                '<div style="color:#9fb8ae;font-size:13px">の番です。前の人の賭けは見えません。</div>'
                '</div></div>'.format(p["color"], p["name"]), unsafe_allow_html=True)
    if st.button("準備OK", type="primary"):
        S.phase = "bet"
        rerun()


# ---------------------------------------------------------------- BET
elif S.phase == "bet":
    it = S.order[S.ri]
    chip_bar(S.players, now=S.turn)
    question_header(it, S.ri, S.rounds)

    p = S.players[S.turn]
    lim = min(p["chips"], G.bet_limit(p["chips"]))
    st.markdown("#### <span style='color:{}'>{}</span> の BET".format(p["color"], p["name"]),
                unsafe_allow_html=True)
    st.caption("所持 {} 枚 ／ 最大 {} ワード ／ このラウンドは合計 {} 枚まで".format(
        p["chips"], G.MAX_WORDS, lim))

    # ボードは眺めるための表示。賭ける操作は下の選択とスライダーで行う
    # （number_input は Enter を押すまで確定せず、パーティ用途に向かない）
    cols = st.columns(4)
    for i, w in enumerate(S.board):
        cols[i % 4].markdown(
            '<div class="pc-card" style="padding:9px 12px 7px;margin-bottom:6px">'
            '<div class="pc-w">{}</div>'
            '<div class="pc-odds">{:.1f} 倍</div></div>'.format(w["w"], w["odds"]),
            unsafe_allow_html=True)

    label_of = {"{}（{:.1f}倍）".format(w["w"], w["odds"]): w["w"] for w in S.board}
    picked = st.multiselect(
        "賭けるワードを選ぶ（最大{}ワード）".format(G.MAX_WORDS),
        list(label_of.keys()), key="pick_{}_{}".format(S.ri, S.turn),
        max_selections=G.MAX_WORDS)

    amounts = {}
    if picked:
        scols = st.columns(len(picked))
        for c, label in zip(scols, picked):
            word = label_of[label]
            with c:
                amounts[word] = st.slider(
                    label, min_value=1, max_value=int(lim), value=1, step=1,
                    key="amt_{}_{}_{}".format(S.ri, S.turn, word))

    used = {k: v for k, v in amounts.items() if v > 0}
    total = sum(used.values())
    st.markdown("**{} ワード / 合計 {} 枚**（残り {} 枚）".format(
        len(used), total, max(0, lim - total)))

    err = None
    if len(used) == 0:
        err = "1ワード以上に賭けてください"
    elif len(used) > G.MAX_WORDS:
        err = "賭けられるのは{}ワードまでです（いま{}ワード）".format(G.MAX_WORDS, len(used))
    elif total > lim:
        err = "このラウンドは合計 {} 枚までです（いま{}枚）".format(lim, total)
    if err:
        st.warning(err)

    if st.button("この内容で確定", type="primary", disabled=bool(err)):
        S.bets[S.turn] = used
        S.turn += 1
        S.phase = "reveal" if S.turn >= len(S.players) else "pass"
        rerun()


# ---------------------------------------------------------------- 開票待ち
elif S.phase == "reveal":
    it = S.order[S.ri]
    question_header(it, S.ri, S.rounds)
    st.markdown('<div class="pc-card"><div class="pc-turn">'
                '<div class="nm">全員のBETが完了</div>'
                '<div style="color:#9fb8ae;font-size:13px">請求項1〜2を開示します</div>'
                '</div></div>', unsafe_allow_html=True)
    if st.button("開　票", type="primary"):
        # 精算してチップを更新する
        S.settle = []
        for i, p in enumerate(S.players):
            stake, payout, detail = G.settle(S.board, S.bets[i])
            p["chips"] = p["chips"] - stake + payout
            p["hist"].append(p["chips"])
            S.settle.append((stake, payout, detail))
        S.phase = "result"
        rerun()


# ---------------------------------------------------------------- 開票結果
elif S.phase == "result":
    it = S.order[S.ri]
    chip_bar(S.players)

    board_hits = [w["w"] for w in S.board if w["isHit"]]
    bet_hits = set()
    for w in S.board:
        if w["isHit"] and any(b.get(w["w"], 0) > 0 for b in S.bets):
            bet_hits.add(w["w"])

    st.markdown("#### 請求項")
    st.caption("黄色 = ボードにあった正解語 ／ 緑 = 誰かが賭けて的中した語")
    for c in it["claims"]:
        text = c["text"]
        out, pos = "", 0
        for s, e, w in G.highlight_spans(text, board_hits):
            out += text[pos:s]
            cls = " class='bet'" if w in bet_hits else ""
            out += "<mark{}>{}</mark>".format(cls, text[s:e])
            pos = e
        out += text[pos:]
        st.markdown('<div class="pc-claim"><span class="cn">請求項 {}</span>\n{}</div>'.format(
            c["num"], out), unsafe_allow_html=True)
    if it.get("source") == "fictional":
        st.caption("※ この設問は動作確認用の架空明細書です。実在特許ではありません。")
    elif it.get("url"):
        st.caption("出典：{}　{}".format(it.get("num", ""), it["url"]))

    st.markdown("#### ボード結果")
    cols = st.columns(4)
    for i, w in enumerate(S.board):
        bettors = [(S.players[j], S.bets[j][w["w"]])
                   for j in range(len(S.players)) if S.bets[j].get(w["w"], 0) > 0]
        who = " / ".join("<span style='color:{}'>{} {}枚</span>".format(
            p["color"], p["name"], a) for p, a in bettors)
        cols[i % 4].markdown(
            '<div class="{}"><div class="pc-w">{} <span style="font-size:10px">{}</span></div>'
            '<div class="pc-odds">{:.1f} 倍</div>'
            '<div style="font-size:11px;color:#cfe0d8;min-height:15px">{}</div></div>'.format(
                "pc-hit" if w["isHit"] else "pc-mis", w["w"],
                "出た" if w["isHit"] else "出ない", w["odds"], who or "&nbsp;"),
            unsafe_allow_html=True)

    st.markdown("#### 精算")
    rows = []
    for i, p in enumerate(S.players):
        stake, payout, detail = S.settle[i]
        rows.append({
            "プレイヤー": p["name"],
            "賭け": " / ".join("{} {}枚{}".format(w, a, "→{}".format(pay) if hit else "×")
                             for w, a, hit, pay in detail) or "—",
            "投入": stake, "払戻": payout, "増減": payout - stake, "残高": p["chips"],
        })
    show_table(rows)

    last = (S.ri + 1 >= S.rounds)
    if not last:
        st.caption("残り {} ラウンド".format(S.rounds - S.ri - 1))
    if st.button("最終結果を見る" if last else "次のラウンドへ", type="primary"):
        if last:
            S.phase = "final"
        else:
            S.ri += 1
            S.turn = 0
            S.bets = [{} for _ in S.players]
            for p in S.players:          # 破産救済
                if p["chips"] <= 0:
                    p["chips"] = G.BAILOUT
            S.board = G.make_board(S.order[S.ri])
            S.phase = "bet"
        rerun()


# ---------------------------------------------------------------- 最終結果
elif S.phase == "final":
    st.markdown("#### 最終結果")
    rank = sorted(S.players, key=lambda p: -p["chips"])
    prev = None
    for k, p in enumerate(rank):
        pos = "=" if prev == p["chips"] else str(k + 1)
        prev = p["chips"]
        st.markdown('<div class="pc-rank{}"><div class="rk">{}</div>'
                    '<div class="nm" style="color:{}">{}</div>'
                    '<div class="ch">{} <span style="font-size:12px;color:#9fb8ae">枚</span></div>'
                    '</div>'.format(" win" if k == 0 else "", pos, p["color"], p["name"], p["chips"]),
                    unsafe_allow_html=True)

    st.markdown("#### チップ推移")
    hist = [dict([("プレイヤー", p["name"])] +
                 [("R{}".format(i + 1), v) for i, v in enumerate(p["hist"])])
            for p in S.players]
    show_table(hist)

    c1, c2 = st.columns(2)
    if c1.button("もう一度あそぶ", type="primary"):
        ok_items, _ = usable(S.questions)
        for p in S.players:
            p["chips"] = S.start_chips
            p["hist"] = []
        S.order = random.sample(ok_items, len(ok_items))
        S.ri = 0
        S.turn = 0
        S.bets = [{} for _ in S.players]
        S.board = G.make_board(S.order[0])
        S.phase = "bet"
        rerun()
    if c2.button("設定に戻る"):
        S.phase = "setup"
        rerun()
