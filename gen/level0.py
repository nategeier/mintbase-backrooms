"""Mintbase HQ (#1297) + Mintbase Showroom (#1342) as one Backrooms block.

The two parcels are adjacent (HQ z 110..121, Showroom z 121..143, both
x -344..-327) with streets on all four sides, so the build treats them as one
17m x 33m block and cuts the voxel field at the shared line afterwards.

COMBINED voxel coords (0.5m each):
  x 0..33 west -> east   (both parcels are 34 voxels wide)
  z 0..65 south -> north (HQ z 0..21, Showroom z 22..65)
  y 0..23 up             (HQ has 24 layers, the Showroom 12)

Voxels' mesher puts layer y at [0.5y - 0.25, 0.5y + 0.25] m, so the floor
layer y=0 has its walking surface at 0.25m. Player: capsule 1.6m tall, eye
1.65m, autostep 0.6m (0.5m steps climb on their own).

Output: out/1297.json and out/1342.json, each {"content": {...}} in exactly
the shape the parcel edit page's JSON import PUTs to /grid/parcels/:id.
"""

from __future__ import annotations

import base64
import json
import math
import os
import sys
import uuid
import zlib

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from textures import TEX  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "out")

W, D, H = 34, 66, 24
HQ_D, SR_D = 22, 44
HQ_H, SR_H = 24, 12

PARCELS = {
    1297: {"name": "Mintbase HQ", "z0": 0, "depth": HQ_D, "height": HQ_H},
    1342: {"name": "Mintbase Showroom", "z0": HQ_D, "depth": SR_D, "height": SR_H},
}

# ---------------------------------------------------------------- palette
# A tint multiplies the baked light on a voxel. 0 keeps the texture's colour.
PALETTE = [
    "#ffffff",  # 0 neutral
    "#efe6c9",  # 1 aged
    "#d8cdab",  # 2 grimy
    "#a9d9e6",  # 3 glass: water
    "#e2f3fa",  # 4 glass: clear
    "#bcbcbc",  # 5 grey
    "#fff2cc",  # 6 warm
    "#1c1c21",  # 7 dark glass
]
NEUTRAL, AGED, GRIMY, WATER, CLEAR, GREY, WARM, DARKGLASS = range(8)


def opaque(tex: str, tint: int = NEUTRAL) -> int:
    return 0x8000 | (tint << 5) | TEX[tex]


def glass(tint: int = CLEAR) -> int:
    return (tint << 5) | 2


def is_passable(v: int) -> bool:
    return v == 0 or (v & 0xFF) % 32 == 2


# ---------------------------------------------------------------- plan

FLOOR = "."
STAIN = ","
LOBBY_FLOOR = "_"
WALL = "#"
DAMP = "%"
PILLAR = "P"
PLASTER = "W"
DOOR = "d"
ENTRANCE = "="
STOREFRONT = "g"
DESK = "R"
ELEVATOR = "e"
SHELL = "E"
GAP = "o"  # full-height opening, no lintel
COOLER = "c"


class Plan:
    def __init__(self) -> None:
        self.g = [[FLOOR for _ in range(D)] for _ in range(W)]

    def set(self, x: int, z: int, ch: str) -> None:
        if 0 <= x < W and 0 <= z < D:
            self.g[x][z] = ch

    def get(self, x: int, z: int) -> str:
        return self.g[x][z]

    def hline(self, x0: int, x1: int, z: int, ch: str = WALL) -> None:
        for x in range(min(x0, x1), max(x0, x1) + 1):
            self.set(x, z, ch)

    def vline(self, x: int, z0: int, z1: int, ch: str = WALL) -> None:
        for z in range(min(z0, z1), max(z0, z1) + 1):
            self.set(x, z, ch)

    def fill(self, x0: int, z0: int, x1: int, z1: int, ch: str) -> None:
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for z in range(min(z0, z1), max(z0, z1) + 1):
                self.set(x, z, ch)

    def scatter(self, x0: int, z0: int, x1: int, z1: int, ch: str, density: float, seed: int) -> None:
        """Sprinkle `ch` over open floor in a rectangle, never two side by side
        (one stain texture repeated in a block reads as a pattern)."""
        rng = np.random.default_rng(seed)
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for z in range(min(z0, z1), max(z0, z1) + 1):
                if self.get(x, z) != FLOOR or rng.random() > density:
                    continue
                if any(self.get(x + dx, z + dz) == ch for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1),
                                                                     (1, 1), (-1, -1), (1, -1), (-1, 1))
                       if 0 <= x + dx < W and 0 <= z + dz < D):
                    continue
                self.set(x, z, ch)

    def gap_x(self, x0: int, z: int, width: int = 3) -> None:
        for x in range(x0, x0 + width):
            self.set(x, z, GAP)

    def gap_z(self, x: int, z0: int, width: int = 3) -> None:
        for z in range(z0, z0 + width):
            self.set(x, z, GAP)

    def door_x(self, x0: int, z: int, width: int = 2) -> None:
        """Doorway in a wall that runs along x."""
        for x in range(x0, x0 + width):
            self.set(x, z, DOOR)

    def door_z(self, x: int, z0: int, width: int = 2) -> None:
        """Doorway in a wall that runs along z."""
        for z in range(z0, z0 + width):
            self.set(x, z, DOOR)

    def ascii(self) -> str:
        rows = []
        for z in range(D - 1, -1, -1):
            rows.append(f"{z:2d} " + "".join(self.g[x][z] for x in range(W)))
        rows.append("   " + "".join(str(x % 10) for x in range(W)))
        return "\n".join(rows)


