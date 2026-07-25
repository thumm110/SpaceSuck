"""
build_verdant.py — SpaceSuck planet factory, planet #5: VERDANT
==============================================================
The small jungle world. A tiny, lush, ALIEN forest planet wrapped in unbroken
teal-jade canopy, lit at night by its own biology, and home to the only clean,
thriving, advanced civilisation in the system: ANGEL OAK, a city built at
mid-trunk among colossal trees.

    blender -b -P build_verdant.py

Outputs (written next to this script):
    verdant.glb           — terrain (canopy-topped), the Angel Oak grove, the
                            city, a separate EMISSIVE bioluminescence mesh
    verdant_height.json   — 1280x640 height grid PLUS a 640x320 CANOPY MASK
    verdant_preview_*.png — Cycles renders

==========================================================================
FOUR THINGS THAT ARE DIFFERENT FROM THE OTHER PLANETS — read before editing
==========================================================================

1. THE CANOPY *IS* THE TERRAIN. Instancing a planet's worth of trees would
   blow the GLB apart, so height_field() returns the CANOPY TOP over forest and
   the real forest FLOOR inside carved clearings. Landing in the jungle sets you
   down on the treetops; clearings are the only true ground. Real tree geometry
   exists only where the silhouette has to sell it — the Angel Oak grove and a
   scatter of emergents around the clearings.

2. TOUCHING CANOPY HURTS — SO THE GRID ISN'T ENOUGH. AZURE's water test was free
   because water is flat at exactly one height; canopy height VARIES, so that
   trick does not transfer. Instead this bakes a SECOND array into the same
   json: `canopy_b64`, a 640x320 uint8 mask (0 = clearing/safe, 255 = canopy),
   sampled with the identical lat/lon math the height grid already uses. No
   extra fetch, ~270KB. The game's check at touchdown is one line:
       canopy → hull damage instead of a clean landing latch.
   The SAFE places on VERDANT are carved clearings and the city's pads.

3. BIOLUMINESCENCE REUSES CINDER'S LAVA MESH PATTERN. glTF vertex colours only
   multiply BASE colour and can't drive emission, so the glowing bits are
   extracted into a separate "Glow" object built from the same faces, lifted a
   hair off the surface, with emissive materials. And the same caveat applies:
   the bundled GLTFLoader does NOT support KHR_materials_emissive_strength, so
   in-game emission is exactly emissiveFactor at intensity 1 — get brightness
   from the COLOR, not the strength number.

4. VERDANT IS TINY — 675u in game, the smallest body in the system. The GLB is
   still modelled at R=100 and the game scales by cfg.radius/100, so the scale
   factor is 6.75 (vs CINDER's 9, AZURE's 14.25, RUBICON's 32). MS re-normalises
   STRUCTURE sizes so a city building is the same physical size as one at
   RustHollow. Planet-relative things (canopy depth, clearing radii, noise
   frequency) are NOT multiplied by MS.
"""

import bpy
import json
import base64
import math
import os
import random
import numpy as np
from mathutils import Vector, Matrix

# ---------------------------------------------------------------- CONFIG --
R       = 100.0     # base radius in Blender units — MUST stay 100
SUBDIV  = 7         # 20 * 4^(n-1) → 81,920 tris
SEED    = 99        # matches VERDANT's seed in the game's BODIES config

GAME_R  = 675.0     # VERDANT's cfg.radius — the smallest world in the system
SCALE   = GAME_R / R                    # 6.75
MS      = 32.0 / SCALE                  # ≈ 4.741 — structure size normalizer

def gu(bu):
    """Blender units → game units, for printing sanity checks"""
    return bu * SCALE

# --- the forest ---------------------------------------------------------
# Canopy depth as a surface multiplier. 0.030 → ~20 game units of leaf layer
# over the forest floor. Kept WELL under the hero trees so the Angel Oak grove
# visibly towers over the general canopy instead of merging into it.
CANOPY_D    = 0.030
CANOPY_VAR  = 0.012   # how much the canopy top rolls
GLOW_LIFT   = 0.04    # BU the bioluminescence mesh floats off the terrain

# --- the city -----------------------------------------------------------
# ANGEL OAK — named for the real ~400-year-old live oak on Johns Island, SC.
# The city is NOT in a clearing: it sits among the trunks, so the canopy hazard
# applies right up to the platform edge. The pads are the only safe ground, and
# groundRadius() checks pads BEFORE the grid, so they exclude themselves.
CITY_LAT, CITY_LON = 12.0, -28.0
CITY_ANG   = 0.165    # the grove's footprint in radians
PLAT_H     = 0.044    # platform height above local ground → ~30 game units
PLAT_R     = 1.55     # platform radius in Blender units → ~10.5 game units

# Pad placement. v1 put these at CITY_ANG * 0.92 — OUTSIDE the grove ring — so
# each platform sat stranded on open ground instead of nestled among trunks.
# Pulled well inside, and then ringed with their own trees below.
PAD_BEARINGS = (0.55, 0.55 + math.pi)
# 0.72, not 0.60: at 0.60 a pad sits only 0.027 rad clear of the protected
# light-ring annulus, so every tree ring on the CITY-FACING side fell inside it
# and got rejected — 82 of 108 ring trees vanished and the platforms were bare
# on their inner flank. 0.72 buys room for the inner rings to close all the way
# around. The outermost rings are still clipped on the plaza side, which is
# correct: that's where the walkway approach comes in.
PAD_RAD      = CITY_ANG * 0.72

OAK_H      = 13.0     # THE ANGEL OAK's trunk height in BU → ~88 game units
GROVE_H    = 8.6      # grove tree height in BU → ~58 game units

# --- clearings (the SAFE ground) ----------------------------------------
# Carved through height_field, so the collision grid knows about them and the
# canopy mask reads 0 inside them. Two named ones plus a scatter, so "find the
# clearings" is a real navigation problem on a world that looks the same
# everywhere.
# Sizing note: v1 ran 9 small scatter clearings and came out 98.3% canopy —
# 1.7% safe ground on a world where you're supposed to hunt for somewhere to
# set down. That isn't "find the clearing", that's "there is no clearing".
# Landing costs hull, not your ship, so the loop only works if a glade is
# findable within a reasonable sweep.
CLEARINGS = [
    {"name": "Johns",   "lat": -22.0, "lon": 48.0,  "ang": 0.125},
    {"name": "Cypress", "lat":  40.0, "lon": 140.0, "ang": 0.110},
]
SCATTER_CLEARINGS = 26

# --- districts (painted only — lit ground under the city) ---------------
DISTRICTS = [("Wadmalaw", 0.052, 1.15), ("Bohicket", 0.048, -1.55)]

# --- palette ------------------------------------------------------------
PAL = {
    # canopy — teal-jade, NOT Earth green. VERDANT sits in the same system as an
    # actual Earth; leaf-green would just read as "Earth again, but smaller".
    "canopy":   0x2e6b52,
    "canopyHi": 0x4d9c7c,   # sunlit crowns
    "canopyDk": 0x1a4133,   # shaded understorey showing through gaps
    "bloomM":   0xa8459c,   # magenta flowering stands
    "bloomA":   0xd9a441,   # amber flowering stands
    # ground (only visible in clearings + on ridges)
    "floor":    0x6b6248,   # forest floor / clearing dirt
    "floorDk":  0x4a442f,
    "rock":     0x5d5a55,   # exposed ridge rock
    "rockHi":   0x827d74,
    "river":    0x1d3f4a,   # river courses
    "sand":     0xa8996d,   # river banks
    # bioluminescence — brightness comes from COLOUR (see header note 3)
    "glowCyan": 0x6afff0,
    "glowViol": 0xc07cff,
    "glowRiv":  0x46d6ff,
    # the city — white ceramic and glass. Every other settlement in the system
    # is a rusty box; this is the one place that isn't.
    "ceramic":  0xe9ece7,
    "ceramicS": 0xc8cfc9,   # shadowed ceramic
    "glass":    0x9fd8d0,
    "trim":     0x7f8b86,
    "deck":     0xd6dad4,   # platform decking
    "cityLite": 0xffe9b0,   # warm window light
    "guide":    0x66ffd5,   # landing guidance light
    "beacon":   0xff5f5f,
    # trees
    "bark":     0x4a3f33,
    "barkHi":   0x60513f,
    "crown":    0x2a6349,
    "crownHi":  0x3f8b64,
}

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT  = os.path.join(ROOT, "planets")
os.makedirs(os.path.join(OUT, "previews"), exist_ok=True)


