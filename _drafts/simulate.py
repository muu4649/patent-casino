# -*- coding: utf-8 -*-
"""ボード生成とBETをシミュレートし、オッズ勾配が妥当かを見る。

template.html の makeBoard / 精算ロジックと同じ手続きをPythonで再現する。
"""
import io, json, math, random, sys

N = 4000
random.seed(20260830)

def band(o):
    return 0 if o < 2.5 else (1 if o <= 7 else 2)

def pick(pool, n):
    by = [[], [], []]
    for w in random.sample(pool, len(pool)):
        by[band(w['odds'])].append(w)
    out = []
    quota = [n // 3, math.ceil(n / 3), n - n // 3 - math.ceil(n / 3)]
    for b in range(3):
        for _ in range(quota[b]):
            if by[b]:
                out.append(by[b].pop())
    rest = by[0] + by[1] + by[2]
    random.shuffle(rest)
    while len(out) < n and rest:
        out.append(rest.pop())
    return out

def make_board(it):
    body = '\n'.join(c['text'] for c in it['claims'])
    hit = [w for w in it['words'] if w['w'] in body]
    mis = [w for w in it['words'] if w['w'] not in body]
    board = pick(hit, 5) + pick(mis, 5)
    for w in board:
        w = dict(w)
    return [dict(w, isHit=(w['w'] in body)) for w in board]

d = json.load(io.open('data/questions_sample.json', encoding='utf-8'))
STAKE = 1   # 1ワードあたり1枚 × 3ワード

print('{:24s} {:>8s} {:>8s} {:>9s} {:>9s}'.format('設問', '正解語odds', '罠odds', 'ランダム', '目利き'))
tot_rand = tot_pro = 0.0
for it in d['items']:
    body = '\n'.join(c['text'] for c in it['claims'])
    hit_all = [w for w in it['words'] if w['w'] in body]
    mis_all = [w for w in it['words'] if w['w'] not in body]
    rand_ret = pro_ret = 0.0
    for _ in range(N):
        b = make_board(it)
        # ランダム: 10語から3語を無作為に
        for w in random.sample(b, 3):
            if w['isHit']:
                rand_ret += math.floor(STAKE * w['odds'])
        # 目利き: 正解語を見抜き、その中で最もオッズが高い3語
        hits = sorted([w for w in b if w['isHit']], key=lambda x: -x['odds'])[:3]
        for w in hits:
            pro_ret += math.floor(STAKE * w['odds'])
    rand = rand_ret / N - 3 * STAKE
    pro  = pro_ret / N - 3 * STAKE
    tot_rand += rand; tot_pro += pro
    print('{:24s} {:8.1f} {:8.1f} {:+9.2f} {:+9.2f}'.format(
        it['title'][:22],
        sum(w['odds'] for w in hit_all) / len(hit_all),
        sum(w['odds'] for w in mis_all) / len(mis_all),
        rand, pro))
print('-' * 62)
print('{:24s} {:8s} {:8s} {:+9.2f} {:+9.2f}'.format('平均（3枚投入あたり収支）', '', '', tot_rand/len(d['items']), tot_pro/len(d['items'])))