STAIR = {"x": (29, 31), "z_first": 3, "steps": 6, "landing": (9, 10), "shaft_ceiling": 13}


def layout() -> tuple[Plan, dict]:
    p = Plan()
    extra: dict = {}

    # --- shell: two voxels thick; the outer ring is the street facade
    for x in range(W):
        for z in range(D):
            if x in (0, W - 1) or z in (0, D - 1):
                p.set(x, z, SHELL)
            elif x in (1, W - 2) or z in (1, D - 2):
                p.set(x, z, WALL)

    # --- HQ lobby (z 2..9, x 10..23): plaster, the one door to the street
    p.fill(10, 2, 23, 9, LOBBY_FLOOR)
    p.vline(9, 1, 10, PLASTER)
    p.vline(24, 1, 10, PLASTER)
    p.hline(9, 24, 10, PLASTER)
    p.hline(10, 23, 1, PLASTER)
    for x in range(15, 19):
        p.set(x, 0, ENTRANCE)
        p.set(x, 1, ENTRANCE)
    for x in (13, 14, 19, 20):
        p.set(x, 0, STOREFRONT)
    p.hline(12, 21, 6, DESK)
    p.vline(9, 4, 5, ELEVATOR)
    p.set(10, 9, COOLER)

    # backrooms side of the lobby walls (each side keeps its own finish)
    p.vline(8, 2, 11)
    p.vline(25, 2, 11)
    p.hline(2, 31, 11)

    # the crack: a jagged hole through both lobby walls (open y ranges)
    extra["crack"] = {
        (19, 10): (1, 2), (20, 10): (1, 4), (21, 10): (1, 4), (22, 10): (2, 3),
        (19, 11): (1, 3), (20, 11): (1, 4), (21, 11): (1, 4), (22, 11): (1, 2),
    }

    # --- HQ west room W1 (x 2..7, z 2..10): a dead end with a doorway into nothing
    p.door_x(2, 11)
    p.scatter(2, 6, 5, 10, STAIN, 0.35, 11)
    extra["void_doors"] = [[(1, 5), (1, 6)]]

    # --- HQ east wing: a 1m passage down to a stair that climbs into the dark
    p.vline(28, 3, 11)
    p.door_x(26, 11)

    # --- the long hallway: x 2..3 from z 12 to z 63, wall at x=4
    p.vline(4, 12, 63)
    for z0 in (14, 25, 41, 57):
        p.door_z(4, z0)
    extra["void_doors"].append([(2, 64), (3, 64)])

    # --- HQ rooms H1 (x 5..16) and H2 (x 18..27), z 12..17
    p.vline(17, 12, 18)
    p.gap_z(17, 13)
    p.hline(5, 31, 18)
    p.door_x(9, 18)
    p.door_x(22, 18)
    p.vline(28, 12, 18)
    p.door_z(28, 15)
    p.scatter(10, 13, 16, 17, STAIN, 0.3, 12)

    # --- band z 19..30: rooms S1 (x 5..14) and S2 (x 16..31)
    p.vline(15, 19, 31)
    p.gap_z(15, 20)
    p.door_z(15, 27)
    p.hline(5, 31, 31)
    p.door_x(7, 31)
    p.gap_x(18, 31, 4)
    p.door_x(28, 31)
    # a wall in S2 that stops for no reason
    p.hline(20, 26, 25)
    p.vline(23, 22, 25)
    # S1's damp closet
    p.hline(5, 10, 26, DAMP)
    p.vline(10, 26, 30, DAMP)
    p.door_z(10, 28)
    p.scatter(5, 27, 9, 30, STAIN, 0.45, 13)

    # --- pillar hall z 32..52, x 5..31
    for px in (9, 15, 21, 27):
        for pz in (35, 41, 47):
            p.fill(px, pz, px + 1, pz + 1, PILLAR)
    p.scatter(12, 40, 22, 46, STAIN, 0.22, 14)

    # one pillar doesn't reach the floor
    extra["floating"] = [(27, 41), (28, 41), (27, 42), (28, 42)]

    # --- north rooms z 54..63
    p.hline(5, 31, 53)
    p.door_x(8, 53)
    p.gap_x(16, 53, 4)
    p.door_x(29, 53)
    p.vline(14, 54, 63)
    p.door_z(14, 58)
    p.vline(22, 54, 63, DAMP)
    p.door_z(22, 56)
    p.scatter(23, 55, 31, 63, STAIN, 0.3, 15)
    extra["void_doors"].append([(18, 64), (19, 64)])
    # a 0.5m crawl hatch into black at the baseboard of the dark room
    extra["hatches"] = [(32, 59)]
    # tiles missing from the drop ceiling
    extra["missing_tiles"] = [(12, 44), (25, 60), (29, 58), (6, 16), (27, 20)]
    # rooftop plant (x0, z0, x1, z1)
    extra["hvac"] = [(7, 29, 10, 33), (22, 47, 25, 49), (4, 14, 6, 16)]

    return p, extra