# ---------------------------------------------------- NOISE (numpy, fast) --
def _hash3(ix, iy, iz, seed):
    x = ix.astype(np.uint32) * np.uint32(374761393)
    x += iy.astype(np.uint32) * np.uint32(668265263)
    x += iz.astype(np.uint32) * np.uint32(3266489917)
    x += np.uint32(seed) * np.uint32(2654435761)
    x ^= x >> np.uint32(13)
    x *= np.uint32(1274126177)
    x ^= x >> np.uint32(16)
    return (x & np.uint32(0xFFFF)).astype(np.float64) / 65535.0

def vnoise(p, seed):
    i = np.floor(p).astype(np.int64)
    f = p - i
    u = f * f * (3.0 - 2.0 * f)
    ix, iy, iz = i[:, 0], i[:, 1], i[:, 2]
    ux, uy, uz = u[:, 0], u[:, 1], u[:, 2]
    c = lambda dx, dy, dz: _hash3(ix + dx, iy + dy, iz + dz, seed)
    x00 = c(0,0,0) + (c(1,0,0) - c(0,0,0)) * ux
    x10 = c(0,1,0) + (c(1,1,0) - c(0,1,0)) * ux
    x01 = c(0,0,1) + (c(1,0,1) - c(0,0,1)) * ux
    x11 = c(0,1,1) + (c(1,1,1) - c(0,1,1)) * ux
    y0 = x00 + (x10 - x00) * uy
    y1 = x01 + (x11 - x01) * uy
    return y0 + (y1 - y0) * uz

def fbm(p, octaves, seed):
    total, amp, freq, norm = 0.0, 0.5, 1.0, 0.0
    for o in range(octaves):
        total = total + vnoise(p * freq + o * 19.19, seed + o) * amp
        norm += amp
        amp *= 0.5
        freq *= 2.0
    return total / norm

def snoise(p, octaves, seed):
    """fbm remapped to roughly [-1, 1].

    Plain fbm() does NOT span [0,1] — it clusters around 0.5 with a typical
    spread of only about ±0.12, so `(fbm - 0.5) * A` swings around A/8, not A.
    That cost a whole iteration on AZURE (see PLANET_CHECKLIST). Use this
    wherever the amplitude is supposed to MEAN something."""
    return np.clip((fbm(p, octaves, seed) - 0.5) * 4.0, -1.0, 1.0)

def ridged(p, octaves, seed):
    """sharp folded ridges. NOTE (from CINDER): this sits MOSTLY NEAR 1, not
    near 0 — threshold high (~0.95+) if you want thin features."""
    n = fbm(p, octaves, seed)
    return (1.0 - np.abs(2.0 * n - 1.0)) ** 2

def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)

def ll_dir(lat, lon):
    la, lo = math.radians(lat), math.radians(lon)
    return np.array([math.cos(la) * math.cos(lo),
                     math.cos(la) * math.sin(lo),
                     math.sin(la)])

def tangents(d):
    up = np.array([0.0, 0.0, 1.0])
    if abs(float(d @ up)) > 0.94:
        up = np.array([1.0, 0.0, 0.0])
    t1 = np.cross(d, up); t1 /= np.linalg.norm(t1)
    t2 = np.cross(d, t1)
    return t1, t2

def step_along(d, fwd, ang):
    v = d * math.cos(ang) + fwd * math.sin(ang)
    return v / np.linalg.norm(v)

CITY_DIR = ll_dir(CITY_LAT, CITY_LON)
CITY_T1, CITY_T2 = tangents(CITY_DIR)
for _c in CLEARINGS:
    _c["dir"] = ll_dir(_c["lat"], _c["lon"])

# scatter more clearings, kept off the city and off each other
_crng = random.Random(SEED + 210)
while len(CLEARINGS) < 2 + SCATTER_CLEARINGS:
    d = ll_dir(math.degrees(math.asin(_crng.uniform(-0.90, 0.90))),
               _crng.uniform(-180, 180))
    if float(d @ CITY_DIR) > math.cos(CITY_ANG * 2.4):
        continue
    if any(float(d @ c["dir"]) > math.cos(0.17) for c in CLEARINGS):
        continue
    CLEARINGS.append({"name": None, "dir": d,
                      "ang": _crng.uniform(0.055, 0.115)})
print(f"clearings: {len(CLEARINGS)} "
      f"({sum(1 for c in CLEARINGS if c['name'])} named)")

# rivers: great-circle arcs carved through the height field, and the brightest
# bioluminescence on the planet runs along them
_rrng = random.Random(SEED + 330)
RIVERS = []
while len(RIVERS) < 7:
    a = ll_dir(math.degrees(math.asin(_rrng.uniform(-0.85, 0.85))),
               _rrng.uniform(-180, 180))
    b = ll_dir(math.degrees(math.asin(_rrng.uniform(-0.85, 0.85))),
               _rrng.uniform(-180, 180))
    if float(a @ b) > 0.5 or float(a @ b) < -0.5:
        continue                       # want a decent-length arc, not a loop
    RIVERS.append((a, b))


# ------------------------------------------------------- THE HEIGHT FIELD --
# Returns the CANOPY TOP over forest and the real FLOOR inside clearings.
# See header notes 1 and 2.

def height_field(dirs, flatten=True, canopy=True):
    z = dirs[:, 2]

    # ---- forest floor: rolling hills, modest relief. VERDANT is small, so the
    # limb is tight and big amplitude would read as a lumpy potato.
    floor = snoise(dirs * 3.0 + 1.7, 5, SEED + 3) * 0.016
    floor += snoise(dirs * 7.5 + 5.2, 4, SEED + 11) * 0.007
    # a few ridge spines where rock breaks through the forest
    ridge = ridged(dirs * 4.2 + 2.8, 4, SEED + 19)
    ridge_m = smoothstep(0.90, 0.99, ridge)
    floor += ridge_m * 0.020

    # ---- RIVERS carved into the floor. Done on the FLOOR (before canopy) so
    # the canopy opens over the water the way it actually does.
    river = np.zeros(len(dirs))
    for A, B in RIVERS:
        N = np.cross(A, B); N = N / np.linalg.norm(N)
        mid = A + B; mid = mid / np.linalg.norm(mid)
        half = math.acos(float(np.clip(A @ B, -1.0, 1.0))) * 0.5
        perp = np.abs(dirs @ N)
        along = np.arccos(np.clip(dirs @ mid, -1.0, 1.0))
        # wander the course so it isn't a ruler-straight line
        perp = perp + snoise(dirs * 14.0 + 9.1, 3, SEED + 27) * 0.010
        band = (np.exp(-(perp / 0.010) ** 2)
                * (1.0 - smoothstep(half * 0.85, half * 1.05, along)))
        river = np.maximum(river, band)
    floor -= river * 0.010

    ground = 1.0 + floor

    # ---- CLEARINGS: where the canopy is absent. `clear` is 1 inside a
    # clearing, 0 under closed forest — it drives BOTH the canopy depth and the
    # exported hazard mask, so what you see is exactly what the game tests.
    clear = np.zeros(len(dirs))
    # The grove is one of them. The city sits among colossal TRUNKS, so the
    # general canopy has to be open here or you'd never see the trees or the
    # city under them — and trunks planted at ground level would be buried
    # inside a surface flattened at canopy height. That also makes the grove
    # floor SAFE ground, which is consistent with "clearings are safe": the
    # hazard on this planet is the closed canopy OUTSIDE the grove. Threading
    # between 88-unit trunks is the challenge here, not the hull damage.
    _acity = np.arccos(np.clip(dirs @ CITY_DIR, -1.0, 1.0))
    clear = np.maximum(clear,
                       1.0 - smoothstep(CITY_ANG * 0.80, CITY_ANG * 1.15, _acity))
    for c in CLEARINGS:
        ac = np.arccos(np.clip(dirs @ c["dir"], -1.0, 1.0))
        # ragged edges — a clearing with a clean circular border reads as a
        # crop circle, and on a coarse mesh it would staircase into a polygon
        # exactly the way AZURE's atoll did
        cr = c["ang"] * (1.0 + snoise(dirs * 18.0 + 4.4, 3, SEED + 31) * 0.28)
        clear = np.maximum(clear, 1.0 - smoothstep(cr * 0.70, cr, ac))
    # rivers punch the canopy open too
    clear = np.maximum(clear, smoothstep(0.35, 0.85, river))

    # ---- CANOPY: thickness rolls, thins on exposed ridges, gone in clearings
    can = CANOPY_D + snoise(dirs * 9.0 + 6.3, 4, SEED + 43) * CANOPY_VAR
    can = can * (1.0 - clear) * (1.0 - ridge_m * 0.55)
    can = np.maximum(can, 0.0)

    m = ground + (can if canopy else 0.0)

    # ---- level the grove floor so every trunk and platform footing starts
    # from the same plane. Done last so the city always wins.
    if flatten:
        t = 1.0 - smoothstep(CITY_ANG * 0.55, CITY_ANG * 1.20, _acity)
        m = m * (1.0 - t) + CITY_GROUND * t

    return m, {"floor": floor, "ground": ground, "canopy": can, "clear": clear,
               "river": river, "ridge": ridge_m, "z": z}

