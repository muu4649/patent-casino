#!/usr/bin/env node
/**
 * 特許カジノ E2E テスト / 画面キャプチャ
 *
 * ヘッドレス Chrome を DevTools Protocol で直接操作し、ゲーム開始から最終結果まで
 * 「実際のタップ・長押し・キー入力」で通す。外部ライブラリは使わない。
 *
 *   node --experimental-websocket tests/e2e.mjs                 # 回帰テスト一式（--strict --layout）
 *   node --experimental-websocket tests/e2e.mjs --shots DIR     # 主要画面のスクリーンショットを DIR へ
 *   node --experimental-websocket tests/e2e.mjs --html PATH     # 別の index.html を対象にする
 *
 * Node 22 以降は --experimental-websocket なしで動く。
 * Chrome の場所は環境変数 CHROME_PATH で上書きできる。
 *
 * --strict で確認すること
 *   - 手番交代の秘匿性：BET確定の直後に、前の人の選択が見える状態が1フレームも無いこと
 *   - 長押しを途中で離すと開始されないこと、Space キー長押しでも開始できること
 *   - BET確定・次のラウンドを二重に押しても、手番やラウンドが二重に進まないこと
 *   - 開票中にタップするとスキップでき、状態が壊れないこと
 *   - 画面に表示した収支・所持チップが、盤面と賭けから独立に計算した値と一致すること
 *   - コンソールにエラーが出ないこと
 * --layout で確認すること（幅 320 / 375 / 390 / 768 / 1024 / 1440）
 *   - 横スクロールが発生しないこと
 *   - 操作要素が画面外にはみ出さないこと、下部バーに隠れないこと
 *   - タップ領域が 44px を下回る操作要素の一覧
 */
import { spawn, execSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const CHROME = process.env.CHROME_PATH ||
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const TMP = process.env.PC_TMP || os.tmpdir();

const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ------------------------------------------------------------------ 引数 */
function parseArgs(argv) {
  const o = { html: path.join(ROOT, 'index.html'), shots: null, strict: false, layout: false, seed: 20261012 };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--html') o.html = path.resolve(argv[++i]);
    else if (a === '--shots') o.shots = path.resolve(argv[++i]);
    else if (a === '--strict') o.strict = true;
    else if (a === '--layout') o.layout = true;
    else if (a === '--seed') o.seed = Number(argv[++i]);
    else throw new Error('不明な引数: ' + a);
  }
  if (!o.shots && !o.strict && !o.layout) { o.strict = true; o.layout = true; }
  return o;
}

/* ------------------------------------------------------------------ CDP */
class CDP {
  constructor(ws) {
    this.ws = ws; this.seq = 0; this.pending = new Map(); this.listeners = new Set();
    ws.addEventListener('message', ev => {
      const m = JSON.parse(typeof ev.data === 'string' ? ev.data : ev.data.toString());
      if (m.id && this.pending.has(m.id)) {
        const { res, rej } = this.pending.get(m.id);
        this.pending.delete(m.id);
        if (m.error) rej(new Error(m.error.message)); else res(m.result);
      } else if (m.method) {
        for (const fn of this.listeners) fn(m);
      }
    });
  }
  send(method, params = {}) {
    const id = ++this.seq;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((res, rej) => this.pending.set(id, { res, rej }));
  }
  on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  once(method, timeout = 10000) {
    return new Promise((res, rej) => {
      const t = setTimeout(() => { off(); rej(new Error('イベント待ちタイムアウト: ' + method)); }, timeout);
      const off = this.on(m => { if (m.method === method) { clearTimeout(t); off(); res(m.params); } });
    });
  }
}

function isAppleSiliconUnderRosetta() {
  if (process.platform !== 'darwin' || process.arch !== 'x64') return false;
  try { return execSync('sysctl -n hw.optional.arm64', { encoding: 'utf8' }).trim() === '1'; }
  catch { return false; }
}