# ---------------------------------------------------------------- extrusion

# Layer 0 sits under the island's ground plane (the ground draws over its top
# face), so the floor you walk on is layer 1: surface at 0.75m.
FOUNDATION_Y = 0
FLOOR_Y = 1
CEIL_Y = 7    # ceiling tiles: underside at 3.25m -> rooms are 2.5m clear
ROOF_Y = 8    # roof deck: top at 4.25m
PARAPET_Y = 9
DOOR_TOP = FLOOR_Y + 4  # doorways are 2m tall
LINTEL_Y = FLOOR_Y + 5


def extrude(p: Plan, extra: dict) -> np.ndarray:
    f = np.zeros((W, H, D), dtype=np.uint16)

    paper = opaque("wallpaper")
    base = opaque("wallpaper_baseboard")
    damp = opaque("wallpaper_damaged")
    plaster = opaque("plaster")
    plinth = opaque("plinth")
    concrete = opaque("concrete")
    ceiling = opaque("ceiling_tile")
    roof = opaque("roof")
    wall_ys = range(FLOOR_Y + 2, CEIL_Y)  # above the baseboard row

    for x in range(W):
        for z in range(D):
            ch = p.get(x, z)
            f[x, FOUNDATION_Y, z] = plinth

            if ch == SHELL:
                f[x, FLOOR_Y, z] = plinth
                f[x, FLOOR_Y + 1, z] = plinth
                for y in range(FLOOR_Y + 2, PARAPET_Y + 1):
                    f[x, y, z] = concrete
                continue
            if ch == STOREFRONT:
                f[x, FLOOR_Y, z] = plinth
                for y in range(FLOOR_Y + 1, DOOR_TOP + 1):
                    f[x, y, z] = glass(DARKGLASS)
                f[x, LINTEL_Y, z] = plinth
                for y in range(LINTEL_Y + 1, PARAPET_Y + 1):
                    f[x, y, z] = concrete
                continue
            if ch == ENTRANCE and z == 0:
                f[x, FLOOR_Y, z] = plinth  # the step up from the street
                f[x, LINTEL_Y, z] = plinth
                for y in range(LINTEL_Y + 1, PARAPET_Y + 1):
                    f[x, y, z] = concrete
                continue

            if ch in (LOBBY_FLOOR, ENTRANCE, COOLER):
                f[x, FLOOR_Y, z] = opaque("tile_white")
            elif ch == STAIN:
                f[x, FLOOR_Y, z] = opaque("carpet_stained")
            else:
                f[x, FLOOR_Y, z] = opaque("carpet")

            b = FLOOR_Y + 1
            if ch in (WALL, PILLAR):
                f[x, b, z] = base
                for y in wall_ys:
                    f[x, y, z] = paper
            elif ch == DAMP:
                # the damp comes from the ceiling: only the top row is stained
                # (a stain texture on every row would repeat every 0.5m)
                f[x, b, z] = base
                for y in wall_ys:
                    f[x, y, z] = damp if y == CEIL_Y - 1 else paper
            elif ch == PLASTER:
                f[x, b, z] = plinth
                for y in wall_ys:
                    f[x, y, z] = plaster
            elif ch == DOOR:
                f[x, LINTEL_Y, z] = paper
            elif ch == ENTRANCE:
                f[x, LINTEL_Y, z] = plaster
            elif ch == DESK:
                f[x, b, z] = plinth
                f[x, b + 1, z] = opaque("plaster", GREY)
            elif ch == COOLER:
                f[x, b, z] = opaque("plinth", GREY)
                f[x, b + 1, z] = opaque("plaster")
                f[x, b + 2, z] = glass(WATER)
            elif ch == ELEVATOR:
                for y in range(b, DOOR_TOP + 1):
                    f[x, y, z] = opaque("plinth", GREY)
                f[x, LINTEL_Y, z] = plaster

            f[x, CEIL_Y, z] = ceiling
            f[x, ROOF_Y, z] = roof

    for (x, z), (y0, y1) in extra["crack"].items():
        for y in range(y0, y1 + 1):
            f[x, FLOOR_Y + y, z] = 0
    for (x, z) in extra["floating"]:
        f[x, FLOOR_Y + 1, z] = 0
    for (x, z) in extra["hatches"]:
        f[x, FLOOR_Y + 1, z] = opaque("void")
    for (x, z) in extra["missing_tiles"]:
        f[x, CEIL_Y, z] = opaque("void")
    for (x0, z0, x1, z1) in extra["hvac"]:
        for x in range(x0, x1 + 1):
            for z in range(z0, z1 + 1):
                f[x, ROOF_Y + 1, z] = concrete
                f[x, ROOF_Y + 2, z] = plinth if (x in (x0, x1) or z in (z0, z1)) else opaque("roof")
    # parapet coping: a dark band along the top of the facade
    for x in range(W):
        for z in range(D):
            if p.get(x, z) in (SHELL, STOREFRONT) or (p.get(x, z) == ENTRANCE and z == 0):
                f[x, PARAPET_Y, z] = plinth

    # doorways into nothing: 1m x 2m of black in a wall
    for cells in extra["void_doors"]:
        for (x, z) in cells:
            for y in range(FLOOR_Y + 1, DOOR_TOP + 1):
                f[x, y, z] = opaque("void")

    build_stair(f)
    return f


