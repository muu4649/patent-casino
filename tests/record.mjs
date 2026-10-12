#!/usr/bin/env node
/**
 * プレイ動画の録画
 *
 *   node --experimental-websocket tests/record.mjs --out play.mp4 [--device mobile|desktop] [--rounds 2]
 *
 * ヘッドレス Chrome で実解像度のスクリーンショットを連続取得し、ffmpeg で 30fps の mp4 にする。
 * 見せ場が入るよう、録画用のプレイヤーは盤面の正解を見て賭け先を選ぶ
 * （高オッズの的中と罠への空振りが両方映るように）。ゲーム本体には手を入れない。
 * タップした位置は録画中だけ円で表示する。
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { launchChrome, Page, vis, sleep } from './e2e.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TMP = process.env.PC_TMP || os.tmpdir();

function parseArgs(argv) {
  const o = { out: path.join(ROOT, 'play.mp4'), device: 'mobile', rounds: 2, seed: 7, html: path.join(ROOT, 'index.html') };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--out') o.out = path.resolve(argv[++i]);
    else if (a === '--device') o.device = argv[++i];
    else if (a === '--rounds') o.rounds = Number(argv[++i]);
    else if (a === '--seed') o.seed = Number(argv[++i]);
    else if (a === '--html') o.html = path.resolve(argv[++i]);
    else throw new Error('不明な引数: ' + a);
  }
  return o;
}

const DEVICES = {
  mobile: { name: 'mobile', w: 390, h: 844, dpr: 2, mobile: true },
  desktop: { name: 'desktop', w: 1280, h: 800, dpr: 1, mobile: false },
};

/* 録画中だけタップ位置を見せる */
const TAP_MARKER = `(() => {
  if (window.__tapMarker) return;
  window.__tapMarker = true;
  const st = document.createElement('style');
  st.textContent = '.__tap{position:fixed;z-index:9999;width:46px;height:46px;margin:-23px 0 0 -23px;border-radius:50%;' +
    'border:3px solid rgba(255,255,255,.9);background:rgba(255,255,255,.25);pointer-events:none;' +
    'animation:__tap .55s ease-out forwards}@keyframes __tap{from{transform:scale(.5);opacity:1}to{transform:scale(1.5);opacity:0}}' +
    '.__hold{animation:__hold .9s ease-out forwards}@keyframes __hold{0%{transform:scale(.6);opacity:1}80%{transform:scale(1);opacity:1}100%{transform:scale(1.4);opacity:0}}';
  document.head.appendChild(st);
  window.__mark = (x, y, hold) => {
    const d = document.createElement('div');
    d.className = '__tap' + (hold ? ' __hold' : '');
    d.style.left = x + 'px'; d.style.top = y + 'px';
    document.body.appendChild(d);
    setTimeout(() => d.remove(), 1000);
  };
})()`;

class Recorder {
  constructor(page, dir) { this.page = page; this.dir = dir; this.frames = []; this.n = 0; this.off = null; }
  /* screencast は CSS ピクセル（390幅）でしか返らないため、
     実解像度のスクリーンショットを連続で撮ってフレームにする */
  async start() {
    fs.mkdirSync(this.dir, { recursive: true });
    this.running = true;
    this.loop = (async () => {
      while (this.running) {
        if (this.paused) { await sleep(8); continue; }
        const t = Date.now() / 1000;
        try {
          this.inflight = this.page.cdp.send('Page.captureScreenshot', { format: 'jpeg', quality: 86, optimizeForSpeed: true });
          const r = await this.inflight;
          const f = path.join(this.dir, `f${String(++this.n).padStart(5, '0')}.jpg`);
          fs.writeFileSync(f, Buffer.from(r.data, 'base64'));
          this.frames.push({ f, t });
        } catch { /* ページ遷移中などは飛ばす */ }
      }
    })();
  }
  async stop() {
    this.running = false;
    await this.loop;
  }
  /* 撮影中はページの座標がずれてタップが別の要素に当たるため、入力の間だけ止める */
  async exclusive(fn) {
    this.paused = true;
    try { await this.inflight; } catch { /* 無視 */ }
    try { return await fn(); } finally { this.paused = false; }
  }
}

