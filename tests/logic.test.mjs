#!/usr/bin/env node
/**
 * ゲームロジックの回帰テスト（外部ライブラリなし）
 *
 *   node tests/logic.test.mjs
 *
 * src/template.html の「GAME LOGIC」区間を切り出して実行し、次を確かめる。
 *   1. 旧実装（UI刷新前のコミット）と、同じ乱数で同じ結果になること（差分テスト）
 *      盤面生成・出題順・BET上限・賭けの操作規則・精算
 *   2. 規則そのもの（盤面は正解4・罠8、賭けは3語・上限内、破産救済、同点の順位）
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const BASE_COMMIT = process.env.BASE_COMMIT || '4d324bc';   // UI刷新前の最後のコミット

let pass = 0, fail = 0;
const ok = (cond, msg) => { if (cond) pass++; else { fail++; console.log('  NG ' + msg); } };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/* 決定的な乱数（両方の実装に同じものを入れる） */
const SEEDER = `function __seed(s){ s = s >>> 0; Math.random = function(){
  s = (s + 0x6D2B79F5) | 0; let t = Math.imul(s ^ (s >>> 15), 1 | s);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }`;

/* ---------- 問題データ ---------- */
const items = [];
for (const f of fs.readdirSync(path.join(ROOT, 'data')).sort()) {
  if (!f.endsWith('.json') || f.startsWith('_')) continue;
  items.push(...JSON.parse(fs.readFileSync(path.join(ROOT, 'data', f), 'utf8')).items);
}