def build_stair(f: np.ndarray) -> None:
    """A 1.5m stair climbing north up into a dark shaft (a penthouse on the
    HQ roof), ending at a black doorway under an EXIT sign."""
    x0, x1 = STAIR["x"]
    zf = STAIR["z_first"]
    n = STAIR["steps"]
    lz0, lz1 = STAIR["landing"]
    top = STAIR["shaft_ceiling"]
    paper = opaque("wallpaper")
    base = opaque("wallpaper_baseboard")
    concrete = opaque("concrete")
    carpet = opaque("carpet")

    zs, zn = zf, lz1 + 1  # shaft's south and north wall rows
    xw, xe = x0 - 1, x1 + 1  # shaft's west and east wall columns
    tread = lambda i: FLOOR_Y + i  # layer of step i's tread

    # carve the air above the step line, up to the shaft ceiling
    for x in range(x0, x1 + 1):
        for z in range(zf + 1, lz1 + 1):
            for y in range(FLOOR_Y + 1, top):
                f[x, y, z] = 0
    # steps: step i at z = zf + i - 1, solid up to its tread
    for i in range(1, n + 1):
        z = zf + i - 1
        for x in range(x0, x1 + 1):
            for y in range(FLOOR_Y + 1, tread(i) + 1):
                f[x, y, z] = carpet if y == tread(i) else base
    for z in range(lz0, lz1 + 1):
        for x in range(x0, x1 + 1):
            for y in range(FLOOR_Y + 1, tread(n) + 1):
                f[x, y, z] = carpet if y == tread(n) else base

    # shaft walls above the Level 0 ceiling, wallpapered (it's still Level 0)
    for y in range(CEIL_Y, top + 1):
        for z in range(zs, zn + 1):
            f[xw, y, z] = paper
            f[xe, y, z] = paper
        for x in range(xw, xe + 1):
            f[x, y, zs] = paper
            f[x, y, zn] = paper
    for y in range(FLOOR_Y + 1, CEIL_Y):
        for x in range(xw, xe + 1):
            f[x, y, zn] = base if y == FLOOR_Y + 1 else paper
    for x in range(x0, x1 + 1):
        for z in range(zs + 1, zn):
            f[x, top, z] = opaque("ceiling_tile")
    # penthouse skin: concrete one voxel outside the shaft walls, roof on top
    for y in range(ROOF_Y + 1, top + 2):
        for z in range(zs - 1, zn + 2):
            f[xw - 1, y, z] = concrete
            f[W - 1, y, z] = concrete
        for x in range(xw - 1, W):
            f[x, y, zs - 1] = concrete
            f[x, y, zn + 1] = concrete
        for z in range(zs, zn + 1):
            if f[xe + 1, y, z] == 0:
                f[xe + 1, y, z] = concrete
    for x in range(xw - 1, W):
        for z in range(zs - 1, zn + 2):
            f[x, top + 1, z] = opaque("roof")
    # the EXIT door at the top: black, 1m wide, 2m tall
    for x in (30, 31):
        for y in range(tread(n) + 1, tread(n) + 5):
            f[x, y, zn] = opaque("void")