# CITY_GROUND has to be resolved before any flatten=True call reads it.
CITY_GROUND = 1.0
_gm, _ = height_field(CITY_DIR[None, :], flatten=False, canopy=False)
CITY_GROUND = float(_gm[0])
print(f"  Angel Oak grove floor → {CITY_GROUND:.5f}")
print(f"  platform deck → {CITY_GROUND + PLAT_H:.5f} "
      f"({gu(PLAT_H * R):.1f} game units above the grove floor)")


# ------------------------------------------------------------- COLOR PASS --
def hex_rgb(h):
    return np.array([(h >> 16 & 255) / 255.0, (h >> 8 & 255) / 255.0, (h & 255) / 255.0])

def lerp_col(a, b, t):
    t = t[:, None]
    return a[None, :] * (1 - t) + b[None, :] * t

def tint(base, color, t):
    t = t[:, None]
    return base * (1 - t) + color[None, :] * t

def glow_field(dirs, aux):
    """Where the planet lights itself up at night. Returns 0..1 per face.
    Two sources: flowering bloom stands in the canopy, and the rivers.

    Bloom stands must be BIG and CONNECTED. v1 thresholded the top tail of a
    high-frequency fbm, which picks out scattered single faces — from orbit it
    read as magenta and cyan glitch triangles sprayed over the planet, not as
    glowing groves. Low frequency plus properly-scaled snoise gives a handful
    of large patches instead."""
    bcl   = snoise(dirs * 5.0 + 3.9, 3, SEED + 61)
    bloom = smoothstep(0.58, 0.92, bcl)
    bloom = bloom * (1.0 - aux["clear"]) * (aux["canopy"] > 0.004)
    rivg  = smoothstep(0.30, 0.80, aux["river"])
    return np.clip(np.maximum(bloom * 0.90, rivg), 0.0, 1.0), bloom, rivg

def face_colors(dirs, aux):
    clear, can, river = aux["clear"], aux["canopy"], aux["river"]
    floor, ridge, z = aux["floor"], aux["ridge"], aux["z"]

    # ---- base: the forest floor / clearing ground
    ft = np.clip((floor + 0.02) / 0.05, 0.0, 1.0)
    col = lerp_col(hex_rgb(PAL["floorDk"]), hex_rgb(PAL["floor"]),
                   smoothstep(0.15, 0.65, ft))
    col = tint(col, hex_rgb(PAL["rock"]),   ridge * 0.75)
    col = tint(col, hex_rgb(PAL["rockHi"]), ridge * smoothstep(0.6, 1.0, ft) * 0.5)

    # ---- CANOPY on top of it. Where there's leaf, you see leaf.
    cmask = smoothstep(0.002, 0.014, can)
    canopy_col = lerp_col(hex_rgb(PAL["canopyDk"]), hex_rgb(PAL["canopy"]),
                          smoothstep(0.30, 0.75, fbm(dirs * 16.0 + 2.1, 4, SEED + 51)))
    canopy_col = tint(canopy_col, hex_rgb(PAL["canopyHi"]),
                      smoothstep(0.58, 0.88, fbm(dirs * 26.0 + 7.7, 3, SEED + 57)) * 0.7)
    # flowering stands — the alien part of the alien flora
    bm = smoothstep(0.62, 0.86, fbm(dirs * 13.0 + 11.3, 4, SEED + 63))
    ba = smoothstep(0.64, 0.88, fbm(dirs * 15.0 + 21.9, 4, SEED + 67))
    canopy_col = tint(canopy_col, hex_rgb(PAL["bloomM"]), bm * 0.55)
    canopy_col = tint(canopy_col, hex_rgb(PAL["bloomA"]), ba * 0.42)
    col = col * (1 - cmask)[:, None] + canopy_col * cmask[:, None]

    # ---- rivers and their banks, painted over everything
    col = tint(col, hex_rgb(PAL["sand"]),  smoothstep(0.10, 0.45, river) * 0.55)
    col = tint(col, hex_rgb(PAL["river"]), smoothstep(0.45, 0.85, river) * 0.90)

    # ---- clearing floors read warmer and drier than the shaded forest floor
    col = tint(col, hex_rgb(PAL["floor"]),
               clear * (1.0 - smoothstep(0.4, 0.9, river)) * 0.45)

    # ---- the city's lit ground districts under the grove
    for _name, dang, daz in DISTRICTS:
        dd = step_along(CITY_DIR, CITY_T1 * math.cos(daz) + CITY_T2 * math.sin(daz),
                        dang)
        ad = np.arccos(np.clip(dirs @ dd, -1.0, 1.0))
        col = tint(col, hex_rgb(PAL["ceramicS"]),
                   (1.0 - smoothstep(dang * 0.35, dang * 0.95, ad)) * 0.55)

    # ---- poles: colder, sparser forest
    col = tint(col, hex_rgb(PAL["canopyDk"]), smoothstep(0.86, 0.99, np.abs(z)) * 0.55)

    # per-face brightness jitter, keyed to DIRECTION not face index (see AZURE:
    # index-keyed jitter outlines any mesh whose face density differs)
    col *= (1.0 + snoise(dirs * 150.0 + 31.0, 1, SEED + 5)[:, None] * 0.055)
    return np.clip(np.concatenate([col, np.ones((len(dirs), 1))], axis=1), 0.0, 1.0)


# ------------------------------------------------------------ SCENE SETUP --
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

def make_material(name, color_hex=None, emission_hex=None, strength=0.0,
                  vertex_colors=False, roughness=0.9):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = roughness
    if vertex_colors:
        vc = mat.node_tree.nodes.new("ShaderNodeVertexColor")
        vc.layer_name = "Col"
        mat.node_tree.links.new(vc.outputs["Color"], bsdf.inputs["Base Color"])
    elif color_hex is not None:
        c = hex_rgb(color_hex)
        bsdf.inputs["Base Color"].default_value = (*c, 1.0)
    if emission_hex is not None:
        e = hex_rgb(emission_hex)
        for cname, sname in (("Emission Color", "Emission Strength"),
                             ("Emission", "Emission Strength")):
            if cname in bsdf.inputs:
                bsdf.inputs[cname].default_value = (*e, 1.0)
                if sname in bsdf.inputs:
                    bsdf.inputs[sname].default_value = strength
                break
    return mat