async function launchChrome() {
  if (typeof WebSocket === 'undefined') {
    throw new Error('WebSocket が使えません。node --experimental-websocket で実行してください（Node 22 以降は不要）');
  }
  if (!fs.existsSync(CHROME)) throw new Error('Chrome が見つかりません: ' + CHROME);
  const dir = fs.mkdtempSync(path.join(TMP, 'pc-chrome-'));
  const port = 9300 + Math.floor(Math.random() * 600);
  const chromeArgs = [
    '--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${dir}`,
    '--no-first-run', '--no-default-browser-check', '--disable-extensions',
    '--hide-scrollbars', '--mute-audio', '--force-color-profile=srgb',
    '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
    '--disable-backgrounding-occluded-windows', 'about:blank',
  ];
  // Intel 版の Node から起動すると Chrome も Rosetta 経由の x64 版になり、起動が極端に遅い。
  // Apple Silicon ではネイティブ版を明示して起動する。
  const proc = isAppleSiliconUnderRosetta()
    ? spawn('/usr/bin/arch', ['-arm64', CHROME, ...chromeArgs], { stdio: 'ignore' })
    : spawn(CHROME, chromeArgs, { stdio: 'ignore' });

  let wsUrl = null;
  for (let i = 0; i < 400 && !wsUrl; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const pg = list.find(t => t.type === 'page');
      if (pg) wsUrl = pg.webSocketDebuggerUrl;
    } catch { /* 起動待ち */ }
    if (!wsUrl) await sleep(100);
  }
  if (!wsUrl) { proc.kill('SIGKILL'); throw new Error('Chrome に接続できませんでした'); }
  const ws = new WebSocket(wsUrl);
  await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej); });
  const cdp = new CDP(ws);
  const close = async () => {
    try { ws.close(); } catch { /* 無視 */ }
    proc.kill('SIGKILL');
    await sleep(300);
    try { fs.rmSync(dir, { recursive: true, force: true }); } catch { /* 無視 */ }
  };
  return { cdp, close };
}

/* 決定的な乱数。旧版と新版で同じ問題・同じ盤面になるよう Math.random を差し替える */
const seedSource = seed => `(() => {
  let s = ${seed >>> 0};
  Math.random = function () {
    s = (s + 0x6D2B79F5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  try { localStorage.clear(); } catch (e) {}
})();`;

/* ------------------------------------------------------------------ ページ操作 */
class Page {
  constructor(cdp, vp) { this.cdp = cdp; this.vp = vp; this.errors = []; this.scriptId = null; }

