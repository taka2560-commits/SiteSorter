# -*- coding: utf-8 -*-
"""アプリアイコン(.ico)生成: 紺の角丸タイル＋橙のインボックス（トレイ＋下向き矢印）

実行: python make_icon.py → assets/app.ico
"""
import os

from PIL import Image, ImageDraw

PRIMARY = "#31658F"
ACCENT = "#F5993D"
S = 256  # ベースサイズ


def build() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 角丸タイル
    d.rounded_rectangle([8, 8, S - 8, S - 8], radius=52, fill=PRIMARY)

    p = lambda x, y: (S * x, S * y)
    w = int(S * 0.07)  # 線幅

    # トレイ（U字）
    d.line([p(0.24, 0.52), p(0.24, 0.76)], fill=ACCENT, width=w)
    d.line([p(0.24, 0.76), p(0.76, 0.76)], fill=ACCENT, width=w)
    d.line([p(0.76, 0.76), p(0.76, 0.52)], fill=ACCENT, width=w)
    d.line([p(0.24, 0.60), p(0.36, 0.60)], fill=ACCENT, width=w)
    d.line([p(0.64, 0.60), p(0.76, 0.60)], fill=ACCENT, width=w)

    # 下向き矢印（シャフト＋ヘッド）
    d.rectangle([*p(0.455, 0.16), *p(0.545, 0.40)], fill=ACCENT)
    d.polygon([p(0.34, 0.38), p(0.66, 0.38), p(0.50, 0.58)], fill=ACCENT)
    return img


def main():
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "app.ico")
    img = build()
    img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                         (64, 64), (128, 128), (256, 256)])
    img.save(os.path.join(out_dir, "app.png"))  # 確認用
    print(f"生成: {out}")


if __name__ == "__main__":
    main()