# --------------------------------------------------------------- TERRAIN --
print("growing the forest…")
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=SUBDIV, radius=R)
planet = bpy.context.active_object
planet.name = "Verdant"
me = planet.data

nv = len(me.vertices)
co = np.empty(nv * 3)
me.vertices.foreach_get("co", co)
co = co.reshape(-1, 3)
dirs = co / np.linalg.norm(co, axis=1)[:, None]

vm, _ = height_field(dirs)
vpos = dirs * (R * vm)[:, None]
me.vertices.foreach_set("co", vpos.ravel())
me.update()

nf = len(me.polygons)
centers = np.empty(nf * 3)
me.polygons.foreach_get("center", centers)
centers = centers.reshape(-1, 3)
fdirs = centers / np.linalg.norm(centers, axis=1)[:, None]
fm, faux = height_field(fdirs)
cols = face_colors(fdirs, faux)

_canopy_frac = 100.0 * float((faux["canopy"] > 0.004).sum()) / nf
print(f"  canopy covers {_canopy_frac:.1f}% of the surface "
      f"({100.0 - _canopy_frac:.1f}% is safe ground)")

attr = me.color_attributes.new(name="Col", type='FLOAT_COLOR', domain='CORNER')
attr.data.foreach_set("color", np.repeat(cols, 3, axis=0).ravel())

bpy.ops.object.shade_flat()
terrain_mat = make_material("Terrain", vertex_colors=True, roughness=0.80)
me.materials.append(terrain_mat)


# ------------------------------------------------- BIOLUMINESCENCE MESH --
# Same extraction pattern as CINDER's lava: pull the glowing faces into their
# own object with emissive materials, lifted off the surface so it can't
# z-fight the terrain it was cut from. Brightness comes from the COLOUR — the
# game's GLTFLoader ignores KHR_materials_emissive_strength (header note 3).
print("lighting the bioluminescence…")
gtot, gbloom, griv = glow_field(fdirs, faux)
sel = np.where(gtot > 0.35)[0]
print(f"  {len(sel)} glowing faces of {nf} ({100.0 * len(sel) / nf:.1f}%)")

pv = np.empty(nf * 3, dtype=np.int32)   # Blender int props are int32
me.polygons.foreach_get("vertices", pv)
gtris = pv.reshape(-1, 3)[sel]
used = np.unique(gtris)
remap = np.full(nv, -1, dtype=np.int64)
remap[used] = np.arange(len(used))
new_tris = remap[gtris]
gverts = dirs[used] * (R * vm[used] + GLOW_LIFT)[:, None]

gmesh = bpy.data.meshes.new("GlowMesh")
gmesh.from_pydata(gverts.tolist(), [], new_tris.tolist())
gmesh.update()
glow_obj = bpy.data.objects.new("Glow", gmesh)
bpy.context.collection.objects.link(glow_obj)

# BASE colour stays near-black while EMISSION carries the colour: setting both
# double-counts (lit base + emission) and clips the bright faces to flat white
# on the day side. Dark base = the emissive colour is what you see, day OR night.
for m_ in (make_material("GlowRiver", color_hex=0x04161c,
                         emission_hex=PAL["glowRiv"],  strength=1.0, roughness=0.5),
           make_material("GlowCyan",  color_hex=0x04170f,
                         emission_hex=PAL["glowCyan"], strength=1.0, roughness=0.6),
           make_material("GlowViolet", color_hex=0x11061a,
                         emission_hex=PAL["glowViol"], strength=1.0, roughness=0.6)):
    gmesh.materials.append(m_)

# Colour is picked by a LOW-frequency field so a whole stand glows one colour.
# v2 keyed it to a high-frequency hash and adjacent faces flipped cyan/violet,
# which read as speckled noise rather than a grove of one flowering species.
_rs, _bs = griv[sel], gbloom[sel]
_species = snoise(fdirs[sel] * 3.0 + 3.3, 2, SEED + 71)
midx = np.where(_rs > 0.30, 0, np.where(_species > 0.0, 2, 1)).astype(np.int32)
gmesh.polygons.foreach_set("material_index", midx)
gmesh.update()

bpy.ops.object.select_all(action='DESELECT')
bpy.context.view_layer.objects.active = glow_obj
glow_obj.select_set(True)
bpy.ops.object.shade_flat()
glow_obj.select_set(False)


# ------------------------------------------------------ STRUCTURE HELPERS --
def surf_quat(d, fwd):
    z = d.normalized()
    x = (fwd - z * fwd.dot(z)).normalized()
    y = z.cross(x)
    return Matrix((x, y, z)).transposed().to_quaternion()

def _box(base_pt, rot, off, scale, mat, objs):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=base_pt + rot @ Vector(off))
    b = bpy.context.active_object
    b.scale = Vector(scale)
    b.rotation_mode = 'QUATERNION'; b.rotation_quaternion = rot
    b.data.materials.append(mat); objs.append(b); return b

def _cyl(base_pt, rot, off, radius, height, mat, objs, verts=10):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=radius, depth=height,
                                        location=base_pt + rot @ Vector(off))
    b = bpy.context.active_object
    b.rotation_mode = 'QUATERNION'; b.rotation_quaternion = rot
    b.data.materials.append(mat); objs.append(b); return b

def _cone(base_pt, rot, off, r1, r2, depth, mat, objs, verts=12):
    bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r1, radius2=r2,
                                    depth=depth,
                                    location=base_pt + rot @ Vector(off))
    b = bpy.context.active_object
    b.rotation_mode = 'QUATERNION'; b.rotation_quaternion = rot
    b.data.materials.append(mat); objs.append(b); return b

def _ico(base_pt, rot, off, scale, mat, objs, subd=2):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=subd, radius=1.0,
                                          location=base_pt + rot @ Vector(off))
    b = bpy.context.active_object
    b.scale = Vector(scale)
    b.rotation_mode = 'QUATERNION'; b.rotation_quaternion = rot
    b.data.materials.append(mat); objs.append(b); return b

def _torus(base_pt, rot, off, major, minor, mat, objs, mseg=20, nseg=6):
    bpy.ops.mesh.primitive_torus_add(location=base_pt + rot @ Vector(off),
                                     major_radius=major, minor_radius=minor,
                                     major_segments=mseg, minor_segments=nseg)
    b = bpy.context.active_object
    b.rotation_mode = 'QUATERNION'; b.rotation_quaternion = rot
    b.data.materials.append(mat); objs.append(b); return b

def join_as(objs, name):
    objs = [o for o in objs if o is not None]
    if not objs:
        return None
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1:
        bpy.ops.object.join()
    j = bpy.context.active_object
    j.name = name
    bpy.ops.object.shade_flat()
    bpy.ops.object.select_all(action='DESELECT')
    return j

bark_m    = make_material("Bark",     color_hex=PAL["bark"],     roughness=0.98)
barkHi_m  = make_material("BarkHi",   color_hex=PAL["barkHi"],   roughness=0.95)
crown_m   = make_material("Crown",    color_hex=PAL["crown"],    roughness=0.92)
crownHi_m = make_material("CrownHi",  color_hex=PAL["crownHi"],  roughness=0.90)
cer_m     = make_material("Ceramic",  color_hex=PAL["ceramic"],  roughness=0.35)
cerS_m    = make_material("CeramicS", color_hex=PAL["ceramicS"], roughness=0.45)
glass_m   = make_material("Glass",    color_hex=PAL["glass"],    roughness=0.12)
trim_m    = make_material("Trim",     color_hex=PAL["trim"],     roughness=0.40)
deck_m    = make_material("Deck",     color_hex=PAL["deck"],     roughness=0.55)
lite_m    = make_material("CityLite", color_hex=PAL["cityLite"],
                          emission_hex=PAL["cityLite"], strength=3.0)
