"""Procedural Backrooms tileset for a Voxels parcel.

Voxels' voxel atlas is a 1024x1024 image cut into a 4x4 grid of 256px cells.
A voxel whose texture index is `t` samples cell (t % 4, t // 4); texture 16
wraps to cell (0, 0). Only the middle 128px of a cell is ever sampled (the
mesher's UV margin is 0.188), so each material is a seamless 128px tile and
the rest of the cell is that same tile wrapped around it, which keeps mipmaps
from bleeding a neighbour's colour in.

Every material here tiles on its own: one tile is one 0.5m voxel face.
"""

from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image

T = 128  # tile size in px (one 0.5m voxel face)
CELL = 256
ATLAS = 1024

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "out", "assets")


# ---------------------------------------------------------------- helpers

def hex_rgb(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float64)


def tnoise(n: int, feature: float, seed: int) -> np.ndarray:
    """Seamless (periodic) gaussian-filtered noise, zero mean, unit std."""
    rng = np.random.default_rng(seed)
    w = rng.standard_normal((n, n))
    fx = np.fft.fftfreq(n)[:, None]
    fy = np.fft.fftfreq(n)[None, :]
    f2 = fx ** 2 + fy ** 2
    filt = np.exp(-f2 * (np.pi * feature) ** 2)
    out = np.real(np.fft.ifft2(np.fft.fft2(w) * filt))
    out -= out.mean()
    s = out.std()
    return out / s if s > 0 else out


def fill(color: str) -> np.ndarray:
    return np.ones((T, T, 3)) * hex_rgb(color)


def shade(img: np.ndarray, amount: np.ndarray) -> np.ndarray:
    """Multiply brightness by (1 + amount)."""
    return img * (1.0 + amount[..., None])


def mix(a: np.ndarray, b: np.ndarray, t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0, 1)[..., None]
    return a * (1 - t) + b * t


def edge_fade(margin: float = 0.3) -> np.ndarray:
    """1 in the middle of the tile, 0 at its border (for blemishes that must
    still meet plain neighbours at the seams)."""
    u = np.linspace(0, 1, T, endpoint=False) + 0.5 / T
    d = np.minimum(u, 1 - u)
    m = np.clip(d / margin, 0, 1)
    m = m[:, None] * m[None, :]
    return m * m * (3 - 2 * m)


def yy_xx():
    y, x = np.mgrid[0:T, 0:T].astype(np.float64)
    return y, x


# ---------------------------------------------------------------- materials
# Each returns a (T, T, 3) float array in 0..255, row 0 = the TOP of the face.

WALL_BASE = "#d8c46c"
WALL_LINE = "#c2ab52"


def wallpaper(seed: int = 1) -> np.ndarray:
    """Level 0's mono-yellow wallpaper: faint vertical chevron stripes."""
    y, x = yy_xx()
    img = fill(WALL_BASE)
    # stripe centres every 16px; each stripe is a zig-zag with a 16px period
    period = 16.0
    phase = (y % period) / period  # 0..1
    tri = np.abs(phase * 2 - 1)  # 1 -> 0 -> 1
    offset = (tri - 0.5) * 5.0  # +-2.5px zig-zag
    dx = ((x - 8 - offset) + period / 2) % period - period / 2
    line = np.exp(-(dx ** 2) / (2 * 0.55 ** 2))
    img = mix(img, np.ones_like(img) * hex_rgb(WALL_LINE), line * 0.85)
    # a faint diamond dot between stripes
    dy = ((y - 8) + period / 2) % period - period / 2
    dx2 = ((x) + period / 2) % period - period / 2
    dot = np.exp(-((dx2 ** 2) + (dy ** 2)) / (2 * 0.9 ** 2))
    img = mix(img, np.ones_like(img) * hex_rgb(WALL_LINE), dot * 0.55)
    # aging: soft blotches + fine paper grain
    img = shade(img, 0.018 * tnoise(T, 18, seed) + 0.014 * tnoise(T, 1.2, seed + 7))
    # faint vertical streaks (moisture running down)
    streak = tnoise(T, 3, seed + 11)
    streak = np.repeat(streak[:1, :], T, axis=0) * 0.6 + tnoise(T, 40, seed + 12) * 0.4
    img = shade(img, -0.012 * np.abs(streak))
    return img