# ---------------------------------------------------------------- features

def parcel_of(z: float) -> int:
    return 1297 if z < HQ_D - 0.5 else 1342


def pos(x: float, y: float, z: float) -> tuple[int, list[float]]:
    """Parcel id + parcel-space position for COMBINED voxel coords. Integer
    coords are voxel centres (x=3.0 is the middle of voxel 3); y is in layers
    (layer j's centre is 0.5j metres)."""
    pid = parcel_of(z)
    parcel = PARCELS[pid]
    k = z - parcel["z0"]
    px = -W / 4 + 0.5 + 0.5 * x
    pz = -parcel["depth"] / 4 + 0.5 + 0.5 * k
    return pid, [round(px, 3), round(0.5 * y, 3), round(pz, 3)]


def fid(tag: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "mintbase-backrooms/" + tag))


ASSET_BASE = "https://assets.backrooms.test"


def asset(name: str) -> str:
    return ASSET_BASE.rstrip("/") + "/" + name


LANTERN_COLOR = "#fff6d6"
CEILING_FACE = CEIL_Y - 0.5  # layer coordinate of the ceiling's underside


def lantern(tag: str, x: float, z: float, along: str = "x", strength: int = 70,
            under: float = CEILING_FACE, color: str = LANTERN_COLOR) -> dict:
    """A fluorescent troffer: a flat glowing box hanging just under a ceiling.
    It is also the light source Voxels bakes into the voxels around it (the
    lantern seeds the air voxel its centre sits in)."""
    sx, sz = (2.0, 1.0) if along == "x" else (1.0, 2.0)
    pid, p = pos(x + 0.02, under - 0.06, z + 0.02)
    return {"_parcel": pid, "type": "lantern", "uuid": fid(tag), "position": p,
            "rotation": [0, 0, 0], "scale": [sx, 0.08, sz], "color": color, "strength": strength}


FACING = {"south": 0.0, "north": math.pi, "west": math.pi / 2, "east": -math.pi / 2}


def on_wall(wall_x: float | None, wall_z: float | None, facing: str) -> tuple[float | None, float | None]:
    """Coordinate just in front of a wall voxel's face (3cm proud)."""
    gap = 0.5 + 0.06
    if facing == "south":
        return None, wall_z - gap
    if facing == "north":
        return None, wall_z + gap
    if facing == "west":
        return wall_x - gap, None
    return wall_x + gap, None


