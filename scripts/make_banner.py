"""README banner -> docs/assets/banner.png, cut from the synthetic galaxy map (docs/images/galaxy_demo.png).

Run after `make docs` refreshes the galaxy map:  .venv/bin/python scripts/make_banner.py
"""
from pathlib import Path

import matplotlib
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BG = "#0d1224"                      # background of the galaxy map
W, H = 1680, 624


def main() -> None:
    src = Image.open(ROOT / "docs/images/galaxy_demo.png").convert("RGB")
    crop = src.crop((20, 215, 1360, 1160))           # the network only, without the legend
    h = 600
    w = round(crop.width * h / crop.height)
    crop = crop.resize((w, h), Image.LANCZOS)
    mask = Image.new("L", crop.size, 0)              # feather every edge into the background
    ImageDraw.Draw(mask).rounded_rectangle((60, 40, w - 90, h - 40), radius=120, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(45))
    canvas = Image.new("RGB", (W, H), BG)
    canvas.paste(crop, (10, 12), mask)

    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")
    ax.imshow(np.asarray(canvas), extent=(0, W, H, 0))
    x0 = 900
    ax.text(x0, 220, "tbg-kit", color="#f5c26b", fontsize=66, fontweight="bold", va="baseline")
    ax.text(x0, 340, "Who controls Thailand's business groups:\nownership, pyramids and the finance–business nexus",
            color="#e8ecf6", fontsize=18.5, va="baseline", linespacing=1.6)
    ax.text(x0, 470, "SET registers · 56-1 One Reports · DBD BOJ.5 · bank Pillar 3 · GLEIF",
            color="#9fb0d0", fontsize=14, va="baseline")
    ax.text(W - 25, 600, "Synthetic demonstration: every company, person and number in this network is fictional",
            color="#7c8aab", fontsize=9.5, ha="right", va="baseline")
    out = ROOT / "docs/assets/banner.png"
    fig.savefig(out, dpi=100, facecolor=BG)
    print(out, Image.open(out).size)


if __name__ == "__main__":
    main()
