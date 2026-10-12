# -*- coding: utf-8 -*-
"""プレイ動画用の BGM と効果音を合成する（音源ファイルは使わない）。

    python3 tests/casino_audio.py events.json 出力.wav --duration 秒

- BGM：112bpm のスウィング・ラウンジジャズ。ウォーキングベース、エレピのコンピング、
  ライドシンバル、ビブラフォンの旋律を 8 小節ループで合成する。
- 効果音：events.json（tests/record.mjs が書き出す操作の時刻）に合わせて鳴らす。
  カードのタップ・チップ・ボタン・長押し完了・開票の的中／外れ・BIG WIN・収支・優勝。
すべてここで新しく合成した音なので、権利上の制約はない。
"""
import argparse
import json
import wave

import numpy as np

SR = 44100
RNG = np.random.default_rng(20261012)


def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def t_axis(dur):
    return np.arange(int(dur * SR)) / SR


def env(n, attack=0.004, decay=0.5):
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    return a * np.exp(-t / decay)


def place(buf, sig, at, gain=1.0):
    i = int(at * SR)
    if i >= len(buf) or i + len(sig) <= 0:
        return
    s0 = max(0, -i)
    i = max(0, i)
    n = min(len(sig) - s0, len(buf) - i)
    buf[i:i + n] += sig[s0:s0 + n] * gain


def highpass(x, times=2):
    for _ in range(times):
        x = np.diff(x, prepend=0.0)
    return x


def lowpass(x, a=0.15):
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc += a * (v - acc)
        y[i] = acc
    return y


def noise(dur):
    return RNG.standard_normal(int(dur * SR))


# ---------------------------------------------------------------- 楽器
def rhodes(f, dur):
    t = t_axis(dur)
    trem = 1 + 0.08 * np.sin(2 * np.pi * 5.2 * t)
    s = np.sin(2 * np.pi * f * t) + 0.22 * np.sin(2 * np.pi * 2 * f * t)
    bell = 0.10 * np.sin(2 * np.pi * 7 * f * t) * np.exp(-t / 0.05)
    return (s * trem + bell) * env(len(t), 0.004, 0.9)


def vibes(f, dur):
    t = t_axis(dur)
    trem = 1 + 0.25 * np.sin(2 * np.pi * 6.0 * t)
    s = np.sin(2 * np.pi * f * t) + 0.12 * np.sin(2 * np.pi * 4 * f * t) * np.exp(-t / 0.2)
    return s * trem * env(len(t), 0.002, 1.1)


def bass(f, dur):
    t = t_axis(dur)
    s = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * 2 * f * t) + 0.1 * np.sin(2 * np.pi * 3 * f * t)
    return s * env(len(t), 0.006, 0.38)


def ride(dur=0.45):
    t = t_axis(dur)
    metal = sum(np.sin(2 * np.pi * f * t + RNG.uniform(0, 6)) for f in (3150, 4610, 5930, 7340, 8810))
    n = highpass(noise(dur), 3)
    return (0.05 * metal + 0.25 * n / (np.abs(n).max() + 1e-9)) * env(len(t), 0.001, 0.22)


def hat(dur=0.05):
    n = highpass(noise(dur), 3)
    return n / (np.abs(n).max() + 1e-9) * env(len(n), 0.001, 0.015)


def brush(dur=0.18):
    n = noise(dur)
    n = highpass(lowpass(n, 0.35), 1)
    return n / (np.abs(n).max() + 1e-9) * env(len(n), 0.01, 0.07)


def kick(dur=0.16):
    t = t_axis(dur)
    f = 50 + 40 * np.exp(-t / 0.03)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * env(len(t), 0.002, 0.07)


def bell(f, dur=0.6, decay=0.25):
    t = t_axis(dur)
    s = sum(a * np.sin(2 * np.pi * f * r * t) for r, a in ((1, 1), (2.76, .45), (5.4, .22), (8.93, .1)))
    return s * env(len(t), 0.001, decay)


def brass(freqs, dur, attack=0.03):
    t = t_axis(dur)
    vib = 1 + 0.006 * np.sin(2 * np.pi * 5.5 * t) * np.clip((t - 0.15) / 0.2, 0, 1)
    s = np.zeros_like(t)
    for f in freqs:
        for h in range(1, 9):
            s += (1 / h) * np.sin(2 * np.pi * f * h * vib * t + h)
    a = np.clip(t / attack, 0, 1) * np.clip((dur - t) / 0.12, 0, 1)
    return s / len(freqs) * a


# ---------------------------------------------------------------- 効果音
def sfx_tap():
    t = t_axis(0.05)
    out = 0.5 * np.sin(2 * np.pi * 1700 * t) * env(len(t), 0.001, 0.012)
    place(out, hat(0.03), 0, 0.25)
    return out


def sfx_chip():
    out = np.zeros(int(0.25 * SR))
    for k, (f, g) in enumerate(((2650, 1.0), (3320, 0.7), (2900, 0.45))):
        place(out, bell(f, 0.15, 0.035), 0.032 * k, g)
    return out