  async open(url, seed) {
    const c = this.cdp;
    await c.send('Page.enable');
    await c.send('Runtime.enable');
    await c.send('Log.enable');
    c.on(m => {
      if (m.method === 'Runtime.exceptionThrown') {
        const d = m.params.exceptionDetails;
        this.errors.push('例外: ' + (d.exception?.description || d.text));
      } else if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
        this.errors.push('console.error: ' + m.params.args.map(a => a.value ?? a.description).join(' '));
      } else if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') {
        this.errors.push('log: ' + m.params.entry.text);
      }
    });
    const { w, h, dpr, mobile } = this.vp;
    await c.send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: dpr, mobile });
    await c.send('Emulation.setTouchEmulationEnabled', { enabled: mobile, maxTouchPoints: mobile ? 5 : 1 });
    if (this.scriptId) await c.send('Page.removeScriptToEvaluateOnNewDocument', { identifier: this.scriptId });
    this.scriptId = (await c.send('Page.addScriptToEvaluateOnNewDocument', { source: seedSource(seed) })).identifier;
    const loaded = c.once('Page.loadEventFired', 15000);
    await c.send('Page.navigate', { url });
    await loaded;
  }

  async js(expr) {
    const r = await this.cdp.send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) {
      throw new Error('JS評価エラー: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text) + '\n  式: ' + expr.slice(0, 160));
    }
    return r.result.value;
  }

  async waitFor(expr, timeout = 8000, label = expr) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      if (await this.js(`!!(${expr})`)) return;
      await sleep(50);
    }
    throw new Error('待機タイムアウト: ' + label);
  }

  async centerOf(sel, idx = 0) {
    return this.js(`(() => {
      const el = document.querySelectorAll(${JSON.stringify(sel)})[${idx}];
      if (!el) return null;
      const fixed = getComputedStyle(el).position === 'fixed' || el.closest('.bottombar,.handoff,.topbar');
      if (!fixed) el.scrollIntoView({ block: 'center', inline: 'center' });
      const b = el.getBoundingClientRect();
      return { x: b.left + b.width / 2, y: b.top + b.height / 2 };
    })()`);
  }

  async press(x, y) {
    if (this.vp.mobile) await this.cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] });
    else {
      await this.cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y });
      await this.cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
    }
  }
  async release(x, y) {
    if (this.vp.mobile) await this.cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    else await this.cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
  }

  async tap(sel, idx = 0) {
    const c = await this.centerOf(sel, idx);
    if (!c) throw new Error(`要素がありません: ${sel}[${idx}]`);
    await sleep(40);
    await this.press(c.x, c.y);
    await sleep(30);
    await this.release(c.x, c.y);
    await sleep(60);
  }

  async hold(sel, ms) {
    const c = await this.centerOf(sel);
    if (!c) throw new Error('要素がありません: ' + sel);
    await this.press(c.x, c.y);
    await sleep(ms);
    await this.release(c.x, c.y);
  }

  async key(type, key, code, vk) {
    await this.cdp.send('Input.dispatchKeyEvent', {
      type, key, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk,
      // Enter はボタンを押すのに text: '\r' が必要（実キーボードと同じ入力列にする）
      text: type === 'keyDown' ? (key === 'Enter' ? '\r' : (key.length === 1 ? key : undefined)) : undefined,
    });
  }

  async shot(file) {
    const r = await this.cdp.send('Page.captureScreenshot', { format: 'png' });
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, Buffer.from(r.data, 'base64'));
  }

  layoutCheck() {
    return this.js(`(() => {
      const vw = window.innerWidth;
      const overflowX = Math.max(0, document.documentElement.scrollWidth - vw);
      const isVis = el => {
        if (!el || el.closest('.hide')) return false;
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden') return false;
        const r = el.getBoundingClientRect();
        return r.width > 2 && r.height > 2;
      };
      const name = el => (el.id ? '#' + el.id : (el.getAttribute('class') || el.tagName)).toString().split(' ')[0];
      const targets = [...document.querySelectorAll('button, select, input[type=text], summary, label.seg')].filter(isVis);
      const small = targets.map(el => {
        const r = el.getBoundingClientRect();
        return { el: name(el), txt: (el.innerText || el.value || '').trim().replace(/\\s+/g, ' ').slice(0, 12), w: Math.round(r.width), h: Math.round(r.height) };
      }).filter(t => t.h < 44 || t.w < 44);
      const offscreen = targets.filter(el => { const r = el.getBoundingClientRect(); return r.right > vw + 1 || r.left < -1; }).map(name);
      const bar = document.getElementById('bottombar');
      let overlap = null;
      if (isVis(bar)) {
        const se = document.scrollingElement, prev = se.scrollTop;
        se.scrollTop = se.scrollHeight;
        const barTop = bar.getBoundingClientRect().top;
        const sec = [...document.querySelectorAll('section')].find(s => !s.classList.contains('hide'));
        const els = sec ? [...sec.querySelectorAll('button, .claim, .revrow, .scorecard, .scorerow, .prow')].filter(isVis) : [];
        const last = els.reduce((m, el) => Math.max(m, el.getBoundingClientRect().bottom), 0);
        overlap = Math.round(last - barTop);
        se.scrollTop = prev;
      }
      return { overflowX, small, offscreen, overlap };
    })()`);
  }
}

