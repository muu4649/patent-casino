#!/usr/bin/env node
/**
 * プレイ動画の録画
 *
 *   node --experimental-websocket tests/record.mjs --out play.mp4 [--device mobile|desktop] [--rounds 2] [--no-captions] [--no-audio]
 *
 * 既定で、画面の下に解説字幕の帯を付ける（場面の切り替わりに合わせて録画中に記録した時刻で出す）。
 * 既定で、合成したラウンジジャズの BGM と、操作の時刻に合わせた効果音を付ける（tests/casino_audio.py）。
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
  const o = { out: path.join(ROOT, 'play.mp4'), device: 'mobile', rounds: 2, seed: 7, html: path.join(ROOT, 'index.html'), captions: true, audio: true };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--out') o.out = path.resolve(argv[++i]);
    else if (a === '--device') o.device = argv[++i];
    else if (a === '--rounds') o.rounds = Number(argv[++i]);
    else if (a === '--seed') o.seed = Number(argv[++i]);
    else if (a === '--html') o.html = path.resolve(argv[++i]);
    else if (a === '--no-captions') o.captions = false;
    else if (a === '--no-audio') o.audio = false;
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
    ev(sel.includes('wcard') ? 'card' : sel.includes('chipbtn') ? 'chip' : sel === '#btnStart' ? 'start' : 'button');
    await sleep(wait);
  };
  const hold = async sel => {
    // 長押しの間も輪が進む様子を撮りたいので、押す瞬間と離す瞬間だけ止める
    const c = await rec.exclusive(async () => { await mark(sel, 0, true); const c = await pg.centerOf(sel); await pg.press(c.x, c.y); return c; });
    ev('hold');
    await sleep(1000);
    await rec.exclusive(() => pg.release(c.x, c.y));
  };
  const pause = ms => sleep(ms);
  const caps = [];
  const cap = text => caps.push({ t: Date.now() / 1000, text });
  const evs = [];
  const ev = (type, extra) => evs.push(Object.assign({ t: Date.now() / 1000, type }, extra || {}));

  try {
    console.log('録画中 ... ' + vp.name);
    // 見せ場（8倍以上の的中）が1ラウンド目に出る乱数の種を探してから録画する
    let seed = o.seed;
    for (let tries = 0; tries < 40; tries++, seed++) {
      await pg.open(pathToFileURL(o.html).href, seed);
      await pg.waitFor(`document.getElementById('btnStart')`, 8000);
      const ok = await pg.js(`(() => { document.getElementById('btnStart').click();
        // 抽出ミスの英字だけの語（例：ｉｉ）が盤面に出る出題は動画では避ける
        const junk = w => /^[a-zA-Zａ-ｚＡ-Ｚ]+$/.test(w.w);
        return S.board.some(w => w.isHit && w.odds >= 8) && !S.board.some(junk); })()`);
      if (ok) break;
    }
    console.log('乱数の種: ' + seed);
    await pg.open(pathToFileURL(o.html).href, seed);
    await pg.js(TAP_MARKER);
    await pg.js(`window.scrollTo(0,0)`);
    await rec.start();
    cap('特許カジノ ― 発明の名称だけを見て、請求項に出てくる単語を当てるゲーム');
    await pause(3800);                                       // タイトルの登場

    // 名前とラウンド数を入れる（入力は一瞬で済ませる）
    await pg.js(`(() => {
      const ins = document.querySelectorAll('#nameInputs input');
      ['ミナト', 'ソラ'].forEach((v, i) => { ins[i].value = v; });
      const r = document.getElementById('nRounds'); r.value = '${o.rounds}'; r.dispatchEvent(new Event('change', { bubbles: true }));
    })()`);
    cap('人数・チップ・ラウンド数を決めて開始。1台の端末を回して2〜4人で遊ぶ');
    await pause(2600);
    // 録画ループと並行するとタップを取りこぼすことがあるので、画面が変わるまで押し直す
    for (let i = 0; i < 4; i++) {
      await tap('#btnStart', 0, 900);
      if (await pg.js(`!!S`)) break;
    }

    for (let r = 1; r <= o.rounds; r++) {
      const first = r === 1;
      // 盤面の答えを見て、見せ場が出る賭け先を決める（字幕に使う語もここで取る）
      const plan = await pg.js(`(() => {
        const idx = w => S.board.findIndex(x => x.w === w.w);
        const hits = S.board.filter(w => w.isHit).sort((a, b) => b.odds - a.odds);
        const miss = S.board.filter(w => !w.isHit).sort((a, b) => b.odds - a.odds);
        const r = ${r};
        // P1：高オッズの正解に厚く、罠にも1つ。P2：堅い正解と罠
        const p1 = r === 1 ? [idx(hits[0]), idx(miss[0]), idx(hits[2])] : [idx(miss[1]), idx(hits[3])];
        const p2 = r === 1 ? [idx(hits[3]), idx(miss[2])] : [idx(hits[0]), idx(hits[1]), idx(miss[0])];
        const it = S.order[S.ri];
        return { p1, p2, title: it.title, top: hits[0].w, topOdds: hits[0].odds,
                 trap: miss[0].w, traps: miss.filter(w => w.odds < 8).slice(0, 2).map(w => w.w) };
      })()`);
      const bets = [
        { cards: plan.p1, chips: first ? ['5', null, null] : ['3', 'max'] },
        { cards: plan.p2, chips: first ? ['3', '1'] : ['5', '3', null] },
      ];

      for (let pi = 0; pi < bets.length; pi++) {
        const bet = bets[pi];
        await pg.waitFor(vis('#handoff'), 8000, '手番交代');
        ev('handoff');
        if (first && pi === 0) cap('手番が来たら端末を本人に渡す。光のリングを長押しするとBETが始まる');
        else if (first) cap('交代のたびに画面は真っ暗に。前の人がどこに賭けたかは見えない');
        else if (pi === 0) cap(`ROUND ${r}。毎ラウンド別の特許が出題される`);
        await pause(first ? 2400 : 1300);
        await hold('#holdBtn');
        await pg.waitFor(`${vis('#scBet')} && document.getElementById('handoff').classList.contains('hide')`, 8000, 'BET画面');
        if (first && pi === 0) {
          cap(`お題は「${plan.title}」。並んだ12語のうち、実際に請求項に出るのは4語だけ`);
          await pause(3200);
          cap('単語をタップして最大3語まで選ぶ。枚数は 1・3・5・MAX のチップで決める');
        } else if (first) {
          cap('オッズは出現しにくさの目安。罠にも同じ帯のオッズが付いていて、倍率では見分けられない');
          await pause(1200);
        } else if (pi === 0) {
          cap('1ラウンドに賭けられるのは所持チップの半分まで。0枚になっても次のラウンドで3枚もらえる');
          await pause(900);
        } else {
          await pause(800);
        }
        if (first && pi === 0) await pause(600);
        for (let k = 0; k < bet.cards.length; k++) {
          await tap('#board .wcard', bet.cards[k], first ? 900 : 650);
          if (bet.chips[k]) await tap(`.chipbtn[data-v="${bet.chips[k]}"]`, 0, first ? 800 : 600);
        }
        await pause(first ? 1000 : 600);
        await tap('#barBtn', 0, 300);
      }

      await pg.waitFor(vis('#scReveal'), 8000, '開票');
      ev('reveal', { rows: await pg.js(`S.revealRows.map(w => ({ hit: w.isHit,
        big: !!(w.isHit && w.odds >= 8 && S.bets.some(b => b[w.w])) }))`) });
      if (first) {
        cap('全員がBETしたら開票。請求項1〜2に出た語が1語ずつ判定される');
        await pause(700);
        cap(`「${plan.top}」${plan.topOdds.toFixed(1)}倍が的中！ 8倍以上の的中は BIG WIN`);
      } else {
        cap('開票。緑のチェックが請求項に出た語、赤い×は罠');
      }
      await pg.waitFor(`${vis('#bottombar')} && document.getElementById('barBtn').textContent.includes('収支')`, 20000, '開票完了');
      await pause(first ? 2600 : 1600);
      await tap('#barBtn', 0, 200);                          // 収支
      ev('score', { n: 2 });
      cap(first ? '当たれば「賭けた枚数 × オッズ」を獲得、外れた分は没収'
                : 'このラウンドの収支。チップの増減がそのまま順位に響く');
      await pause(first ? 3600 : 2400);
      await tap('#barBtn', 0, 200);                          // 答え合わせ
      if (first) {
        cap('答え合わせ。請求項の全文で、どの語が出ていたかを確認できる');
        await pause(3000);
        const t = plan.traps.length ? plan.traps.map(w => `「${w}」`).join('や') : `「${plan.trap}」`;
        cap(`${t}は出そうで出ない。明細書では別の言葉に置き換わっていることが多い`);
      } else {
        cap('黄色はボードにあった正解語、緑は誰かが当てた語');
      }
      await pg.js(`window.scrollTo({ top: 520, behavior: 'smooth' })`);
      await pause(first ? 3600 : 2600);
      await tap('#barBtn', 0, 300);                          // 次のラウンド or 最終結果
    }
    await pg.waitFor(vis('#scFinal'), 8000, '最終結果');
    ev('final');
    const winner = await pg.js(`rankPlayers(S.players).filter(r => r.rank === 1).map(r => r.p.name + ' ' + r.p.chips + '枚').join('・')`);
    cap(`全ラウンド終了。チップが最も多い人の勝ち ― 優勝は ${winner}`);
    await pause(5200);
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
  if (o.captions && caps.length) {
    const raw = o.out.replace(/\.mp4$/, '') + '.nocap.mp4';
    fs.renameSync(o.out, raw);
    const json = path.join(work, 'captions.json');
    fs.writeFileSync(json, JSON.stringify(caps.map(c => ({ t: Math.max(0, c.t - fr[0].t), text: c.text })), null, 1));
    execFileSync('python3', [path.join(ROOT, 'tests', 'caption_video.py'), raw, json, o.out, '--duration', sec.toFixed(2)], { stdio: 'inherit' });
    fs.rmSync(raw);
  }
  if (o.audio) {
    const evJson = path.join(work, 'events.json');
    fs.writeFileSync(evJson, JSON.stringify(evs.map(e => Object.assign({}, e, { t: Math.max(0, e.t - fr[0].t) })), null, 1));
    const wav = path.join(work, 'audio.wav');
    execFileSync('python3', [path.join(ROOT, 'tests', 'casino_audio.py'), evJson, wav, '--duration', (sec + 1).toFixed(2)], { stdio: 'inherit' });
    const silent = o.out.replace(/\.mp4$/, '') + '.silent.mp4';
    fs.renameSync(o.out, silent);
    execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', silent, '-i', wav, '-map', '0:v', '-map', '1:a',
      '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', o.out]);
    fs.rmSync(silent);
  }
  console.log(`出力: ${path.relative(process.cwd(), o.out)}（${sec.toFixed(1)}秒 / 取得 ${fr.length} 枚＝平均 ${(fr.length / sec).toFixed(1)} 枚/秒 → 30fps に変換）`);
  fs.rmSync(work, { recursive: true, force: true });
}

main().catch(e => { console.error(e); process.exit(1); });
