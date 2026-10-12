# -*- coding: utf-8 -*-
"""プレイ動画の下に解説字幕の帯を付ける。

    python3 tests/caption_video.py 元動画.mp4 captions.json 出力.mp4 [--duration 秒]

captions.json は [{"t": 秒, "text": "..."}] の配列（tests/record.mjs が書き出す）。
各字幕は次の字幕の時刻まで表示する。
手元の ffmpeg に字幕フィルタ（libass / drawtext）が無くても動くよう、
帯は Pillow で画像として描き、ffmpeg で元動画の下に連結する。
"""
import argparse
import glob
import json
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont

BG_TOP = (11, 32, 25)
BG_BOTTOM = (4, 13, 9)
GOLD = (215, 184, 102)
TEXT = (245, 242, 233)
# 行頭に来てはいけない文字（禁則）
NO_HEAD = set("、。，．・：；？！ー」』）】〕〉》”’ぁぃぅぇぉっゃゅょァィゥェォッャュョ")


def find_font():
    for pat in ["/System/Library/Fonts/*W6.ttc", "/System/Library/Fonts/*W7.ttc",
                "/System/Library/Fonts/*W3.ttc", "/usr/share/fonts/**/NotoSansCJK*.ttc"]:
        hits = sorted(glob.glob(pat, recursive=True))
        if hits:
            return hits[0]
    raise SystemExit("日本語フォントが見つかりません")


def probe(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", path])
    j = json.loads(out)
    s = j["streams"][0]
    return s["width"], s["height"], float(j["format"]["duration"])


def wrap(draw, text, font, width):
    """1文字ずつ詰めて折り返す。禁則文字は前の行に残す。"""
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) <= width or not cur:
            cur += ch
            continue
        if ch in NO_HEAD:
            cur += ch          # 句読点などは行末にはみ出させる
            continue
        lines.append(cur)
        cur = ch
    if cur:
        lines.append(cur)
    return lines


def render_band(text, w, h, font_path, size, out):
    img = Image.new("RGB", (w, h), BG_BOTTOM)
    d = ImageDraw.Draw(img)
    for y in range(h):                                 # 縦グラデーション
        k = y / max(1, h - 1)
        c = tuple(round(BG_TOP[i] * (1 - k) + BG_BOTTOM[i] * k) for i in range(3))
        d.line([(0, y), (w, y)], fill=c)
    d.line([(0, 0), (w, 0)], fill=GOLD, width=max(2, h // 90))
    if text:
        pad_x = round(w * 0.06)
        font = ImageFont.truetype(font_path, size)
        lines = wrap(d, text, font, w - pad_x * 2 - size // 2)
        while len(lines) > 3 and size > 18:            # 3行に収まるまで縮める
            size -= 2
            font = ImageFont.truetype(font_path, size)
            lines = wrap(d, text, font, w - pad_x * 2 - size // 2)
        lh = round(size * 1.5)
        total = lh * len(lines)
        y = (h - total) // 2 + round(size * 0.1)
        bar_x = pad_x - round(size * 0.55)
        d.rounded_rectangle([bar_x, y + 4, bar_x + max(4, size // 8), y + total - 8], radius=3, fill=GOLD)
        for ln in lines:
            d.text((pad_x + 2, y + 2), ln, font=font, fill=(0, 0, 0))   # 影
            d.text((pad_x, y), ln, font=font, fill=TEXT)
            y += lh
    img.save(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("captions")
    ap.add_argument("out")
    ap.add_argument("--duration", type=float, default=None)
    a = ap.parse_args()

    w, h, dur = probe(a.video)
    if a.duration:
        dur = min(dur, a.duration + 1)
    caps = sorted(json.load(open(a.captions, encoding="utf-8")), key=lambda c: c["t"])
    portrait = h > w
    band_h = round(w * (0.30 if portrait else 0.115)) // 2 * 2
    size = round(w * (0.047 if portrait else 0.027))
    font_path = find_font()

    with tempfile.TemporaryDirectory() as tmp:
        seq = []                                       # (画像, 表示秒数)
        blank = os.path.join(tmp, "blank.png")
        render_band("", w, band_h, font_path, size, blank)
        if caps and caps[0]["t"] > 0.05:
            seq.append((blank, caps[0]["t"]))
        for i, c in enumerate(caps):
            png = os.path.join(tmp, f"c{i:03d}.png")
            render_band(c["text"], w, band_h, font_path, size, png)
            end = caps[i + 1]["t"] if i + 1 < len(caps) else dur
            seq.append((png, max(0.04, end - c["t"])))
        lst = os.path.join(tmp, "bands.txt")
        with open(lst, "w", encoding="utf-8") as f:
            for png, d in seq:
                f.write(f"file '{png}'\nduration {d:.3f}\n")
            f.write(f"file '{seq[-1][0]}'\n")
        subprocess.check_call([
            "ffmpeg", "-y", "-loglevel", "error", "-i", a.video,
            "-f", "concat", "-safe", "0", "-i", lst,
            "-filter_complex", "[1:v]fps=30,format=yuv420p[c];[0:v][c]vstack=inputs=2,format=yuv420p[v]",
            "-map", "[v]", "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "slow", "-crf", "20",
            "-movflags", "+faststart", a.out])
    print(f"字幕 {len(caps)} 本を付けました: {a.out}（{w}x{h + band_h}）")


if __name__ == "__main__":
    main()
