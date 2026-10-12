# -*- coding: utf-8 -*-
"""改修前後のスクリーンショットを左右に並べた比較画像を作る。

    python3 tests/compare_screens.py BEFORE_DIR AFTER_DIR OUT_DIR

tests/e2e.mjs --shots で撮った {mobile,desktop}_NN_name.png を対象にする。
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

SCREENS = [
    ("01_setup", "開始"), ("02_handoff", "手番交代"), ("03_bet", "BET（上部）"),
    ("03b_bet_bottom", "BET（下部）"), ("04a_reveal_mid", "開票（途中）"), ("04_reveal", "開票（完了）"),
    ("05_score", "収支"), ("06_claims", "答え合わせ"), ("07_final", "最終結果"),
]
FONT_PATHS = ["/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc"]


def font(size):
    for p in FONT_PATHS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def sheet(before, after, device, out, width):
    pairs = [(n, l) for n, l in SCREENS
             if os.path.exists(os.path.join(before, f"{device}_{n}.png"))
             and os.path.exists(os.path.join(after, f"{device}_{n}.png"))]
    if not pairs:
        return None
    def load(d, n):
        im = Image.open(os.path.join(d, f"{device}_{n}.png")).convert("RGB")
        return im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    rows = [(l, load(before, n), load(after, n)) for n, l in pairs]
    pad, head = 24, 44
    h = max(r[1].height for r in rows)
    W = pad * 3 + width * 2
    H = pad + 60 + len(rows) * (head + h + pad)
    img = Image.new("RGB", (W, H), "#0b0f0d")
    d = ImageDraw.Draw(img)
    d.text((pad, 18), f"{device}  改修前  →  改修後", font=font(30), fill="#F5DC99")
    y = pad + 60
    for label, b, a in rows:
        d.text((pad, y + 8), f"{label}　改修前", font=font(22), fill="#AAB8B0")
        d.text((pad * 2 + width, y + 8), f"{label}　改修後", font=font(22), fill="#F5DC99")
        img.paste(b, (pad, y + head))
        img.paste(a, (pad * 2 + width, y + head))
        y += head + h + pad
    img.save(out, quality=86)
    return out


def main():
    before, after, out_dir = sys.argv[1:4]
    os.makedirs(out_dir, exist_ok=True)
    for device, width in (("mobile", 390), ("desktop", 720)):
        out = sheet(before, after, device, os.path.join(out_dir, f"compare_{device}.jpg"), width)
        if out:
            print("出力:", out, Image.open(out).size)


if __name__ == "__main__":
    main()