def wallpaper_baseboard(seed: int = 2) -> np.ndarray:
    """Wallpaper with the cream baseboard along the bottom of the face."""
    img = wallpaper(seed)
    y, x = yy_xx()
    board_top = T - 15
    board = fill("#e3dac0")
    board = shade(board, 0.02 * tnoise(T, 2, seed + 3))
    img = np.where((y >= board_top)[..., None], board, img)
    # top lip of the board + the shadow it casts on the paper above
    img = np.where((y == board_top)[..., None], hex_rgb("#f2ecd8"), img)
    img = np.where((y == board_top - 1)[..., None], img * 0.86, img)
    img = np.where((y == board_top - 2)[..., None], img * 0.94, img)
    # grime at the floor line
    img = np.where((y >= T - 2)[..., None], img * 0.82, img)
    return img


CARPET = "#a99658"


def carpet(seed: int = 3) -> np.ndarray:
    img = fill(CARPET)
    fibre = tnoise(T, 0.7, seed)
    tuft = tnoise(T, 2.2, seed + 1)
    mottle = tnoise(T, 22, seed + 2)
    img = shade(img, 0.09 * fibre + 0.05 * tuft + 0.05 * mottle)
    # sparse dark flecks
    rng = np.random.default_rng(seed + 9)
    fleck = (rng.random((T, T)) > 0.992).astype(np.float64)
    img = mix(img, img * 0.62, fleck)
    return img


def carpet_stained(seed: int = 4) -> np.ndarray:
    img = carpet(seed)
    y, x = yy_xx()
    c = (T - 1) / 2
    r = np.sqrt(((x - c) / 1.0) ** 2 + ((y - c) / 0.8) ** 2)
    blob = r + 14 * tnoise(T, 10, seed + 5)
    wet = np.clip((52 - blob) / 14, 0, 1)
    ring = np.exp(-((blob - 50) ** 2) / (2 * 3.0 ** 2))
    fade = edge_fade(0.28)
    damp = mix(img, img * np.array([0.72, 0.68, 0.58]), wet * fade)
    damp = mix(damp, damp * np.array([0.62, 0.56, 0.44]), ring * fade * 0.8)
    return damp


CEIL = "#e6e1cf"


def ceiling_tile(seed: int = 5, stained: bool = False) -> np.ndarray:
    y, x = yy_xx()
    img = fill(CEIL)
    img = shade(img, 0.025 * tnoise(T, 14, seed) + 0.02 * tnoise(T, 1.0, seed + 1))
    # fissured acoustic pattern: short dark worms
    worms = tnoise(T, 1.6, seed + 2)
    worm_mask = np.clip((worms - 1.75) * 2.2, 0, 1)
    img = mix(img, img * 0.72, worm_mask)
    pits = np.random.default_rng(seed + 3).random((T, T)) > 0.985
    img = mix(img, img * 0.8, pits.astype(np.float64))
    if stained:
        c = (T - 1) / 2
        r = np.sqrt((x - c - 6) ** 2 + (y - c + 4) ** 2)
        blob = r + 10 * tnoise(T, 12, seed + 4)
        inner = np.clip((44 - blob) / 12, 0, 1)
        ring = np.exp(-((blob - 44) ** 2) / (2 * 2.2 ** 2))
        fade = edge_fade(0.22)
        img = mix(img, img * np.array([0.93, 0.86, 0.70]), inner * fade)
        img = mix(img, img * np.array([0.72, 0.60, 0.40]), ring * fade)
    # T-bar grid: bright painted metal at the edge, groove just inside
    d = np.minimum(np.minimum(x, T - 1 - x), np.minimum(y, T - 1 - y))
    img = np.where((d <= 2)[..., None], hex_rgb("#efece2"), img)
    img = np.where((d == 3)[..., None], img * 0.78, img)
    return img