const vis = sel => `(el => !!el && !el.classList.contains('hide') && !el.closest('.hide') && getComputedStyle(el).display !== 'none')(document.querySelector(${JSON.stringify(sel)}))`;

/* 盤面・賭け・開始時チップから、そのラウンド後の所持チップを独立に計算する */
const EXPECT_CHIPS = `(start => S.players.map((p, i) => {
  let stake = 0, pay = 0;
  for (const k of Object.keys(S.bets[i])) {
    const w = S.board.find(x => x.w === k);
    stake += S.bets[i][k];
    if (w.isHit) pay += Math.floor(S.bets[i][k] * w.odds);
  }
  return { name: p.name, expected: start[i] - stake + pay, actual: p.chips, diff: pay - stake };
}))`;

/* ------------------------------------------------------------------ 通しプレイ */
async function playRound(pg, ctx) {
  const { shots, strict, layout, report, roundNo, last } = ctx;
  const snap = async name => {
    const key = `R${roundNo}_${name}`;
    if (shots && roundNo === 1) await pg.shot(path.join(shots, `${pg.vp.name}_${name}.png`));
    if (layout) report.layout[key] = await pg.layoutCheck();
  };
  const check = (ok, msg) => { report.checks.push({ ok: !!ok, msg }); if (!ok) console.log('    NG ' + msg); };

  // ラウンド開始時の所持チップ（破産救済後）
  await pg.waitFor(vis('#handoff'), 8000, '手番交代画面');
  await sleep(450);
  const start = await pg.js(`S.players.map(p => p.chips)`);
  if (roundNo === 1) await snap('02_handoff');

  /* --- プレイヤー1 --- */
  if (strict && roundNo === 2 && !pg.vp.mobile) {
    // キーボード：Space 長押しで開始できる
    await pg.js(`document.getElementById('holdBtn').focus()`);
    await pg.key('keyDown', ' ', 'Space', 32);
    await sleep(950);
    await pg.key('keyUp', ' ', 'Space', 32);
  } else {
    await pg.hold('#holdBtn', 1000);
  }
  await pg.waitFor(`${vis('#scBet')} && document.getElementById('handoff').classList.contains('hide')`, 8000, 'BET画面（P1）');
  await pg.waitFor(`document.querySelectorAll('#board .wcard').length === 12`, 4000, '12枚のワードカード');
  await sleep(350);

  if (strict && roundNo === 2 && !pg.vp.mobile) {
    // キーボード：カードにフォーカスして Enter で選択できる
    await pg.js(`document.querySelectorAll('#board .wcard')[0].focus()`);
    await pg.key('keyDown', 'Enter', 'Enter', 13);
    await pg.key('keyUp', 'Enter', 'Enter', 13);
    await sleep(120);
    check(await pg.js(`document.querySelectorAll('#board .wcard.sel').length === 1`), 'キーボード（Enter）でワードを選択できる');
  } else {
    await pg.tap('#board .wcard', 0);
  }
  await pg.tap('.chipbtn[data-v="5"]');
  await pg.tap('#board .wcard', 1);
  await pg.tap('#board .wcard', 2);
  await sleep(450);
  if (strict) {
    const st = await pg.js(`({ sel: document.querySelectorAll('#board .wcard.sel').length,
      dim: document.querySelectorAll('#board .wcard.dim').length, keys: Object.keys(S.bets[0]).length })`);
    check(st.sel === 3 && st.keys === 3, `3語選択でき、状態と表示が一致する（表示${st.sel}・内部${st.keys}）`);
    check(st.dim === 9, `3語選ぶと残り9語が無効表示になる（${st.dim}）`);
    // 4語目は選べない
    await pg.js(`document.querySelectorAll('#board .wcard.dim')[0] && document.querySelectorAll('#board .wcard.dim')[0].click()`);
    await sleep(80);
    check(await pg.js(`Object.keys(S.bets[0]).length === 3`), '4語目は選べない');
  }
  if (roundNo === 1) {
    await pg.js(`window.scrollTo(0, 0)`); await sleep(150);
    await snap('03_bet');
    await pg.js(`window.scrollTo(0, document.scrollingElement.scrollHeight)`); await sleep(250);
    await snap('03b_bet_bottom');
  }

  // BET確定 → 直後に秘匿状態になっているか
  await pg.tap('#barBtn');
  if (strict) {
    const s = await pg.js(`(() => {
      const ho = document.getElementById('handoff'), cs = getComputedStyle(ho);
      const bet = document.getElementById('scBet');
      const bg = cs.backgroundColor.match(/[\\d.]+/g) || [];
      return { shown: !ho.classList.contains('hide') && cs.display !== 'none', opacity: cs.opacity,
        bgAlpha: bg.length === 4 ? +bg[3] : 1,
        betHidden: bet.classList.contains('hide') || getComputedStyle(bet).display === 'none',
        sel: document.querySelectorAll('#board .wcard.sel').length, turn: S.turn };
    })()`);
    check(s.shown && s.opacity === '1' && s.bgAlpha === 1, `確定直後に交代画面が不透明で表示される（opacity ${s.opacity}・背景α ${s.bgAlpha}）`);
    check(s.betHidden || s.sel === 0, '確定直後、前の人の選択がDOM上で見える状態に残っていない');
    check(s.turn === 1, '手番が1つだけ進む');
  }

  /* --- プレイヤー2 --- */
  await pg.waitFor(vis('#handoff'), 5000, '手番交代画面（P2）');
  await sleep(350);
  if (strict && roundNo === 2) {
    // 途中で離すと始まらない
    await pg.hold('#holdBtn', 250);
    await sleep(700);
    check(await pg.js(`${vis('#handoff')} && document.getElementById('scBet').classList.contains('hide')`), '長押しを途中で離すとBETが始まらない');
  }
  await pg.hold('#holdBtn', 1000);
  if (strict) {
    // フェードアウト中に見えるのは新しい手番の空の盤面だけ
    await sleep(40);
    const s = await pg.js(`({ sel: document.querySelectorAll('#board .wcard.sel').length, turn: S.turn })`);
    check(s.sel === 0 && s.turn === 1, 'P2の盤面にP1の選択が残っていない');
  }
  await pg.waitFor(`${vis('#scBet')} && document.getElementById('handoff').classList.contains('hide')`, 8000, 'BET画面（P2）');
  await sleep(300);
  await pg.tap('#board .wcard', 3);
  await pg.tap('#board .wcard', 4);
  await pg.tap('.chipbtn[data-v="3"]');
  await sleep(200);

  if (strict) {
    // 二重押し：同じ瞬間に2回 click しても精算は1回だけ
    await pg.js(`(() => { const b = document.getElementById('barBtn'); b.click(); b.click(); })()`);
    await sleep(100);
    check(await pg.js(`S.players.every(p => p.hist.length === ${roundNo})`), 'BET確定を二重に押しても精算は1回だけ');
  } else {
    await pg.tap('#barBtn');
  }

  /* --- 開票 --- */
  await pg.waitFor(vis('#scReveal'), 5000, '開票画面');
  if (strict && roundNo === 2) {
    await sleep(500);
    await pg.tap('#scReveal');
    await sleep(250);
    const s = await pg.js(`({ rows: document.querySelectorAll('#revList .revrow').length,
      bar: ${vis('#bottombar')} && document.getElementById('barBtn').textContent.includes('収支') })`);
    check(s.rows === 12 && s.bar, `開票中にタップするとスキップされ、12行と次へボタンが揃う（${s.rows}行）`);
  } else if (roundNo === 1) {
    await sleep(1100);
    await snap('04a_reveal_mid');
  }
  await pg.waitFor(`${vis('#bottombar')} && document.getElementById('barBtn').textContent.includes('収支')`, 15000, '開票完了');
  await sleep(700);
  await pg.js(`window.scrollTo(0, 0)`); await sleep(120);
  await snap('04_reveal');

  /* --- 収支 --- */
  const expected = await pg.js(`${EXPECT_CHIPS}(${JSON.stringify(start)})`);
  for (const e of expected) check(e.expected === e.actual, `精算：${e.name} 期待 ${e.expected} / 実際 ${e.actual}`);
  await pg.tap('#barBtn');
  await pg.waitFor(vis('#scScore'), 5000, '収支画面');
  await sleep(1300);
  await snap('05_score');
  if (strict) {
    const text = await pg.js(`document.getElementById('scoreList').innerText`);
    for (const e of expected) {
      const sign = e.diff >= 0 ? '+' + e.diff : String(e.diff);
      check(text.includes(sign) && text.includes(String(e.actual)), `収支画面の表示が正しい：${e.name} ${sign} / 合計 ${e.actual}`);
    }
  }

  /* --- 答え合わせ --- */
  await pg.tap('#barBtn');
  await pg.waitFor(vis('#scClaims'), 5000, '答え合わせ画面');
  await sleep(500);
  await snap('06_claims');

  /* --- 次へ --- */
  if (!last) {
    if (strict) {
      await pg.js(`(() => { const b = document.getElementById('barBtn'); b.click(); b.click(); })()`);
      await sleep(150);
      check(await pg.js(`S.ri === ${roundNo}`), `次のラウンドを二重に押してもラウンドは1つだけ進む（S.ri=${await pg.js('S.ri')}）`);
    } else {
      await pg.tap('#barBtn');
    }
    return;
  }
  await pg.tap('#barBtn');
  await pg.waitFor(vis('#scFinal'), 5000, '最終結果画面');
  await sleep(900);
  if (roundNo === 1) await snap('07_final');
  await sleep(3200);
  await snap('07b_final_after');
  const fin = await pg.js(`({ text: document.getElementById('scFinal').innerText, chips: S.players.map(p => [p.name, p.chips]) })`);
  for (const [nm, ch] of fin.chips) check(fin.text.includes(nm) && fin.text.includes(String(ch)), `最終結果に ${nm} の ${ch} 枚が表示される`);
}