def sign(tag: str, text: str, x: float, y: float, z: float, facing: str,
         color: str = "#ff3b2f", background: str = "#140202", width: float | None = None,
         height: float = 0.26, font: int = 64) -> dict:
    """A text plane (Voxels signs render full-bright). `facing` is the side
    the text reads from."""
    pid, p = pos(x, y, z)
    w = width if width is not None else max(0.5, 0.16 * len(text) + 0.2)
    return {"_parcel": pid, "type": "sign", "uuid": fid(tag), "text": text,
            "position": p, "rotation": [0, round(FACING[facing], 4), 0],
            "scale": [round(w, 3), round(height, 3), 0],
            "color": color, "background": background, "fontSize": str(font)}


def light_plan() -> list[dict]:
    L = []
    # HQ lobby (x 10..23, z 2..9)
    L.append(lantern("lobby-1", 13.0, 4.5, strength=60))
    L.append(lantern("lobby-2", 20.0, 4.5, strength=60))
    L.append(lantern("lobby-3", 16.5, 8.5, strength=55))
    # W1: the dead end
    L.append(lantern("w1", 5.0, 5.5, along="z", strength=45))
    # E1 passage + the landing at the top of the stair
    L.append(lantern("e1", 26.5, 6.0, along="z", strength=40))
    L.append(lantern("stair-top", 30.0, 9.5, strength=35, under=STAIR["shaft_ceiling"] - 0.5))
    # H1 / H2 and the corner past H2
    L.append(lantern("h1-a", 8.0, 14.5, strength=65))
    L.append(lantern("h1-b", 13.0, 14.5, strength=65))
    L.append(lantern("h2-a", 21.0, 14.5, strength=65))
    L.append(lantern("h2-b", 25.5, 14.5, strength=65))
    L.append(lantern("hq-east", 30.0, 15.0, along="z", strength=50))
    # hallway + the band at the top of HQ
    L.append(lantern("hall-1", 2.5, 13.5, along="z", strength=60))
    L.append(lantern("hall-2", 2.5, 19.5, along="z", strength=60))
    L.append(lantern("band-hq-a", 10.0, 20.0, strength=60))
    L.append(lantern("band-hq-b", 24.0, 20.0, strength=60))
    # over the street door, outside the facade (lights the facade)
    pid, p = pos(16.52, 6.2, -0.9)
    L.append({"_parcel": pid, "type": "lantern", "uuid": fid("door-light"), "position": p,
              "rotation": [0, 0, 0], "scale": [1.2, 0.1, 0.3], "color": "#fff1c4", "strength": 55})

    # Showroom
    L.append(lantern("hall-3", 2.5, 27.5, along="z", strength=60))
    L.append(lantern("hall-4", 2.5, 35.5, along="z", strength=60))
    L.append(lantern("hall-5", 2.5, 43.5, along="z", strength=60))
    L.append(lantern("hall-6", 2.5, 51.5, along="z", strength=60))
    L.append(lantern("hall-7", 2.5, 59.5, along="z", strength=45))
    L.append(lantern("s1-a", 8.0, 23.5, strength=60))
    L.append(lantern("s1-closet", 7.5, 28.5, strength=30, color="#f4e9b8"))
    L.append(lantern("s2-a", 19.0, 22.5, strength=65))
    L.append(lantern("s2-b", 28.0, 22.5, strength=65))
    L.append(lantern("s2-c", 18.5, 28.5, strength=60))
    L.append(lantern("s2-d", 28.5, 28.5, strength=60))
    for i, (x, z) in enumerate([(12.0, 38.0), (24.0, 38.0), (6.5, 44.0), (18.0, 44.0),
                                (12.0, 50.0), (24.0, 50.0)]):
        L.append(lantern(f"hall-p{i}", x, z, strength=62))
    L.append(lantern("north-a", 9.5, 58.5, strength=55))
    L.append(lantern("north-b", 18.0, 58.5, strength=50))
    L.append(lantern("north-dark", 27.0, 60.0, strength=22, color="#e8e0b0"))
    return L


def hum(tag: str, x: float, z: float, volume: float = 0.35) -> dict:
    """The ballast hum. The feature sits inside a ceiling voxel, so its little
    player sprite is never seen; it starts when you walk into the parcel."""
    pid, p = pos(x, CEIL_Y, z)
    return {"_parcel": pid, "type": "audio", "uuid": fid(tag), "url": asset("hum.wav"),
            "position": p, "rotation": [0, 0, 0], "scale": [0.3, 0.3, 0], "sprite": True,
            "autoplay": True, "loop": True, "volume": volume, "rolloffFactor": 1.4}