def panel_off(seed: int = 6) -> np.ndarray:
    """A dead fluorescent troffer: metal frame, prismatic diffuser."""
    y, x = yy_xx()
    img = fill("#e4e7e4")
    prism = (((x % 4) < 1) & ((y % 4) < 1)).astype(np.float64)
    img = mix(img, img * 0.9, prism)
    img = shade(img, 0.015 * tnoise(T, 20, seed))
    d = np.minimum(np.minimum(x, T - 1 - x), np.minimum(y, T - 1 - y))
    img = np.where((d <= 5)[..., None], hex_rgb("#cfd2cf"), img)
    img = np.where((d == 6)[..., None], img * 0.8, img)
    img = np.where((d <= 1)[..., None], hex_rgb("#efece2"), img)
    return img


def concrete(seed: int = 7) -> np.ndarray:
    """Weathered precast facade panel for the street side."""
    y, x = yy_xx()
    img = fill("#8e8b83")
    img = shade(img, 0.025 * tnoise(T, 16, seed) + 0.03 * tnoise(T, 1.1, seed + 1))
    pores = np.random.default_rng(seed + 2).random((T, T)) > 0.988
    img = mix(img, img * 0.7, pores.astype(np.float64))
    rain = tnoise(T, 2.5, seed + 3)
    rain = np.repeat(rain[:1, :], T, axis=0)
    img = shade(img, -0.035 * np.clip(rain, 0, None))
    # panel joints on two edges -> a 0.5m block grid once tiled
    img = np.where((y >= T - 2)[..., None], img * 0.8, img)
    img = np.where((x <= 1)[..., None], img * 0.84, img)
    return img


def plinth(seed: int = 8) -> np.ndarray:
    img = fill("#5d5a55")
    img = shade(img, 0.07 * tnoise(T, 1.0, seed) + 0.05 * tnoise(T, 9, seed + 1))
    rng = np.random.default_rng(seed + 2)
    spk = rng.random((T, T))
    img = mix(img, img * 1.45, (spk > 0.985).astype(np.float64))
    img = mix(img, img * 0.6, (spk < 0.012).astype(np.float64))
    return img


def wallpaper_damaged(seed: int = 9) -> np.ndarray:
    """Water damage: brown runs from the top of the face, a tide line where
    the damp stopped, and some lifting paper. Columns vary smoothly and wrap,
    so neighbouring damp voxels read as one long stain, not a stamp."""
    img = wallpaper(seed)
    y, x = yy_xx()
    col = tnoise(T, 9, seed + 1)[0]  # one smooth, periodic value per column
    reach = 0.45 + 0.25 * col  # how far down the damp got, 0..1 of the face
    depth = y / T
    wet = np.clip((reach[None, :] - depth) / 0.18, 0, 1)
    runs = np.clip(tnoise(T, 2.0, seed + 2)[0] * 0.8 + 0.2, 0, 1)[None, :]
    wet = wet * (0.55 + 0.45 * runs)
    img = mix(img, img * np.array([0.78, 0.72, 0.52]), wet * 0.75)
    tide = np.exp(-((depth - reach[None, :]) ** 2) / (2 * 0.018 ** 2))
    img = mix(img, img * np.array([0.62, 0.55, 0.38]), tide * 0.7)
    spots = np.clip((tnoise(T, 1.3, seed + 3) - 1.6) * 1.5, 0, 1) * wet
    img = mix(img, img * np.array([0.45, 0.47, 0.32]), spots)
    return img


def void(seed: int = 10) -> np.ndarray:
    img = fill("#060606")
    return shade(img, 0.2 * tnoise(T, 3, seed))


def plaster(seed: int = 11) -> np.ndarray:
    img = fill("#e4e1d8")
    return shade(img, 0.008 * tnoise(T, 12, seed) + 0.01 * tnoise(T, 1.0, seed + 1))