def sfx_button():
    out = np.zeros(int(0.6 * SR))
    for k in range(3):
        place(out, sfx_chip(), 0.04 * k, 0.6)
    for k, n in enumerate((84, 88, 91)):
        place(out, bell(midi(n), 0.5, 0.18), 0.12 + 0.05 * k, 0.35)
    return out


def sfx_whoosh(dur=0.6, up=False):
    n = noise(dur)
    n = lowpass(n, 0.06 if not up else 0.12)
    e = np.sin(np.linspace(0, np.pi, len(n))) ** 2
    return n / (np.abs(n).max() + 1e-9) * e


def sfx_hold():
    out = np.zeros(int(0.9 * SR))
    place(out, sfx_whoosh(0.35, True), 0, 0.5)
    for k, n in enumerate((79, 84, 88, 91)):
        place(out, bell(midi(n), 0.6, 0.22), 0.28 + 0.045 * k, 0.32)
    return out


def sfx_hit():
    out = np.zeros(int(0.7 * SR))
    place(out, bell(midi(88), 0.6, 0.2), 0, 0.5)
    place(out, bell(midi(95), 0.5, 0.15), 0.06, 0.3)
    return out


def sfx_miss():
    t = t_axis(0.22)
    f = 210 - 70 * t / 0.22
    s = np.sign(np.sin(2 * np.pi * np.cumsum(f) / SR)) * 0.4 + np.sin(2 * np.pi * np.cumsum(f) / SR)
    return lowpass(s, 0.2) * env(len(t), 0.003, 0.08)


def coin_shower(dur=1.6, n=70):
    out = np.zeros(int((dur + 0.3) * SR))
    for _ in range(n):
        at = (RNG.random() ** 1.6) * dur
        place(out, bell(RNG.uniform(2300, 5200), 0.15, RNG.uniform(0.02, 0.05)), at, RNG.uniform(0.12, 0.35))
    return out


def sfx_bigwin():
    out = np.zeros(int(2.6 * SR))
    for k, n in enumerate((72, 76, 79, 84, 88, 91, 96)):
        place(out, bell(midi(n), 0.7, 0.25), 0.055 * k, 0.45)
    place(out, brass([midi(n) for n in (60, 64, 67, 72)], 0.9), 0.4, 0.45)
    place(out, coin_shower(1.6, 80), 0.35, 0.9)
    return out


def sfx_counter(n=12, dur=0.72):
    out = np.zeros(int((dur + 0.2) * SR))
    for k in range(n):
        place(out, bell(1900 + 90 * k, 0.08, 0.02), dur * k / n, 0.35)
    return out


def sfx_fanfare():
    out = np.zeros(int(4.0 * SR))
    place(out, brass([midi(n) for n in (55, 59, 62, 67)], 0.2), 0.0, 0.7)
    place(out, brass([midi(n) for n in (55, 59, 62, 67)], 0.14), 0.26, 0.6)
    place(out, brass([midi(n) for n in (60, 64, 67, 72)], 1.7, 0.05), 0.46, 0.85)
    crash = highpass(noise(2.2), 2)
    crash = crash / (np.abs(crash).max() + 1e-9) * env(len(crash), 0.002, 0.7)
    place(out, crash, 0.46, 0.25)
    place(out, coin_shower(2.2, 110), 0.5, 0.8)
    return out


# ---------------------------------------------------------------- BGM
BPM = 112
BEAT = 60 / BPM
SW = 2 / 3                                  # スウィングの裏拍位置

# 8 小節：Fmaj7 Dm7 Gm7 C7 Am7 D7 Gm7 C7（ルートレス・ボイシング）
CHORDS = [
    (41, (57, 60, 64, 67)), (38, (53, 57, 60, 64)), (43, (58, 62, 65, 69)), (36, (58, 62, 64, 67)),
    (45, (60, 64, 67, 71)), (38, (60, 64, 66, 69)), (43, (58, 62, 65, 69)), (36, (58, 62, 64, 67)),
]
MELODY = [  # (小節, 拍, MIDI, 拍数)
    (0, 0, 72, 1), (0, 1 + SW, 74, .4), (0, 2, 76, 1.6),
    (1, 0, 77, .7), (1, SW, 76, .4), (1, 1, 74, 1), (1, 2 + SW, 72, 1.2),
    (2, 0, 70, 1.6), (2, 1 + SW, 72, .4), (2, 2, 74, 1), (2, 3, 77, 1),
    (3, 0, 76, 2), (3, 2 + SW, 74, .4), (3, 3, 72, 1),
    (4, 0, 72, 1), (4, 1 + SW, 76, .4), (4, 2, 79, 1.6),
    (5, 0, 78, .7), (5, SW, 76, .4), (5, 1, 74, 1), (5, 2 + SW, 72, 1.2),
    (6, 0, 70, 1), (6, 1, 74, 1), (6, 2, 77, 1), (6, 3, 76, 1),
    (7, 0, 72, 3),
]


