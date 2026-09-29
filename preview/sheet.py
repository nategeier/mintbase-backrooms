"""Compose the preview shots into one labelled contact sheet (drops the
minimap by cropping the right edge of each frame)."""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "..", "shots")

VIEWS = [
    ("street", "The street: MINTBASE HQ"),
    ("lobby", "Reception, Level 0"),
    ("crack", "The crack in the back wall"),
    ("h2", "First rooms past the crack"),
    ("hallway", "The 25 m hallway"),
    ("s2", "The wall that stops for no reason"),
    ("pillars", "Pillar hall"),
    ("w1", "A doorway into nothing"),
    ("dark", "The dark room"),
    ("stair", "Stairs to the EXIT"),
    ("street-corner", "From the corner"),
    ("aerial", "Both parcels from above"),
]


def font(size):
    for f in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def main(out_name="walkthrough.png", cols=3):
    frames = []
    for name, label in VIEWS:
        p = os.path.join(SHOTS, name + ".png")
        if not os.path.exists(p):
            continue
        im = Image.open(p).convert("RGB").crop((0, 0, 1080, 800))
        im = im.resize((540, 400), Image.LANCZOS)
        d = ImageDraw.Draw(im)
        f = font(17)
        tw = d.textlength(label, font=f)
        d.rectangle((10, 360, 10 + tw + 16, 390), fill=(12, 12, 12))
        d.text((18, 365), label, font=f, fill=(245, 232, 170))
        frames.append(im)
    rows = (len(frames) + cols - 1) // cols
    gap = 6
    sheet = Image.new("RGB", (cols * 540 + (cols + 1) * gap, rows * 400 + (rows + 1) * gap), (10, 10, 10))
    for i, im in enumerate(frames):
        r, c = divmod(i, cols)
        sheet.paste(im, (gap + c * (540 + gap), gap + r * (400 + gap)))
    out = os.path.join(SHOTS, out_name)
    sheet.save(out)
    print(out, sheet.size)


if __name__ == "__main__":
    main(*sys.argv[1:])