guide_m   = make_material("Guide",    color_hex=PAL["guide"],
                          emission_hex=PAL["guide"], strength=3.5)
beacon_m  = make_material("Beacon",   color_hex=PAL["beacon"],
                          emission_hex=PAL["beacon"], strength=3.2)


# ------------------------------------------------------------- THE TREES --
def make_tree(base_pt, rot, height, trunk_r, rng, objs, hero=False, detail=1):
    """A tree: tapered trunk, a few boughs, a cluster of crown blobs.
    These exist to sell the silhouette, not to be botany — the general canopy
    is TERRAIN (header note 1), not geometry.

    `detail` is a poly budget, because there are now ~250 of these:
        2 / hero — subdiv-2 main crown, 5 boughs      (~700 tris)
        1        — subdiv-1 main crown, 3 boughs      (~410 tris)
        0        — subdiv-1 main crown, 2 boughs      (~310 tris)
    Background trees at detail 0 read identically past a few hundred units and
    cost less than half as much."""
    csub = 2 if hero else 1
    _cone(base_pt, rot, (0, 0, height * 0.5), trunk_r, trunk_r * 0.42, height,
          bark_m, objs, verts=8 if detail else 6)
    # buttress flare at the base — what makes a big tree read as OLD
    _cone(base_pt, rot, (0, 0, height * 0.055), trunk_r * 1.85, trunk_r,
          height * 0.11, barkHi_m, objs, verts=8)
    # Foliage sits HIGH and stays SMALL. v1 hung crowns of radius ~3.5 BU from
    # 0.55 of trunk height, and since the city deck is at 4.4 BU they drooped
    # straight over the whole town — from above, Angel Oak was a mat of green
    # balls with one guidance ring peeking out. Keep the canopy above the deck
    # and let daylight down between the trunks.
    nb = 5 if hero else (3 if detail >= 1 else 2)
    for bi in range(nb):
        a = rng.uniform(0, 2 * math.pi)
        el = rng.uniform(0.72, 0.92)
        bl = height * rng.uniform(0.22, 0.34) * (1.25 if hero else 1.0)
        bq = rot @ Matrix.Rotation(a, 4, 'Z').to_quaternion() \
                 @ Matrix.Rotation(rng.uniform(0.9, 1.25), 4, 'Y').to_quaternion()
        bough = _cone(base_pt, rot, (0, 0, height * el), trunk_r * 0.34,
                      trunk_r * 0.12, bl, bark_m, objs, verts=6)
        bough.rotation_quaternion = bq
        # crown blob out at the end of the bough
        ex = math.sin(rng.uniform(0.85, 1.15)) * bl * 0.55
        _ico(base_pt, rot,
             (math.cos(a) * ex, math.sin(a) * ex, height * (el + 0.14)),
             (bl * rng.uniform(0.30, 0.42), bl * rng.uniform(0.30, 0.42),
              bl * rng.uniform(0.16, 0.24)),
             crown_m if rng.random() < 0.6 else crownHi_m, objs, subd=1)
    # the main crown mass
    _ico(base_pt, rot, (0, 0, height * 1.08),
         (height * (0.26 if hero else 0.21), height * (0.26 if hero else 0.21),
          height * 0.12), crownHi_m, objs, subd=csub)

cd = Vector(CITY_DIR.tolist())
ct1 = Vector(CITY_T1.tolist())
ct2 = Vector(CITY_T2.tolist())
grove_ground = R * CITY_GROUND
grove = []
trng = random.Random(SEED + 808)

# --- pad directions, needed by the tree layout AND the city section. Computed
# once so the two can't drift apart.
PAD_DIRS = [step_along(CITY_DIR,
                       CITY_T1 * math.cos(pa) + CITY_T2 * math.sin(pa), PAD_RAD)
            for pa in PAD_BEARINGS]

# =========================================================================
# THE CITY LAYOUT — buildings are sited BEFORE any tree is planted
# =========================================================================
# Trees and buildings used to be placed independently with zero mutual
# awareness, so they intersected freely. Now the building sites are resolved
# first and the tree pass treats them as obstacles, which is what lets hit
# blocks be added later without tree and building volumes overlapping.
#
# RING_KEEP is the showcase: the lit walkway ring around the Angel Oak is at
# CITY_ANG * R * 0.34 ≈ 5.6 BU (38 game units), and NOTHING — tree or
# building — is allowed in that annulus, so it reads clean from directly above.
RING_MAJOR = CITY_ANG * R * 0.34
RING_KEEP  = ((RING_MAJOR - 1.2) / R, (RING_MAJOR + 1.2) / R)   # in radians
OAK_KEEP   = 0.040          # the Angel Oak's own crown footprint
SHAFT_KEEP = 0.022          # floor on the descent shaft; the real test is
                            # CROWN-AWARE — see pad_clear() below

def _ang(a, b):
    return math.acos(max(-1.0, min(1.0, float(a @ b))))

def in_ring_keep(d):
    return RING_KEEP[0] <= _ang(d, CITY_DIR) <= RING_KEEP[1]

def pad_dist(d):
    return min(_ang(d, p) for p in PAD_DIRS)

CITY_BUILDINGS = 58      # target; rejection sampling lands ~46-50
crng = random.Random(SEED + 909)
CITY_SITES = []          # (dir, size_BU, kind_roll, footprint_BU)
_tries = 0
while len(CITY_SITES) < CITY_BUILDINGS and _tries < 4000:
    _tries += 1
    a   = crng.uniform(0, 2 * math.pi)
    rad = CITY_ANG * crng.uniform(0.18, 0.86)
    d   = step_along(CITY_DIR, CITY_T1 * math.cos(a) + CITY_T2 * math.sin(a), rad)
    if in_ring_keep(d):
        continue                       # keep the showcase ring clear
    if pad_dist(d) < 0.030:
        continue                       # keep the platforms clear
    s = crng.uniform(0.42, 0.78) * MS
    foot = s * 0.75                    # the widest a structure gets, in BU
    if any(_ang(d, o[0]) * R < (foot + o[3]) * 0.85 for o in CITY_SITES):
        continue                       # don't stack buildings on each other
    CITY_SITES.append((d, s, crng.random(), foot))
print(f"Angel Oak: {len(CITY_SITES)} building sites")

# =========================================================================
# THE TREES — one zoned pass. See the radial profile below.
# =========================================================================
#   0.000 – 0.040   the Angel Oak alone
#   0.040 – 0.072   THE LIGHT RING — clear, this is the showcase
#   0.072 – 0.165   built-up city: trees BETWEEN buildings, canopy tier so
#                   their crowns clear the rooftops
#   around a pad    size gradient — small at the shaft, growing outward
#   0.165 – 0.320   the thick collar, dense all the way around
#   0.320 – 0.600   falloff, thinning with distance
#
# SIZE GRADIENT (the hit-block requirement): tree height is driven by distance
# from the NEAREST pad, so the smallest trunks are exactly where a clipped
# wingtip would otherwise ruin a landing, and they grow outward from there.
#   at the shaft edge  ≈ 4.7 BU  (32 game units — just tops the 30-unit deck)
#   far from any pad   ≈ 10.8 BU (73 game units)
TREE_LOG = []            # (dir, height_BU, trunk_r_BU, ground_mult) → json

def tree_height(d, rng):
    t = smoothstep(SHAFT_KEEP, 0.100, pad_dist(d))
    return GROVE_H * (0.55 + 0.72 * t) * rng.uniform(0.90, 1.12)

def pad_clear(d, h):
    """No CROWN may overhang a platform deck.

    A fixed keep-out radius does not work here, because crown size varies 3x
    across the gradient. v1 used a flat 0.022 rad while a canopy-tier crown
    spans ~0.032 — so a tree planted legally at 0.023 threw foliage clean over
    the pad, and the platform rendered as a white speck under a lid of leaves.
    Scaling the keep-out by the tree's own crown is also what PRODUCES the
    gradient: small trees may crowd right up to the deck edge, big ones are
    pushed back, with no separate rule needed."""
    need = (PLAT_R + h * 0.30 + 0.30) / R      # deck + crown spread + margin
    return pad_dist(d) >= max(SHAFT_KEEP, need)