async function main() {
  const o = parseArgs(process.argv.slice(2));
  const vp = DEVICES[o.device];
  if (!vp) throw new Error('--device は mobile か desktop');
  const work = fs.mkdtempSync(path.join(TMP, 'pc-rec-'));
  const b = await launchChrome();
  const pg = new Page(b.cdp, vp);
  const rec = new Recorder(pg, path.join(work, 'frames'));

  // タップ位置の表示を挟むため tap / hold を包む
  const mark = async (sel, idx, hold) => {
    const c = await pg.centerOf(sel, idx);
    if (c) await pg.js(`window.__mark(${c.x}, ${c.y}, ${hold ? 'true' : 'false'})`);
  };
  const tap = async (sel, idx = 0, wait = 650) => {
    await rec.exclusive(async () => { await mark(sel, idx, false); await pg.tap(sel, idx); });
    await sleep(wait);
  };
  const hold = async sel => {
    // 長押しの間も輪が進む様子を撮りたいので、押す瞬間と離す瞬間だけ止める
    const c = await rec.exclusive(async () => { await mark(sel, 0, true); const c = await pg.centerOf(sel); await pg.press(c.x, c.y); return c; });
    await sleep(1000);
    await rec.exclusive(() => pg.release(c.x, c.y));
  };
  const pause = ms => sleep(ms);

  try {
    console.log('録画中 ... ' + vp.name);
    // 見せ場（8倍以上の的中）が1ラウンド目に出る乱数の種を探してから録画する
    let seed = o.seed;
    for (let tries = 0; tries < 40; tries++, seed++) {
      await pg.open(pathToFileURL(o.html).href, seed);
      await pg.waitFor(`document.getElementById('btnStart')`, 8000);
      const ok = await pg.js(`(() => { document.getElementById('btnStart').click();
        return S.board.some(w => w.isHit && w.odds >= 8) && S.board.filter(w => w.isHit).length === 4; })()`);
      if (ok) break;
    }
    console.log('乱数の種: ' + seed);
    await pg.open(pathToFileURL(o.html).href, seed);
    await pg.js(TAP_MARKER);
    await pg.js(`window.scrollTo(0,0)`);
    await rec.start();
    await pause(2200);                                       // タイトルの登場

    // 名前とラウンド数を入れる（入力は一瞬で済ませる）
    await pg.js(`(() => {
      const ins = document.querySelectorAll('#nameInputs input');
      ['ミナト', 'ソラ'].forEach((v, i) => { ins[i].value = v; });
      const r = document.getElementById('nRounds'); r.value = '${o.rounds}'; r.dispatchEvent(new Event('change', { bubbles: true }));
    })()`);
    await pause(900);
    // 録画ループと並行するとタップを取りこぼすことがあるので、画面が変わるまで押し直す
    for (let i = 0; i < 4; i++) {
      await tap('#btnStart', 0, 900);
      if (await pg.js(`!!S`)) break;
    }

    for (let r = 1; r <= o.rounds; r++) {
      // 盤面の答えを見て、見せ場が出る賭け先を決める
      const plan = await pg.js(`(() => {
        const idx = w => S.board.findIndex(x => x.w === w.w);
        const hits = S.board.filter(w => w.isHit).sort((a, b) => b.odds - a.odds);
        const miss = S.board.filter(w => !w.isHit).sort((a, b) => b.odds - a.odds);
        const r = ${r};
        // P1：高オッズの正解に厚く、罠にも1つ。P2：堅い正解と罠
        const p1 = r === 1 ? [idx(hits[0]), idx(miss[0]), idx(hits[2])] : [idx(miss[1]), idx(hits[3])];
        const p2 = r === 1 ? [idx(hits[3]), idx(miss[2])] : [idx(hits[0]), idx(hits[1]), idx(miss[0])];
        return { p1, p2 };
      })()`);
      const bets = [
        { cards: plan.p1, chips: r === 1 ? ['5', null, null] : ['3', 'max'] },
        { cards: plan.p2, chips: r === 1 ? ['3', '1'] : ['5', '3', null] },
      ];

      for (const bet of bets) {
        await pg.waitFor(vis('#handoff'), 8000, '手番交代');
        await pause(1300);
        await hold('#holdBtn');
        await pg.waitFor(`${vis('#scBet')} && document.getElementById('handoff').classList.contains('hide')`, 8000, 'BET画面');
        await pause(1500);                                   // 発明の名称を読む間
        for (let k = 0; k < bet.cards.length; k++) {
          await tap('#board .wcard', bet.cards[k], 700);
          if (bet.chips[k]) await tap(`.chipbtn[data-v="${bet.chips[k]}"]`, 0, 650);
        }
        await pause(700);
        await tap('#barBtn', 0, 300);
      }

      await pg.waitFor(vis('#scReveal'), 8000, '開票');
      await pg.waitFor(`${vis('#bottombar')} && document.getElementById('barBtn').textContent.includes('収支')`, 20000, '開票完了');
      await pause(1600);
      await tap('#barBtn', 0, 2600);                          // 収支
      await tap('#barBtn', 0, 300);                           // 答え合わせ
      await pause(1800);
      await pg.js(`window.scrollTo({ top: 520, behavior: 'smooth' })`);
      await pause(2000);
      await tap('#barBtn', 0, 300);                           // 次のラウンド or 最終結果
    }
    await pg.waitFor(vis('#scFinal'), 8000, '最終結果');
    await pause(4500);
    await rec.stop();
  } finally {
    await b.close();
  }

  if (pg.errors.length) console.log('コンソールエラー:\n  ' + pg.errors.join('\n  '));

  /* フレームの実時間をそのまま使って 30fps の動画にする */
  const fr = rec.frames;
  if (fr.length < 10) throw new Error('フレームが足りません: ' + fr.length);
  const lines = [];
  for (let i = 0; i < fr.length; i++) {
    const dur = i + 1 < fr.length ? Math.max(0.001, fr[i + 1].t - fr[i].t) : 0.5;
    lines.push(`file '${fr[i].f}'`, `duration ${dur.toFixed(4)}`);
  }
  lines.push(`file '${fr[fr.length - 1].f}'`);
  const list = path.join(work, 'list.txt');
  fs.writeFileSync(list, lines.join('\n'));
  fs.mkdirSync(path.dirname(o.out), { recursive: true });
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', list,
    '-vf', 'fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2', '-c:v', 'libx264', '-preset', 'slow', '-crf', '20',
    '-pix_fmt', 'yuv420p', '-movflags', '+faststart', o.out]);
  const sec = fr[fr.length - 1].t - fr[0].t;
  console.log(`出力: ${path.relative(process.cwd(), o.out)}（${sec.toFixed(1)}秒 / 取得 ${fr.length} 枚＝平均 ${(fr.length / sec).toFixed(1)} 枚/秒 → 30fps に変換）`);
  fs.rmSync(work, { recursive: true, force: true });
}

main().catch(e => { console.error(e); process.exit(1); });