def feature_list() -> list[dict]:
    fs = light_plan()

    # hum: quiet in the lobby, everywhere past the crack
    fs.append(hum("hum-lobby", 16.0, 5.0, volume=0.12))
    fs.append(hum("hum-h2", 22.0, 14.0))
    fs.append(hum("hum-w1", 5.0, 6.0))
    fs.append(hum("hum-hall-hq", 2.5, 17.0))
    fs.append(hum("hum-s1", 9.0, 24.0))
    fs.append(hum("hum-pillars", 18.0, 42.0))
    fs.append(hum("hum-hall-sr", 2.5, 48.0))
    fs.append(hum("hum-north", 18.0, 59.0, volume=0.28))

    _, z = on_wall(None, 10, "south")
    fs.append(sign("lobby-name", "MINTBASE", 16.5, 4.9, z, "south",
                   color="#2b2b2b", background="#e6e2d8", width=2.2, height=0.42, font=72))
    fs.append(sign("lobby-level", "RECEPTION - LEVEL 0", 16.5, 4.3, z, "south",
                   color="#6b6b6b", background="#e6e2d8", width=2.2, height=0.18, font=40))
    x, _ = on_wall(9, None, "east")
    fs.append(sign("elevator", "OUT OF ORDER", x, 4.2, 4.5, "east",
                   color="#1b1b1b", background="#f1e36a", width=1.0, height=0.2, font=28))
    _, z = on_wall(None, STAIR["landing"][1] + 1, "south")
    fs.append(sign("exit-stair", "EXIT", 30.5, 12.0, z, "south"))
    _, z = on_wall(None, 64, "south")
    fs.append(sign("exit-hall", "EXIT", 2.5, 6.0, z, "south"))
    fs.append(sign("exit-north", "EXIT", 18.5, 6.0, z, "south"))
    x, _ = on_wall(8, None, "west")
    fs.append(sign("w1-note", "IF YOU CAN READ THIS, YOU NOCLIPPED", x, 4.2, 6.0, "west",
                   color="#3a3420", background="#d8c46c", width=2.2, height=0.14, font=32))
    _, z = on_wall(None, 0, "south")
    fs.append(sign("street-door", "MINTBASE HQ", 16.5, 7.4, z, "south",
                   color="#1f1f1f", background="#d9d4c6", width=2.0, height=0.34, font=64))

    pid, p = pos(16.5, 1.6, -5.0)
    fs.append({"_parcel": pid, "type": "spawn-point", "uuid": fid("spawn"),
               "position": p, "rotation": [0, 0, 0], "scale": [1, 1, 1]})
    return fs


BUDGET = {"lantern": 20, "sign": 100, "spawn-point": 1, "image": 500, "audio": 80}


def split_features() -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {1297: [], 1342: []}
    for f in feature_list():
        out[f.pop("_parcel")].append(f)
    for pid, fs in out.items():
        counts: dict[str, int] = {}
        for f in fs:
            counts[f["type"]] = counts.get(f["type"], 0) + 1
        for t, n in counts.items():
            assert n <= BUDGET.get(t, 0), f"{pid}: {n} {t} over budget {BUDGET.get(t)}"
    return out


# ---------------------------------------------------------------- ceiling detail