def blocked(d, h):
    """Reject a tree site. Buildings block by TRUNK only — a crown may pass
    overhead, which is exactly the 'big canopy trees spaced between the
    buildings' look — but a trunk inside a structure would put two collision
    volumes in the same place."""
    if _ang(d, CITY_DIR) < OAK_KEEP:
        return True
    if in_ring_keep(d):
        return True
    if not pad_clear(d, h):
        return True
    for bd, _s, _k, foot in CITY_SITES:
        if _ang(d, bd) * R < foot + 0.55:      # trunk clearance in BU
            return True
    return False

def city_canopy_fix(d, h):
    """Inside the city, a tree near a building must be TALL enough that its
    crown clears the rooftop — otherwise foliage grows through a building.
    Roofs top out around deck_z + 3.5 BU; crown undersides sit at ~0.96 * h."""
    if _ang(d, CITY_DIR) > CITY_ANG:
        return h
    near = any(_ang(d, bd) * R < 4.5 for bd, _s, _k, _f in CITY_SITES)
    return max(h, 8.8) if near else h

def add_tree(d, rng, detail=1, trunk_r=None, h=None):
    if h is None:
        h = tree_height(d, rng)
    h = city_canopy_fix(d, h)
    if blocked(d, h):
        return False
    TREE_LOG.append((d, h, trunk_r if trunk_r else 0.062 * h, detail))
    return True

# THE ANGEL OAK itself — dead centre, biggest thing on the planet. Logged by
# hand because it bypasses every keep-out rule (it IS the centre).
make_tree(cd * grove_ground, surf_quat(cd, ct1), OAK_H, 0.95, trng, grove, hero=True)
OAK_ENTRY = (CITY_DIR, OAK_H, 0.95, CITY_GROUND)

# ---- rings around each platform, small→large going out. Four rings instead of
# two, so the gradient is actually readable as a bowl.
pad_planted = 0
for pd_ in PAD_DIRS:
    p1, p2 = tangents(pd_)
    # Radii chosen against pad_clear(): at each one the gradient's tree is just
    # small enough that its crown stops at the deck edge. 0.035 → ~5.2 BU trees,
    # 0.078 → ~9.7 BU. That IS the small-to-large bowl.
    for ring_r, count, phase in ((0.035, 10, 0.00), (0.048, 13, 0.26),
                                 (0.062, 15, 0.12), (0.078, 18, 0.34)):
        for ri in range(count):
            a = (ri / count) * 2 * math.pi + phase + trng.uniform(-0.09, 0.09)
            td = step_along(pd_, p1 * math.cos(a) + p2 * math.sin(a),
                            ring_r * trng.uniform(0.93, 1.09))
            if add_tree(td, trng, detail=1):
                pad_planted += 1

# ---- the rest of the built-up city, filling between the buildings
city_planted = 0
_t = 0
while city_planted < 70 and _t < 3000:
    _t += 1
    a   = trng.uniform(0, 2 * math.pi)
    rad = trng.uniform(RING_KEEP[1], CITY_ANG)
    d   = step_along(CITY_DIR, CITY_T1 * math.cos(a) + CITY_T2 * math.sin(a), rad)
    if add_tree(d, trng, detail=1):
        city_planted += 1

# ---- THE COLLAR: thick forest wrapping the whole city, thinning outward.
# Sampled by rejection against a density that decays with angular distance, so
# it's genuinely dense at the city edge and fades rather than stopping dead.
collar_planted = 0
_t = 0
while collar_planted < 250 and _t < 12000:
    _t += 1
    a   = trng.uniform(0, 2 * math.pi)
    rad = CITY_ANG + (0.60 - CITY_ANG) * (trng.random() ** 2.1)   # packed inward
    d   = step_along(CITY_DIR, CITY_T1 * math.cos(a) + CITY_T2 * math.sin(a), rad)
    if add_tree(d, trng, detail=0 if rad > 0.26 else 1):
        collar_planted += 1

# ---- emergents around EVERY clearing, so every glade has a treeline edge
edge_planted = 0
for c in CLEARINGS:
    e1, e2 = tangents(c["dir"])
    for ei in range(18 if c["name"] else 4):
        a = trng.uniform(0, 2 * math.pi)
        ed = step_along(c["dir"], e1 * math.cos(a) + e2 * math.sin(a),
                        c["ang"] * trng.uniform(0.92, 1.30))
        if add_tree(ed, trng, detail=0,
                    h=GROVE_H * trng.uniform(0.55, 0.86), trunk_r=0.42):
            edge_planted += 1

# ---- and a scatter through the open canopy, so the whole planet reads as real
# forest. Their trunks are BURIED inside the canopy terrain by design — only
# the crowns break through, which is what an emergent looks like from above.
_srng = random.Random(SEED + 616)
scatter_planted = 0
_t = 0
while scatter_planted < 90 and _t < 3000:
    _t += 1
    d = ll_dir(math.degrees(math.asin(_srng.uniform(-0.92, 0.92))),
               _srng.uniform(-180, 180))
    if _ang(d, CITY_DIR) < 0.62:
        continue                      # the collar already owns this ground
    if add_tree(d, _srng, detail=0,
                h=GROVE_H * _srng.uniform(0.62, 0.95), trunk_r=0.44):
        scatter_planted += 1

# ---- plant everything logged, in ONE batched height lookup. A per-tree
# height_field() call re-evaluates 28 clearings and 7 rivers for a single
# point, and there are now several hundred of them.
print("planting…")
_ds = np.array([t[0] for t in TREE_LOG])
_gm, _ = height_field(_ds, flatten=False, canopy=False)
# inside the grove the ground is LEVELLED, so use the pan height there or the
# trunks would step up and down over the natural relief the flatten removed
TREE_PLANTED = []
for (d, h, tr, det), g in zip(TREE_LOG, _gm):
    inside = 1.0 - smoothstep(CITY_ANG * 0.55, CITY_ANG * 1.20, _ang(d, CITY_DIR))
    gh = float(g) * (1.0 - inside) + CITY_GROUND * inside
    dv = Vector(d.tolist())
    t1, _ = tangents(d)
    make_tree(dv * (R * gh), surf_quat(dv, Vector(t1.tolist())),
              h, tr, trng, grove, detail=det)
    TREE_PLANTED.append((d, h, tr, gh))
TREE_PLANTED.append(OAK_ENTRY)

print(f"  {len(TREE_PLANTED)} trees: 1 Angel Oak + {pad_planted} ringing the "
      f"platforms + {city_planted} through the city + {collar_planted} collar "
      f"+ {edge_planted} clearing edges + {scatter_planted} emergents")
join_as(grove, "Grove")

# The city's walkways span from the ring out to real trunks, so they need the
# grove tree positions. Derived from what was actually planted rather than kept
# as a parallel list — a second list is exactly how the walkways ended up
# pointing at trees that no longer existed.
grove_dirs = [d for d, h, tr, gh in TREE_PLANTED
              if RING_KEEP[1] < _ang(d, CITY_DIR) < CITY_ANG * 0.80
              and h > 8.0]
grove_dirs.sort(key=lambda d: _ang(d, CITY_DIR))


# -------------------------------------------------------- ANGEL OAK CITY --
# White ceramic and glass, curved forms, strung between the trunks at mid-trunk
# height. Every other settlement in this system is a rusty box — this is the
# one place that isn't, and the geometry has to say so before the colour does.
print("building Angel Oak…")
city = []
deck_z = PLAT_H * R                    # platform height above the grove floor
crng = random.Random(SEED + 909)
cq = surf_quat(cd, ct1)
cbase = cd * grove_ground

