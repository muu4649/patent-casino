# -*- coding: utf-8 -*-
"""問題データの整合性チェック。実データ投入時も同じスクリプトで検証する。"""
import json, io, sys

def band(o):
    return '低(<2.5)' if o < 2.5 else ('中(2.5-7)' if o <= 7 else '高(>7)')

def validate(path, verbose=True):
    d = json.load(io.open(path, encoding='utf-8'))
    err = 0
    for it in d['items']:
        body = '\n'.join(c['text'] for c in it['claims'])
        hits = [w for w in it['words'] if w['w'] in body]
        miss = [w for w in it['words'] if w['w'] not in body]
        if verbose:
            print('=== {} {}  全{}語 / 正解{} / 罠{}'.format(
                it['id'], it['title'], len(it['words']), len(hits), len(miss)))
        for w in it['words']:
            if (w['w'] in body) != (w['tier'] != 'trap'):
                print('   *NG* tier不整合:', w['w'], w['tier']); err += 1
        if len(hits) < 5:
            print('   *NG* 正解語が5未満'); err += 1
        if len(miss) < 5:
            print('   *NG* 罠語が5未満'); err += 1
        for b in ['低(<2.5)', '中(2.5-7)', '高(>7)']:
            h = [w['w'] for w in hits if band(w['odds']) == b]
            m = [w['w'] for w in miss if band(w['odds']) == b]
            ok = bool(h) and bool(m)
            if not ok: err += 1
            if verbose:
                print('   {} {:10s} 正解{}語 罠{}語   正解例:{}  罠例:{}'.format(
                    'OK ' if ok else '*NG*', b, len(h), len(m),
                    '/'.join(h[:3]), '/'.join(m[:3])))
    print('検証エラー:', err)
    return err

if __name__ == '__main__':
    p = sys.argv[1] if len(sys.argv) > 1 else 'data/questions_sample.json'
    sys.exit(1 if validate(p) else 0)
