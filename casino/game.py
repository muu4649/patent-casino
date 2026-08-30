# -*- coding: utf-8 -*-
"""特許カジノのゲームロジック。

src/template.html の JS 実装と同じ仕様。数値を変えるときは両方を揃えること。
"""
import math
import random

MAX_WORDS = 3      # 1ラウンドに賭けられるワード数
BOARD_HIT = 4      # ボードに出す正解語の数
BOARD_MIS = 8      # ボードに出す罠語の数（的中率33%。50%だと倍率に対して当たりすぎる）
BAILOUT = 3        # 破産時の救済チップ
BET_RATIO = 0.5    # 1ラウンドに賭けられるのは所持チップのこの割合まで
BET_FLOOR = 3      # ただし最低この枚数までは賭けられる

PCOLOR = ["#e4b429", "#4aa3df", "#e06c4f", "#7fc47f"]


def bet_limit(chips):
    """このラウンドに賭けられる上限枚数。"""
    return max(BET_FLOOR, int(chips * BET_RATIO))


def claim_body(item):
    """請求項1〜2を結合した本文。正解判定はこの文字列へのマッチで行う。"""
    return "\n".join(c["text"] for c in item["claims"])


def band(odds):
    """オッズ帯。0=低(<2.5) 1=中(2.5-7) 2=高(>7)"""
    return 0 if odds < 2.5 else (1 if odds <= 7 else 2)


def split_words(item):
    """語を「請求項に出る/出ない」で分ける。"""
    body = claim_body(item)
    hit = [w for w in item["words"] if w["w"] in body]
    mis = [w for w in item["words"] if w["w"] not in body]
    return hit, mis


def _pick(pool, n, rng):
    """オッズ帯のバランスを取りながら n 語を抜く。"""
    by = [[], [], []]
    for w in rng.sample(pool, len(pool)):
        by[band(w["odds"])].append(w)
    out = []
    quota = [n // 3, int(math.ceil(n / 3.0)), n - n // 3 - int(math.ceil(n / 3.0))]
    for b in range(3):
        for _ in range(quota[b]):
            if by[b]:
                out.append(by[b].pop())
    rest = by[0] + by[1] + by[2]
    rng.shuffle(rest)
    while len(out) < n and rest:
        out.append(rest.pop())
    return out


def make_board(item, rng=None):
    """正解4語・罠8語を抽出してシャッフルしたボードを返す。"""
    rng = rng or random
    hit, mis = split_words(item)
    board = ([dict(w, isHit=True) for w in _pick(hit, BOARD_HIT, rng)] +
             [dict(w, isHit=False) for w in _pick(mis, BOARD_MIS, rng)])
    rng.shuffle(board)
    return board


def can_bet(board, bets, chips, index, delta):
    """BET を delta 枚動かせるか判定し、(可否, 新しい枚数, 警告文) を返す。"""
    w = board[index]["w"]
    cur = bets.get(w, 0)
    total = sum(bets.values())
    nxt = max(0, cur + delta)

    if cur == 0 and nxt > 0:
        used = len([k for k, v in bets.items() if v > 0])
        if used >= MAX_WORDS:
            return False, cur, "賭けられるのは{}ワードまでです".format(MAX_WORDS)

    lim = min(chips, bet_limit(chips))
    if total - cur + nxt > lim:
        nxt = lim - (total - cur)
        if nxt <= cur:
            return False, cur, "このラウンドは合計 {} 枚までです（所持 {} 枚）".format(lim, chips)
    return True, nxt, ""


def settle(board, bets):
    """1人分の精算。(投入, 払戻, 明細) を返す。明細は (語, 枚数, 的中, 払戻)。"""
    stake = payout = 0
    detail = []
    by_word = {w["w"]: w for w in board}
    for word, amount in bets.items():
        if amount <= 0:
            continue
        w = by_word.get(word)
        if w is None:
            continue
        stake += amount
        pay = int(math.floor(amount * w["odds"])) if w["isHit"] else 0
        payout += pay
        detail.append((word, amount, w["isHit"], pay))
    detail.sort(key=lambda d: -d[1])
    return stake, payout, detail


def highlight_spans(text, words):
    """text 中の words の出現位置を返す。長い語を優先し重複させない。"""
    spans = []
    for w in sorted(words, key=lambda x: -len(x)):
        start = 0
        while True:
            i = text.find(w, start)
            if i < 0:
                break
            s, e = i, i + len(w)
            if not any(s < m[1] and e > m[0] for m in spans):
                spans.append((s, e, w))
            start = i + 1
    spans.sort(key=lambda m: m[0])
    return spans