def city_pt(a, rad):
    """a point on the grove floor at bearing `a`, `rad` radians out"""
    d = step_along(CITY_DIR, CITY_T1 * math.cos(a) + CITY_T2 * math.sin(a), rad)
    return Vector(d.tolist()), d

# ---- the great ring: a walkway encircling the Angel Oak at deck height
_torus(cbase, cq, (0, 0, deck_z), CITY_ANG * R * 0.34, 0.10 * MS,
       deck_m, city, mseg=28, nseg=5)
_torus(cbase, cq, (0, 0, deck_z + 0.28 * MS), CITY_ANG * R * 0.34, 0.03 * MS,
       guide_m, city, mseg=28, nseg=4)

# ---- buildings, hung around the grove at deck height. Domes, lenses and
# tapered spires — no boxes.
# Sites were resolved BEFORE the trees were planted (see THE CITY LAYOUT), so
# the tree pass could treat them as obstacles. Iterate that list — don't
# re-roll positions here, or buildings and trees go back to intersecting.
for _bd, s, k, _foot in CITY_SITES:
    pv = Vector(_bd.tolist())
    bp = pv * grove_ground
    bq = surf_quat(pv, ct1)
    if k < 0.34:
        # dome on a slim stem
        _cyl(bp, bq, (0, 0, deck_z * 0.5), 0.10 * MS, deck_z, trim_m, city, verts=8)
        _ico(bp, bq, (0, 0, deck_z + s * 0.18), (s * 0.52, s * 0.52, s * 0.34),
             cer_m, city, subd=2)
        _torus(bp, bq, (0, 0, deck_z + s * 0.16), s * 0.42, 0.035 * MS,
               glass_m, city, mseg=16, nseg=4)
    elif k < 0.60:
        # lens block — a flattened ellipsoid, the signature shape here
        _cyl(bp, bq, (0, 0, deck_z * 0.5), 0.09 * MS, deck_z, trim_m, city, verts=8)
        _ico(bp, bq, (0, 0, deck_z + s * 0.14), (s * 0.72, s * 0.44, s * 0.20),
             cer_m, city, subd=2)
        _ico(bp, bq, (0, 0, deck_z + s * 0.15), (s * 0.55, s * 0.30, s * 0.22),
             glass_m, city, subd=2)
    elif k < 0.80:
        # tapered spire with a lit crown
        _cyl(bp, bq, (0, 0, deck_z * 0.5), 0.09 * MS, deck_z, trim_m, city, verts=8)
        _cone(bp, bq, (0, 0, deck_z + s * 0.50), s * 0.34, s * 0.10, s * 1.00,
              cer_m, city, verts=10)
        _ico(bp, bq, (0, 0, deck_z + s * 1.04), (s * 0.10,) * 3, lite_m, city, subd=1)
    else:
        # stacked terrace pods
        _cyl(bp, bq, (0, 0, deck_z * 0.5), 0.09 * MS, deck_z, trim_m, city, verts=8)
        for t in range(crng.randint(2, 3)):
            r_ = s * (0.44 - t * 0.10)
            _cyl(bp, bq, (0, 0, deck_z + s * (0.12 + t * 0.30)), r_, s * 0.26,
                 cerS_m if t % 2 else cer_m, city, verts=12)
        _ico(bp, bq, (0, 0, deck_z + s * 0.14), (s * 0.06,) * 3, lite_m, city, subd=1)

# ---- walkways: thin decks radiating from the ring out to the grove trunks.
# Cap the count — grove_dirs is now derived from every planted city tree, which
# is far more than the 12 the original hand-built list held.
for gd in grove_dirs[:36:3]:
    gdv = Vector(gd.tolist())
    mid = (cd + gdv).normalized()
    span = math.acos(max(-1.0, min(1.0, float(CITY_DIR @ gd)))) * R
    wq = surf_quat(mid, (gdv - cd).normalized())
    _box(mid * grove_ground, wq, (0, 0, deck_z),
         (span * 1.02, 0.16 * MS, 0.05 * MS), deck_m, city)

# ---- THE LANDING PLATFORMS. The only safe ground in the city: everything
# around them is canopy, which costs hull. Two of them, opposite sides, each
# ringed with guidance lights so they're findable from above the leaf line.
PADS = []
for pi, pd_ in enumerate(PAD_DIRS):
    pv = Vector(pd_.tolist())
    pp = pv * grove_ground
    pq = surf_quat(pv, ct1)
    # stem down to the forest floor
    _cyl(pp, pq, (0, 0, deck_z * 0.5), 0.20 * MS, deck_z, trim_m, city, verts=10)
    # the deck — a clean disc
    _cyl(pp, pq, (0, 0, deck_z - 0.06), PLAT_R, 0.14, deck_m, city, verts=16)
    _cyl(pp, pq, (0, 0, deck_z + 0.02), PLAT_R * 0.96, 0.04, cer_m, city, verts=16)
    # guidance ring + approach beacons
    _torus(pp, pq, (0, 0, deck_z + 0.06), PLAT_R * 0.80, 0.025 * MS,
           guide_m, city, mseg=20, nseg=4)
    for li in range(6):
        la = li * math.pi / 3.0
        _ico(pp, pq, (math.cos(la) * PLAT_R * 0.90, math.sin(la) * PLAT_R * 0.90,
                      deck_z + 0.10 * MS), (0.055 * MS,) * 3,
             guide_m if li % 2 == 0 else beacon_m, city, subd=1)
    PADS.append((pd_, deck_z))

join_as(city, "AngelOak")
print(f"  {CITY_BUILDINGS} structures + 2 landing platforms, deck {gu(deck_z):.1f} game units up")


# ------------------------------------------------------------ EXPORT GLB --
glb_path = os.path.join(OUT, "verdant.glb")
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=glb_path, export_format='GLB')
print(f"wrote {glb_path}")


# ------------------------------------- EXPORT HEIGHT GRID + CANOPY MASK --
# Two arrays in one file (header note 2). The height grid is the canopy top;
# the mask says whether that height is LEAF (hazard) or GROUND (safe).
print("baking height grid + canopy mask…")
GW, GH = 1280, 640
gy, gx = np.mgrid[0:GH, 0:GW]
lon = (gx + 0.5) / GW * 2 * np.pi - np.pi
lat = np.pi / 2 - (gy + 0.5) / GH * np.pi
gdirs = np.stack([np.cos(lat) * np.cos(lon),
                  np.cos(lat) * np.sin(lon),
                  np.sin(lat)], axis=-1).reshape(-1, 3)
gm, _ = height_field(gdirs)
lo, hi = float(gm.min()), float(gm.max())
q = np.round((gm - lo) / (hi - lo) * 255).astype(np.uint8)

# canopy mask at half resolution — it's a yes/no, it does not need 1280x640
MW, MH = 640, 320
my, mx = np.mgrid[0:MH, 0:MW]
mlon = (mx + 0.5) / MW * 2 * np.pi - np.pi
mlat = np.pi / 2 - (my + 0.5) / MH * np.pi
mdirs = np.stack([np.cos(mlat) * np.cos(mlon),
                  np.cos(mlat) * np.sin(mlon),
                  np.sin(mlat)], axis=-1).reshape(-1, 3)
_, maux = height_field(mdirs)
mask = np.where(maux["canopy"] > 0.004, 255, 0).astype(np.uint8)
_hazard = 100.0 * float((mask > 0).sum()) / mask.size

with open(os.path.join(OUT, "verdant_height.json"), "w") as f:
    json.dump({"w": GW, "h": GH, "min": lo, "max": hi,
               "b64": base64.b64encode(q.tobytes()).decode(),
               "canopy_w": MW, "canopy_h": MH,
               "canopy_b64": base64.b64encode(mask.tobytes()).decode()}, f)
print(f"wrote verdant_height.json  (height {lo:.4f} … {hi:.4f}, "
      f"canopy mask {MW}x{MH}, {_hazard:.1f}% hazard)")