/* ---------- 新実装 ---------- */
const tpl = fs.readFileSync(path.join(ROOT, 'src', 'template.html'), 'utf8');
const m = tpl.match(/\/\* ==== GAME LOGIC START ====[\s\S]*?\*\/([\s\S]*?)\/\* ==== GAME LOGIC END ==== \*\//);
if (!m) { console.error('GAME LOGIC 区間が見つかりません'); process.exit(2); }
const NEW = vm.createContext({});
vm.runInContext(SEEDER + m[1], NEW);
const N = vm.runInContext(`({MAX_WORDS, BOARD_HIT, BOARD_MIS, BAILOUT, betLimit, roundLimit, betUsed, splitWords, isUsable,
  orderQuestions, makeBoard, toggleBet, setBetAmount, applyBailout, settleRound, rankPlayers, seed: __seed})`, NEW);

/* ---------- 旧実装（git から当時のコードをそのまま取り出す） ---------- */
let O = null;
try {
  const old = execFileSync('git', ['show', `${BASE_COMMIT}:src/template.html`], { cwd: ROOT, encoding: 'utf8' });
  const cut = (a, b) => { const i = old.indexOf(a), j = old.indexOf(b, i); if (i < 0 || j < 0) throw new Error(a); return old.slice(i, j); };
  const code = [
    cut('const MAX_WORDS', '/* クラッカー'),                       // 定数・小道具・出題順・盤面
    cut('function toggleWord', 'function updateBetUI'),            // 語の選択
    cut('function setAmount', 'function warn'),                    // 枚数指定
    cut('function settle()', '/* ===================== 開票'),     // 精算
  ].join('\n');
  const OLD = vm.createContext({
    DATA: { items: [] }, document: {},
    localStorage: { _v: '[]', getItem(){ return this._v; }, setItem(k, v){ this._v = v; } },
  });
  vm.runInContext(SEEDER + code + `
    let __warn = '';
    function warn(m){ __warn = m; }
    function renderBoard(){} function updateBetUI(){}`, OLD);
  O = OLD;
} catch (e) {
  console.log(`旧実装（${BASE_COMMIT}）を取り出せないため差分テストを省略: ${e.message}`);
}
const oldEval = expr => vm.runInContext(expr, O);

/* =====================================================================
   1. 差分テスト
   ===================================================================== */
if (O) {
  console.log(`差分テスト（旧実装 ${BASE_COMMIT} と比較）`);

  // 盤面生成：全問 × 20 シード
  let boards = 0;
  for (const it of items) {
    for (let s = 1; s <= 20; s++) {
      N.seed(s); const a = N.makeBoard(it);
      O.__item = it; oldEval(`__seed(${s})`); const b = oldEval('makeBoard(__item)');
      ok(same(a, b), `盤面が一致しない: ${it.id} seed=${s}`);
      boards++;
    }
  }
  console.log(`  盤面生成 ${boards} 通り`);

  // 出題順：直近の出題を後回しにする規則
  const pool = items.filter(N.isUsable);
  for (let s = 1; s <= 60; s++) {
    const recent = pool.slice(s % 7, s % 7 + (s % 5)).map(q => q.id);
    N.seed(s); const a = N.orderQuestions(pool, recent).map(q => q.id);
    O.localStorage._v = JSON.stringify(recent); O.__pool = pool;
    oldEval(`__seed(${s})`); const b = oldEval('orderQuestions(__pool)').map(q => q.id);
    ok(same(a, b), `出題順が一致しない: seed=${s}`);
  }
  console.log('  出題順 60 通り');

  // BET上限
  for (let c = -5; c <= 400; c++) ok(N.betLimit(c) === oldEval(`betLimit(${c})`), `betLimit(${c})`);
  console.log('  BET上限 406 通り');

  // 賭けの操作：ランダムな操作列で、賭けの中身・選択中の語・拒否の有無が一致するか
  let ops = 0;
  for (let s = 1; s <= 300; s++) {
    const it = pool[s % pool.length];
    N.seed(s); const board = N.makeBoard(it);
    const chips = [1, 2, 3, 4, 5, 7, 10, 20, 30, 50, 120][s % 11];
    let r = s * 7919;
    const rnd = n => { r = (r * 1103515245 + 12345) % 2147483648; return r % n; };
    const nb = {}; let nActive = null;
    O.__S = { board, bets: [{}], turn: 0, players: [{ chips }], active: null }; oldEval('S = __S');  // 旧コードの S は let 宣言なので式の中で入れる
    for (let k = 0; k < 40; k++) {
      if (rnd(3) === 0) {
        const v = [1, 3, 5, 'max'][rnd(4)];
        if (nActive) N.setBetAmount(nb, nActive, v, chips);
        O.__v = v; oldEval('setAmount(__v)');
      } else {
        const i = rnd(12);
        const res = N.toggleBet(nb, board[i].w, chips, nActive);
        nActive = res.active;
        oldEval(`__warn = ''; toggleWord(${i})`);
        ok(res.ok === (oldEval('__warn') === ''), `語の選択の可否が一致しない: seed=${s} op=${k}`);
      }
      ok(same(nb, oldEval('S.bets[0]')), `賭けの中身が一致しない: seed=${s} op=${k}`);
      ok(nActive === oldEval('S.active'), `選択中の語が一致しない: seed=${s} op=${k}`);
      ops++;
    }
  }
  console.log(`  賭けの操作 ${ops} 手`);

  // 精算
  for (let s = 1; s <= 300; s++) {
    const it = pool[(s * 3) % pool.length];
    N.seed(s); const board = N.makeBoard(it);
    const np = 2 + (s % 3);
    const mk = () => Array.from({ length: np }, (_, i) => ({ name: 'P' + i, chips: 3 + ((s * (i + 3)) % 60), hist: [5] }));
    const bets = Array.from({ length: np }, (_, i) => {
      const b = {}; const pick = [(s + i) % 12, (s * 5 + i) % 12, (s * 7 + 2 * i) % 12];
      pick.forEach((j, k) => { if (k <= (s + i) % 3) b[board[j].w] = 1 + ((s + j) % 6); });
      return b;
    });
    const pa = mk(), pb = mk();
    const ra = N.settleRound(pa, board, bets);
    O.__S = { players: pb, board, bets }; oldEval('S = __S');
    oldEval('settle()');
    ok(same(ra, oldEval('S.settle')) && same(pa, pb), `精算が一致しない: seed=${s}`);
  }
  console.log('  精算 300 通り');
}

/* =====================================================================
   2. 規則
   ===================================================================== */
console.log('規則のテスト');
const pool = items.filter(N.isUsable);
for (const it of pool) {
  for (let s = 1; s <= 5; s++) {
    N.seed(s * 31);
    const b = N.makeBoard(it);
    const words = b.map(w => w.w);
    ok(b.length === 12, `${it.id}: 盤面が12語でない`);
    ok(b.filter(w => w.isHit).length === N.BOARD_HIT && b.filter(w => !w.isHit).length === N.BOARD_MIS, `${it.id}: 正解4・罠8 でない`);
    ok(new Set(words).size === 12, `${it.id}: 盤面に重複語がある`);
    const body = it.claims.map(c => c.text).join('\n');
    ok(b.every(w => w.isHit === body.includes(w.w)), `${it.id}: 正解判定が請求項本文と食い違う`);
  }
}
console.log(`  盤面 ${pool.length} 問 × 5`);

// 賭けは常に 3 語・上限以内
for (let s = 1; s <= 500; s++) {
  N.seed(s); const board = N.makeBoard(pool[s % pool.length]);
  const chips = (s % 60) + 1, bets = {};
  let active = null, r = s;
  for (let k = 0; k < 30; k++) {
    r = (r * 48271) % 2147483647;
    if (r % 3 === 0 && active) N.setBetAmount(bets, active, [1, 3, 5, 'max'][r % 4], chips);
    else active = N.toggleBet(bets, board[r % 12].w, chips, active).active;
    ok(Object.keys(bets).length <= N.MAX_WORDS, `語数が上限を超えた: seed=${s}`);
    ok(N.betUsed(bets) <= N.roundLimit(chips), `枚数が上限を超えた: seed=${s}`);
    ok(Object.values(bets).every(v => v >= 1), `0枚以下の賭けがある: seed=${s}`);
  }
}
console.log('  賭けの上限 500 通り');

// 破産救済
const ps = [{ chips: 0 }, { chips: -4 }, { chips: 1 }, { chips: 30 }];
N.applyBailout(ps);
ok(same(ps.map(p => p.chips), [3, 3, 1, 30]), '破産救済：0枚以下だけが3枚になる');

// 同点の順位（1,1,3 方式）
const rk = pl => N.rankPlayers(pl.map((c, i) => ({ name: 'P' + i, chips: c }))).map(r => [r.p.name, r.rank]);
ok(same(rk([10, 30, 30, 5]), [['P1', 1], ['P2', 1], ['P0', 3], ['P3', 4]]), '同点の1位が2人なら次は3位');
ok(same(rk([20, 20]), [['P0', 1], ['P1', 1]]), '全員同点なら全員1位');
ok(same(rk([5, 9, 7]), [['P1', 1], ['P2', 2], ['P0', 3]]), '同点なしは素直な順位');

console.log(`\n結果: ${pass} 件OK / ${fail} 件NG`);
process.exit(fail ? 1 : 0);