def tiles(seed: int, face: str, grout: str, n: int = 4) -> np.ndarray:
    y, x = yy_xx()
    size = T // n
    img = fill(face)
    rng = np.random.default_rng(seed)
    per = rng.normal(0, 0.015, (n, n))
    img = shade(img, per[(y // size).astype(int), (x // size).astype(int)])
    img = shade(img, 0.012 * tnoise(T, 1.0, seed + 1))
    gx = (x % size)
    gy = (y % size)
    g = (gx <= 1) | (gy <= 1)
    img = np.where(g[..., None], hex_rgb(grout), img)
    # soft sheen on each tile's upper-left
    sheen = np.exp(-(((gx - size * 0.3) ** 2 + (gy - size * 0.3) ** 2) / (2 * (size * 0.35) ** 2)))
    img = np.where(g[..., None], img, img * (1 + 0.035 * sheen[..., None]))
    return img


def roof(seed: int = 14) -> np.ndarray:
    img = fill("#6f6a63")
    pebble = tnoise(T, 1.4, seed)
    img = shade(img, 0.12 * pebble + 0.05 * tnoise(T, 12, seed + 1))
    return img


def glass_swatch() -> np.ndarray:
    img = fill("#9ec9dc")
    y, x = yy_xx()
    img = np.where(((x + y) % 48 < 6)[..., None], img * 1.12, img)
    return img


# texture index -> (name, builder)
SLOTS = {
    1: ("wallpaper", lambda: wallpaper(1)),
    2: ("glass", glass_swatch),  # glass is drawn by its own material; swatch only
    3: ("wallpaper_baseboard", lambda: wallpaper_baseboard(2)),
    4: ("carpet", lambda: carpet(3)),
    5: ("carpet_stained", lambda: carpet_stained(4)),
    6: ("ceiling_tile", lambda: ceiling_tile(5)),
    7: ("ceiling_tile_stained", lambda: ceiling_tile(15, stained=True)),
    8: ("panel_off", lambda: panel_off(6)),
    9: ("concrete", lambda: concrete(7)),
    10: ("plinth", lambda: plinth(8)),
    11: ("wallpaper_damaged", lambda: wallpaper_damaged(9)),
    12: ("void", lambda: void(10)),
    13: ("plaster", lambda: plaster(11)),
    14: ("tile_white", lambda: tiles(12, "#f0f2f1", "#c3c9c7")),
    15: ("tile_aqua", lambda: tiles(13, "#cde6ea", "#9dbcc1")),
    16: ("roof", lambda: roof(14)),
}

TEX = {name: idx for idx, (name, _) in SLOTS.items()}


def cell_of(index: int) -> tuple[int, int]:
    """Top-left pixel of the atlas cell a texture index samples."""
    layer = index % 32
    col = layer % 4
    row = (layer // 4) % 4  # index 16 wraps to row 0
    return col * CELL, row * CELL


def build_atlas() -> tuple[Image.Image, dict[str, np.ndarray]]:
    atlas = np.zeros((ATLAS, ATLAS, 3), dtype=np.float64)
    tiles_out: dict[str, np.ndarray] = {}
    for idx, (name, fn) in SLOTS.items():
        tile = np.clip(fn(), 0, 255)
        tiles_out[name] = tile
        x0, y0 = cell_of(idx)
        # the cell is the tile wrapped around itself, tile exactly in the middle
        big = np.tile(tile, (3, 3, 1))[T - 64:T - 64 + CELL, T - 64:T - 64 + CELL]
        atlas[y0:y0 + CELL, x0:x0 + CELL] = big
    img = Image.fromarray(atlas.round().astype(np.uint8), "RGB")
    return img, tiles_out


def contact_sheet(tiles_out: dict[str, np.ndarray], path: str) -> None:
    names = list(tiles_out.keys())
    cols = 4
    rows = (len(names) + cols - 1) // cols
    pad = 8
    tile_px = 2 * T  # each shown as a 2x2 repeat
    sheet = np.full((rows * (tile_px + pad) + pad, cols * (tile_px + pad) + pad, 3), 32, dtype=np.uint8)
    for i, n in enumerate(names):
        r, c = divmod(i, cols)
        rep = np.tile(np.clip(tiles_out[n], 0, 255), (2, 2, 1)).round().astype(np.uint8)
        y0 = pad + r * (tile_px + pad)
        x0 = pad + c * (tile_px + pad)
        sheet[y0:y0 + tile_px, x0:x0 + tile_px] = rep
    Image.fromarray(sheet).save(path)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    img, tiles_out = build_atlas()
    img.save(os.path.join(OUT, "tileset.png"), optimize=True)
    contact_sheet(tiles_out, os.path.join(OUT, "..", "tileset-contact.png"))
    sizes = {f: os.path.getsize(os.path.join(OUT, f)) for f in ("tileset.png",)}
    print("atlas written", sizes)


if __name__ == "__main__":
    sys.exit(main())