# ------------------------------------------------- EXPORT TREE COLLIDERS --
# Every tree's position and size, so hit blocks can be built without parsing
# 500+ meshes back out of the GLB. Emitted from the SAME list the geometry was
# planted from, so the colliders cannot drift from what you can see.
#
# All dimensions in GAME units. Position: dir * (radius * ground).
#   trunkR  the solid part — this is the collider that matters
#   crownR  foliage spread, if you want a soft/brush volume above trunk height
#   h       total height; the crown sits in the top ~25% of it
print("baking tree colliders…")
trees_out = []
for d, h, tr, gh in TREE_PLANTED:
    trees_out.append({
        "lat":    round(math.degrees(math.asin(max(-1.0, min(1.0, float(d[2]))))), 4),
        "lon":    round(math.degrees(math.atan2(float(d[1]), float(d[0]))), 4),
        "ground": round(float(gh), 6),
        "h":      round(gu(h), 2),
        "trunkR": round(gu(tr), 2),
        "crownR": round(gu(h * 0.30), 2),
    })
with open(os.path.join(OUT, "verdant_trees.json"), "w") as f:
    json.dump({"radius": GAME_R, "count": len(trees_out),
               "note": "position = dir(lat,lon) * (radius * ground); "
                       "dims in game units; crown sits in the top ~25% of h",
               "trees": trees_out}, f)
_hs = [t["h"] for t in trees_out]
print(f"wrote verdant_trees.json  ({len(trees_out)} colliders, "
      f"heights {min(_hs):.0f}–{max(_hs):.0f} game units)")


# --------------------------------------------------------------- PREVIEWS --
print("rendering previews (Cycles CPU)…")
scene.render.engine = 'CYCLES'
scene.cycles.samples = 16
scene.cycles.device = 'CPU'
scene.render.resolution_x = scene.render.resolution_y = 900
scene.view_settings.view_transform = 'Standard'

world = bpy.data.worlds.new("Space")
world.color = (0.004, 0.005, 0.004)
scene.world = world

def aim(obj, target):
    d = (target - obj.location).normalized()
    obj.rotation_mode = 'QUATERNION'
    obj.rotation_quaternion = d.to_track_quat('-Z', 'Y')

bpy.ops.object.light_add(type='SUN', location=(300, -300, 200))
sun = bpy.context.active_object
sun.data.energy = 3.6
aim(sun, Vector((0, 0, 0)))
bpy.ops.object.light_add(type='SUN', location=(-300, 300, -150))
fill = bpy.context.active_object
fill.data.energy = 0.35
aim(fill, Vector((0, 0, 0)))

bpy.ops.object.camera_add()
cam = bpy.context.active_object
scene.camera = cam

def cam_over(lat, lon, dist, elev_deg, az_deg):
    d = ll_dir(lat, lon)
    hm, _ = height_field(d[None, :])
    dv = Vector(d.tolist())
    C = dv * (R * float(hm[0]))
    t1 = dv.cross(Vector((0, 0, 1))).normalized()
    t2 = dv.cross(t1)
    az, el = math.radians(az_deg), math.radians(elev_deg)
    horiz = t1 * math.cos(az) + t2 * math.sin(az)
    return C + (dv * math.sin(el) + horiz * math.cos(el)) * dist, C

def light_for(target):
    n = target.normalized()
    t = n.cross(Vector((0, 0, 1)))
    t = t.normalized() if t.length > 1e-6 else Vector((1, 0, 0))
    return (n * 1.0 + t * 0.85).normalized() * 500

SUN_HOME = Vector((300, -300, 200))

_city  = cam_over(CITY_LAT, CITY_LON, 34, 26, 40)
_cityhi= cam_over(CITY_LAT, CITY_LON, 46, 58, 130)
_oak   = cam_over(CITY_LAT, CITY_LON, 19, 14, 210)
# straight down onto platform 1 — the shot that proves the ring of trunks
_p0lat = math.degrees(math.asin(max(-1.0, min(1.0, float(PAD_DIRS[0][2])))))
_p0lon = math.degrees(math.atan2(float(PAD_DIRS[0][1]), float(PAD_DIRS[0][0])))
# Pull WELL back and look steeply down. The trunk ring is 3.2–5.2 BU out and
# 7–10 BU tall, so anything closer than ~25 BU puts the camera inside the
# canopy and renders a wall of bark.
_pad0  = cam_over(_p0lat, _p0lon, 30, 74, 30)
_pad1  = cam_over(_p0lat, _p0lon, 34, 32, 120)
_johns = cam_over(-22, 48, 22, 30, 60)
_cyp   = cam_over(40, 140, 20, 28, -50)

SHOTS = [
    ("verdant_preview_a.png",     Vector(ll_dir(10, -28).tolist()) * 300,
                                  Vector((0, 0, 0)), 3.6, False),   # city face
    ("verdant_preview_b.png",     Vector(ll_dir(-6, 120).tolist()) * 300,
                                  Vector((0, 0, 0)), 3.6, False),   # far face
    ("verdant_preview_night.png", Vector(ll_dir(8, -30).tolist()) * 280,
                                  Vector((0, 0, 0)), 0.04, False),  # BIOLUMINESCENCE
    ("verdant_preview_city.png",   _city[0],   _city[1],   3.2, True),
    ("verdant_preview_cityhi.png", _cityhi[0], _cityhi[1], 3.2, True),
    ("verdant_preview_oak.png",    _oak[0],    _oak[1],    3.2, True),
    ("verdant_preview_pad.png",    _pad0[0],   _pad0[1],   3.2, True),
    ("verdant_preview_approach.png", _pad1[0], _pad1[1],   3.2, True),
    ("verdant_preview_johns.png",  _johns[0],  _johns[1],  3.2, True),
    ("verdant_preview_cypress.png",_cyp[0],    _cyp[1],    3.2, True),
]
for fname, pos, target, energy, relight in SHOTS:
    sun.data.energy = energy
    fill.data.energy = 0.35 if energy > 1.0 else 0.02
    sun.location = light_for(target) if relight else SUN_HOME
    aim(sun, Vector((0, 0, 0)))
    cam.location = pos
    aim(cam, target)
    scene.render.filepath = os.path.join(OUT, "previews", fname)
    bpy.ops.render.render(write_still=True)
    print(f"wrote {fname}")

# ------------------------------------------------------- THE BODIES ENTRY --
print("\n" + "=" * 70)
print("BODIES entry for space-flight.html — copy these EXACT numbers:")
print("=" * 70)
print( '    landable: true,')
print(f'    gravity: 0.45,          // smallest world in the system — light pull')
print(f'    spin: 0.004,            // was 0.03, the fastest in the system. A')
print(f'                            // parked ship RIDES the rotation and 0.02')
print(f'                            // already shears the ground out from under')
print(f'                            // it (see CINDER). Only safe before now')
print(f'                            // because VERDANT was not landable.')
print(f'    heightFile: "planets/verdant_height.json",')
print( '    // canopy hazard: the SAME json carries canopy_b64, a 640x320 uint8')
print( '    // mask (0 = clearing/safe, 255 = canopy) on the same lat/lon math')
print( '    // as the height grid. At touchdown: canopy -> hull damage instead')
print( '    // of a clean landing latch. Pads are checked first, so they are safe.')
print(f'    pads: [')
for pi, (pdir, dz) in enumerate(PADS):
    plat = math.degrees(math.asin(max(-1.0, min(1.0, float(pdir[2])))))
    plon = math.degrees(math.atan2(float(pdir[1]), float(pdir[0])))
    ang  = (PLAT_R * 0.86) / R
    print(f'      {{ lat: {plat:.2f}, lon: {plon:.2f}, ang: {ang:.4f}, '
          f'top: {CITY_GROUND + PLAT_H:.5f} }},   // Angel Oak platform {pi + 1}')
print(f'    ],')
print("=" * 70)
print("\nDONE — verdant.glb + verdant_height.json + previews")