def dress_ceiling(f: np.ndarray, feats: dict[int, list[dict]]) -> None:
    """Panel texture over every lit troffer, dead troffers on the same grid
    elsewhere, and a few water-stained tiles."""
    panel = opaque("panel_off")
    stained = opaque("ceiling_tile_stained")
    ceiling = opaque("ceiling_tile")
    lit: list[tuple[int, int]] = []
    for pid, fs in feats.items():
        z0 = PARCELS[pid]["z0"]
        depth = PARCELS[pid]["depth"]
        for ft in fs:
            if ft["type"] != "lantern":
                continue
            px, py, pz = ft["position"]
            vx = (px + W / 4 - 0.5) / 0.5
            vz = (pz + depth / 4 - 0.5) / 0.5 + z0
            vy = py / 0.5
            ceil_layer = int(math.floor(vy)) + 1
            sx, _, sz = ft["scale"]
            xs = [int(math.floor(vx - 0.5)), int(math.floor(vx + 0.5))] if sx > 1.5 else [int(round(vx))]
            zs = [int(math.floor(vz - 0.5)), int(math.floor(vz + 0.5))] if sz > 1.5 else [int(round(vz))]
            for xx in xs:
                for zz in zs:
                    if 0 <= xx < W and 0 <= zz < D and 0 <= ceil_layer < H and f[xx, ceil_layer, zz] == ceiling:
                        f[xx, ceil_layer, zz] = panel
                        lit.append((xx, zz))
    rng = np.random.default_rng(1297)
    for x in range(2, W - 2):
        for z in range(2, D - 2):
            if f[x, CEIL_Y, z] != ceiling or f[x, CEIL_Y - 1, z] != 0:
                continue
            near = min((abs(x - a) + abs(z - b) for a, b in lit), default=99)
            if x % 6 in (2, 3) and z % 8 == 4 and near > 4:
                f[x, CEIL_Y, z] = panel
            elif rng.random() < 0.035:
                f[x, CEIL_Y, z] = stained


# ---------------------------------------------------------------- checks

def check_lanterns(f: np.ndarray, feats: dict[int, list[dict]]) -> None:
    """Each lantern must sit in an air voxel, or Voxels bakes no light for it."""
    for pid, fs in feats.items():
        z0 = PARCELS[pid]["z0"]
        depth = PARCELS[pid]["depth"]
        off = [-W / 4 + 0.25, -0.75, -depth / 4 + 0.25]
        for ft in fs:
            if ft["type"] != "lantern":
                continue
            lx, ly, lz = ft["position"]
            fx = math.floor((lx - off[0] - 0.25) / 0.5)
            fy = math.floor((ly - off[1] - 0.75) / 0.5)
            fz = math.floor((lz - off[2] - 0.25) / 0.5)
            inside = 0 <= fx < W and 0 <= fy < H and 0 <= fz < depth
            v = int(f[fx, fy, fz + z0]) if inside else 0
            assert is_passable(v), f"lantern {ft['uuid']} seeds a solid voxel {(fx, fy, fz + z0)}"


# ---------------------------------------------------------------- export

def encode_field(field: np.ndarray) -> str:
    """[w,h,d] uint16, C order (x slowest) -> base64(zlib(little-endian))."""
    data = np.ascontiguousarray(field.astype("<u2")).tobytes()
    return base64.b64encode(zlib.compress(data, 9)).decode("ascii")


def split_field(f: np.ndarray) -> dict[int, np.ndarray]:
    hq = f[:, :HQ_H, 0:HQ_D]
    sr = f[:, :SR_H, HQ_D:D]
    assert not f[:, SR_H:, HQ_D:D].any(), "Showroom content above its 6m ceiling"
    return {1297: hq, 1342: sr}


def build(asset_base: str) -> dict:
    global ASSET_BASE
    ASSET_BASE = asset_base
    p, extra = layout()
    f = extrude(p, extra)
    feats = split_features()
    dress_ceiling(f, feats)
    check_lanterns(f, feats)
    fields = split_field(f)
    tileset = asset("tileset.png")
    contents = {}
    for pid, field in fields.items():
        contents[pid] = {
            "voxels": encode_field(field),
            "palette": PALETTE,
            "tileset": tileset,
            "features": feats[pid],
            "scripting": False,
            "brightness": 1,
        }
    return {"plan": p, "field": f, "contents": contents, "features": feats}


def main() -> None:
    asset_base = sys.argv[1] if len(sys.argv) > 1 else "https://assets.backrooms.test"
    b = build(asset_base)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "plan.txt"), "w") as fh:
        fh.write(b["plan"].ascii() + "\n")
    np.save(os.path.join(OUT, "combined.npy"), b["field"])
    for pid, c in b["contents"].items():
        path = os.path.join(OUT, f"{pid}.json")
        with open(path, "w") as fh:
            json.dump({"content": c}, fh)
        counts: dict[str, int] = {}
        for ft in c["features"]:
            counts[ft["type"]] = counts.get(ft["type"], 0) + 1
        print(pid, PARCELS[pid]["name"], counts, "bytes", os.path.getsize(path))


if __name__ == "__main__":
    main()