async function playGame(browser, vp, opt, rounds, label) {
  const pg = new Page(browser.cdp, vp);
  const report = { label, vp: vp.name, checks: [], layout: {}, errors: [] };
  await pg.open(pathToFileURL(opt.html).href, opt.seed);
  await pg.waitFor(`document.getElementById('btnStart')`, 8000, '開始画面');
  await sleep(1000);
  await pg.js(`(() => {
    const ins = document.querySelectorAll('#nameInputs input');
    ['ミナト', 'ソラ'].forEach((v, i) => { if (ins[i]) { ins[i].value = v; ins[i].dispatchEvent(new Event('input', { bubbles: true })); } });
    const r = document.getElementById('nRounds');
    r.value = '${rounds}'; r.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);
  await sleep(150);
  if (opt.shots) await pg.shot(path.join(opt.shots, `${vp.name}_01_setup.png`));
  if (opt.layout) report.layout['R1_01_setup'] = await pg.layoutCheck();

  await pg.tap('#btnStart');
  for (let r = 1; r <= rounds; r++) {
    await playRound(pg, { shots: opt.shots, strict: opt.strict, layout: opt.layout, report, roundNo: r, last: r === rounds });
  }
  report.errors = pg.errors.slice();
  return report;
}

/* ------------------------------------------------------------------ main */
const VIEWPORTS = {
  mobile: { name: 'mobile', w: 390, h: 844, dpr: 2, mobile: true },
  desktop: { name: 'desktop', w: 1440, h: 900, dpr: 1, mobile: false },
};
const LAYOUT_WIDTHS = [320, 375, 390, 768, 1024, 1440];

async function main() {
  const opt = parseArgs(process.argv.slice(2));
  if (!fs.existsSync(opt.html)) throw new Error('HTML がありません: ' + opt.html);
  console.log('対象: ' + path.relative(process.cwd(), opt.html));
  const reports = [];

  const run = async (vp, rounds, label, o) => {
    const b = await launchChrome();
    try {
      process.stdout.write(`- ${label} ... `);
      const rep = await playGame(b, vp, o, rounds, label);
      const ng = rep.checks.filter(c => !c.ok).length + rep.errors.length;
      console.log(ng ? `NG ${ng}件` : 'OK');
      rep.errors.forEach(e => console.log('    ' + e));
      reports.push(rep);
    } catch (e) {
      console.log('失敗');
      console.log('    ' + e.message);
      reports.push({ label, vp: vp.name, checks: [{ ok: false, msg: e.message }], layout: {}, errors: [] });
    } finally {
      await b.close();
    }
  };

  if (opt.shots) {
    for (const vp of Object.values(VIEWPORTS)) {
      await run(vp, 1, `画面キャプチャ ${vp.name}`, { ...opt, strict: false, layout: false });
    }
  }
  if (opt.strict) {
    for (const vp of Object.values(VIEWPORTS)) {
      await run(vp, 2, `回帰テスト ${vp.name}（2ラウンド）`, { ...opt, shots: null, layout: false });
    }
  }
  if (opt.layout) {
    for (const w of LAYOUT_WIDTHS) {
      const vp = { name: `w${w}`, w, h: w < 600 ? 780 : 900, dpr: 1, mobile: w < 768 };
      await run(vp, 1, `レイアウト ${w}px`, { ...opt, shots: null, strict: false, layout: true });
    }
  }

  /* --- 集計 --- */
  let fail = 0;
  const lines = [];
  for (const r of reports) {
    const ng = r.checks.filter(c => !c.ok);
    fail += ng.length + r.errors.length;
    lines.push(`## ${r.label}`);
    lines.push(`確認 ${r.checks.length} 件 / NG ${ng.length} 件 / コンソールエラー ${r.errors.length} 件`);
    for (const c of r.checks) lines.push(`- ${c.ok ? 'OK' : 'NG'} ${c.msg}`);
    for (const e of r.errors) lines.push(`- NG ${e}`);
    for (const [k, v] of Object.entries(r.layout)) {
      const issues = [];
      if (v.overflowX > 0) { issues.push(`横スクロール ${v.overflowX}px`); fail++; }
      if (v.offscreen.length) { issues.push(`画面外: ${v.offscreen.join(', ')}`); fail++; }
      if (v.overlap !== null && v.overlap > 0) { issues.push(`下部バーに ${v.overlap}px 隠れる`); fail++; }
      const small = v.small.map(s => `${s.el}「${s.txt}」${s.w}x${s.h}`);
      lines.push(`- ${k}: ${issues.length ? 'NG ' + issues.join(' / ') : 'OK'}` + (small.length ? `（44px未満: ${small.join('、')}）` : ''));
    }
    lines.push('');
  }
  const out = path.join(ROOT, 'tests', 'e2e_report.md');
  fs.writeFileSync(out, `# E2E 結果\n\n対象: ${path.relative(ROOT, opt.html)}\n実行: ${new Date().toISOString()}\n\n${lines.join('\n')}\n`);
  console.log(`\n結果: ${fail ? `NG ${fail} 件` : 'すべてOK'}  →  ${path.relative(process.cwd(), out)}`);
  process.exit(fail ? 1 : 0);
}

// 他のスクリプト（tests/record.mjs）から部品として読み込んだときは実行しない
if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(e => { console.error(e); process.exit(2); });
}

export { launchChrome, Page, vis, sleep };