def walking_line(root, nxt):
    third = root + (4 if root in (41,) else 3)
    return [root, third, root + 7, nxt + (1 if nxt < root + 7 else -1)]


def bgm(duration):
    out = np.zeros(int((duration + 3) * SR))
    bar = 4 * BEAT
    nbar = int(duration / bar) + 2
    for b in range(nbar):
        t0 = b * bar
        root, voicing = CHORDS[b % 8]
        nxt = CHORDS[(b + 1) % 8][0]
        for k, n in enumerate(walking_line(root, nxt)):
            place(out, bass(midi(n), BEAT * 1.1), t0 + k * BEAT, 0.55)
        hits = [0, 1 + SW] if b % 2 == 0 else [1 + SW, 3]
        for h in hits:
            for n in voicing:
                place(out, rhodes(midi(n), BEAT * 1.6), t0 + h * BEAT + RNG.uniform(0, 0.008), 0.11)
        for beat in range(4):
            place(out, ride(), t0 + beat * BEAT, 0.16)
            place(out, kick(), t0 + beat * BEAT, 0.12)
            if beat in (1, 3):
                place(out, ride(0.3), t0 + (beat + SW) * BEAT, 0.10)
                place(out, hat(), t0 + beat * BEAT, 0.18)
                place(out, brush(), t0 + beat * BEAT, 0.07)
        # 旋律は2周目から（冒頭はリズムだけで始める）
        if b >= 2:
            for mb, beat, n, d in MELODY:
                if mb == b % 8:
                    place(out, vibes(midi(n), d * BEAT + 0.6), t0 + beat * BEAT, 0.17)
    out = out[:int(duration * SR)]
    fade_in, fade_out = int(1.2 * SR), int(2.5 * SR)
    out[:fade_in] *= np.linspace(0, 1, fade_in)
    out[-fade_out:] *= np.linspace(1, 0, fade_out)
    return out


# ---------------------------------------------------------------- 組み立て
REVEAL_LEAD, REVEAL_STEP = 0.45, 0.30        # template.html の開票タイミングと同じ


def build(events, duration):
    music = bgm(duration)
    fx = np.zeros_like(music)
    duck = np.ones_like(music)

    def duck_at(at, dur, depth=0.4):
        i, j = int(at * SR), int((at + dur) * SR)
        i, j = max(0, i), min(len(duck), j)
        if j > i:
            ramp = np.minimum(1, np.minimum(np.arange(j - i), np.arange(j - i)[::-1]) / (0.15 * SR))
            duck[i:j] = np.minimum(duck[i:j], 1 - depth * ramp)

    for e in events:
        t, kind = e["t"], e["type"]
        if kind == "card":
            place(fx, sfx_tap(), t, 0.5)
        elif kind == "chip":
            place(fx, sfx_chip(), t, 0.55)
        elif kind == "start":
            place(fx, sfx_button(), t, 0.6)
        elif kind == "button":
            place(fx, sfx_button(), t, 0.5)
        elif kind == "handoff":
            place(fx, sfx_whoosh(0.7), t, 0.22)
        elif kind == "hold":
            place(fx, sfx_hold(), t + 0.62, 0.6)
        elif kind == "reveal":
            for k, row in enumerate(e["rows"]):
                at = t + REVEAL_LEAD + REVEAL_STEP * k + 0.12
                place(fx, sfx_hit() if row["hit"] else sfx_miss(), at, 0.55 if row["hit"] else 0.35)
                if row.get("big"):
                    place(fx, sfx_bigwin(), at + 0.08, 0.75)
                    duck_at(at, 2.4, 0.55)
        elif kind == "score":
            for k in range(e.get("n", 2)):
                place(fx, sfx_counter(), t + 0.22 + 0.14 * k, 0.5)
        elif kind == "final":
            place(fx, sfx_fanfare(), t + 0.3, 0.85)
            duck_at(t + 0.2, 3.2, 0.65)

    mix = music * duck * 0.55 + fx
    mix = np.tanh(mix * 1.1)                    # 軽いリミッター
    mix /= max(1e-9, np.abs(mix).max()) / 0.89
    return mix


def write_wav(path, x):
    st = np.stack([x, x], axis=1)
    # 少しだけ左右に広げる（遅延で擬似ステレオ）
    d = int(0.012 * SR)
    st[d:, 1] = 0.85 * x[d:] + 0.15 * x[:-d]
    pcm = (np.clip(st, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("events")
    ap.add_argument("out")
    ap.add_argument("--duration", type=float, required=True)
    a = ap.parse_args()
    events = json.load(open(a.events, encoding="utf-8"))
    write_wav(a.out, build(events, a.duration))
    print(f"音声を合成しました: {a.out}（{a.duration:.1f}秒・効果音 {len(events)} 件）")


if __name__ == "__main__":
    main()
