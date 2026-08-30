# -*- coding: utf-8 -*-
"""ボード構成（正解語数 × 罠語数）を変えて期待収支を比較する。"""
import io, json, math, random

N = 3000
random.seed(20260830)

def band(o): return 0 if o < 2.5 else (1 if o <= 7 else 2)

def pick(pool, n):
    by = [[], [], []]
    for w in random.sample(pool, len(pool)):
        by[band(w['odds'])].append(w)
    out, quota = [], [n // 3, math.ceil(n / 3), n - n // 3 - math.ceil(n / 3)]
    for b in range(3):
        for _ in range(quota[b]):
            if by[b]: out.append(by[b].pop())
    rest = by[0] + by[1] + by[2]; random.shuffle(rest)
    while len(out) < n and rest: out.append(rest.pop())
    return out

d = json.load(io.open('data/questions_sample.json', encoding='utf-8'))

print('{:>10s} {:>10s} {:>10s} {:>10s} {:>10s}'.format(
    '正解語', '罠語', '的中率', 'ランダム', '目利き'))
for nhit, nmis in [(5,5), (4,8), (3,9), (4,6), (3,7)]:
    rs = ps = 0.0
    for it in d['items']:
        body = '\n'.join(c['text'] for c in it['claims'])
        hit = [w for w in it['words'] if w['w'] in body]
        mis = [w for w in it['words'] if w['w'] not in body]
        if len(hit) < nhit or len(mis) < nmis:
            continue
        r = p = 0.0
        for _ in range(N):
            b = [dict(w, isHit=True) for w in pick(hit, nhit)] + \
                [dict(w, isHit=False) for w in pick(mis, nmis)]
            for w in random.sample(b, 3):
                if w['isHit']: r += math.floor(w['odds'])
            for w in sorted([x for x in b if x['isHit']], key=lambda x: -x['odds'])[:3]:
                p += math.floor(w['odds'])
        rs += r / N - 3; ps += p / N - 3
    n = len(d['items'])
    print('{:10d} {:10d} {:9.0f}% {:+10.2f} {:+10.2f}'.format(
        nhit, nmis, 100.0*nhit/(nhit+nmis), rs/n, ps/n))
