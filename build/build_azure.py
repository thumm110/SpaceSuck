"""
build_azure.py — SpaceSuck planet factory, planet #4: AZURE
==========================================================
The ocean world. A bright, wet, DENSELY INHABITED archipelago planet — the exact
tonal opposite of CINDER. Scattered island chains, turquoise reef shallows, a
colossal ring atoll (THE RING), a permanent cyclone (THE EYE), a working sail
fleet, and four settlements strung along the shipping lanes between them.

    blender -b -P build_azure.py

Outputs (written next to this script):
    azure.glb            — the planet mesh: flat-shaded low-poly with per-face
                           colors, four settlements, ~26 sailing vessels, a
                           cloud deck with a spiral storm
    azure_height.json    — 1280x640 lat/lon height grid (base64 uint8)
    azure_preview_*.png  — Cycles renders

==========================================================================
THE ONE THING THAT MAKES AZURE DIFFERENT: **WATER KILLS YOU**
==========================================================================
There is no water landing. Touch the sea and the game calls shipBreach() —
you're towed home and the ship resets. Everything below follows from that.

1. THE OCEAN IS BAKED FLAT AT EXACTLY SEA LEVEL, in BOTH the visible mesh and
   the height grid. height_field() computes real bathymetry internally (deep
   basins, shelves, reef crests) — that drives the COLOR — and then clamps:

       raw = 1.0 + elev            # true topography/bathymetry
       m   = maximum(raw, SEA)     # what the mesh and the grid both see
       depth = SEA - raw           # >0 in water; only the color pass sees it

   So there is NO seafloor geometry in the GLB at all. The visible surface over
   water IS the water. That means:
     - no transparency, so no z-sorting/z-fighting against a seabed
     - a smaller GLB than CINDER's for the same subdiv
     - the game's water test is free: "the grid says sea level" IS "this is
       water". One comparison, no water-mask file, no second lookup.

2. PADS EXCLUDE THEMSELVES. groundRadius() in the game checks pads BEFORE it
   samples the grid, and every pad deck here sits above SEA. So the water test
   can't fire on a pad — you can land on FOLLY's rig deck surrounded by lethal
   ocean and the check never trips.

3. NO POLAR ICE — DELIBERATE. Pack ice would look like solid white ground and
   then kill you, because it's water. That's a trap, not a challenge. The poles
   get a cold steel-blue WATER tint instead. Don't "fix" this by adding ice.

4. THE COSMETIC RIPPLE IS NOT IN THE GRID. The ocean gets a small wave
   displacement so it isn't a mirror, applied with ripple=True when building the
   MESH and ripple=False when baking the GRID. The grid stays authoritative —
   same ground rule as every other planet. Boats carry a DRAFT deeper than the
   ripple amplitude so hulls never hover over a trough.

5. SCALE: AZURE is 1425u in game, so the loader scales this R=100 model by
   14.25 (vs CINDER's 9, RUBICON's 32). MS re-normalizes STRUCTURE sizes so a
   dock shack here is the same physical size as one at RustHollow. Planet-scale
   things (island widths, the atoll, cloud altitude) are NOT multiplied by MS.
"""

import bpy
import bmesh
import json
import base64
import math
import os
import random
import numpy as np
from mathutils import Vector, Matrix

# ---------------------------------------------------------------- CONFIG --
R       = 100.0     # base radius in Blender units — MUST stay 100 (the game's
                    #   loader does model.scale = cfg.radius / 100)
SUBDIV  = 7         # 20 * 4^(n-1) → 81,920 tris. Same as every other planet.
SEED    = 42        # matches AZURE's seed in the game's BODIES config

GAME_R  = 1425.0    # AZURE's cfg.radius — used only to print game-unit numbers
SCALE   = GAME_R / R                    # 14.25
MS      = 32.0 / SCALE                  # ≈ 2.246 — structure size normalizer

# --- the sea ------------------------------------------------------------
SEA        = 1.000    # sea level as a surface multiplier. The game's BODIES
                      #   entry MUST carry seaLevel: 1.0 to match.
RIPPLE_AMP = 0.0005   # cosmetic chop, ±0.7 game units. MESH ONLY (see note 4).
BOAT_DRAFT = 0.0010   # hulls sink this far below SEA — deeper than the ripple

# --- ocean floor (never seen; drives color only) ------------------------
FLOOR_DEEP = -0.020   # abyssal floor, ~29 game units below the surface
FLOOR_VAR  =  0.009   # bathymetric roughness

# ------------------------------------------------------------- THE SITES --
# Lowcountry names. Charleston is on EARTH; AZURE gets the rest of the coast.
#
# LAND_SITES get a leveled pan exactly like CINDER's outposts — the pan is real
# ground above sea level, so there's no deck-vs-grid mismatch to get wrong. Each
# one also declares a pad in BODIES so the port system has an anchor, with
# top == the pan height the script prints (perfect agreement by construction).
LAND_SITES = [
    # the capital: a working port terraced up the biggest island on the planet
    {"name": "Bulls Bay", "lat": -14.0, "lon": 62.0, "ang": 0.105,
     "structures": 56, "kind": "port"},
    # stilt village out on a reef edge — aquaculture, drying racks, small docks
    {"name": "Shem", "lat": 26.0, "lon": 118.0, "ang": 0.070,
     "structures": 22, "kind": "stilt"},
    # stilt village straddling a channel between two islands
    {"name": "Breach Inlet", "lat": -32.0, "lon": -110.0, "ang": 0.062,
     "structures": 18, "kind": "stilt"},
]

# THE RIG — the hero landing. A salvage platform standing on pylons in open
# water inside THE RING's lagoon. NOT in LAND_SITES: there is no pan, no ground,
# nothing but ocean under it. The deck is the only safe surface, and it is
# surrounded on every side by instant death. Miss it and you're towed home.
RIG = {"name": "Folly", "lat": 7.0, "lon": -34.0,
       "deck_r": 2.8,          # deck radius in Blender units → 40 game units
       "deck_top": 0.010}      # deck sits SEA + this → pad top 1.010

# HERO #1 — THE RING: a colossal atoll. The crest breaks the surface as a broken
# necklace of motus (dry islets) with navigable passes between them; inside is a
# shallow lagoon that reads bright turquoise from orbit. FOLLY sits in it.
RING_LAT, RING_LON = 8.0, -35.0
# RING_R was 0.160 in v1–v3, which is only ~8 icosphere faces of radius at
# subdiv 7 — and a thresholded circle that small on a triangular lattice
# renders as a HEXAGON no matter how much noise you throw at it. (Confirmed:
# the baked height grid shows a clean ring, so it was never the math.) The
# checklist's answer for a hero feature is a local hi-res patch; the cheaper
# answer, taken here, is to make the atoll big enough that faceting stops
# reading as a polygon — and strongly LOBED so there's no clean circle to
# alias in the first place. 0.235 rad ≈ 335 game units of lagoon radius, which
# also makes it somewhere you can actually fly around inside.
RING_R    = 0.235     # crest radius in radians → ~335 game units
RING_W    = 0.026     # crest thickness
RING_H    = 0.032     # crest height above the local floor
RING_LOBE = 0.22      # azimuthal wobble of the crest radius (was 0.09)
# The lagoon floor is SET to this, not lifted toward it. v1 added a lift to the
# abyssal floor and the floor noise + shelf term pushed parts of the lagoon
# above sea level — the lagoon turned into a BEACH and FOLLY ended up standing
# on dry sand instead of over water. Setting it absolutely makes the lagoon
# guaranteed shallow water, which is the whole reason the rig is interesting.
LAGOON_FLOOR = -0.0060   # ~8.5 game units deep → bright turquoise, never land

# HERO #2 — THE EYE: a permanent cyclone. Pure cloud geometry (see the clouds
# section) — a logarithmic spiral of flattened blobs with a clear eye. White on
# deep blue is the FORGIVING case for low-poly cloud blobs; CINDER's failure was
# opaque blobs on a near-black world, which is the opposite problem.
EYE_LAT, EYE_LON = -24.0, 8.0
EYE_R = 0.145         # outer radius of the spiral in radians

# THE BATTERY — a wreck field. Hulls piled on a shallow bank, one of them
# capsized with its mast in the water. Pure landmark, zero services.
BATTERY_LAT, BATTERY_LON = 40.0, 168.0

# --- palette ------------------------------------------------------------
# Authored as sRGB hex, exported raw (the game renders linear passthrough).
PAL = {
    # Water, deep → shallow. This gradient does most of the planet's work.
    # v1 ran too dark and desaturated — the far side read as a gray-blue marble
    # rather than an OCEAN world. The whole ramp is brighter and bluer now.
    "abyss":    0x0a2a4e,   # deepest basins
    "deep":     0x11467a,   # open ocean
    "ocean":    0x1b6fa0,   # ordinary sea
    "shelf":    0x2b9dbe,   # continental shelf / lagoon edge
    "shallow":  0x45c9d2,   # bright shallows
    "reef":     0x7ceada,   # reef crest turquoise — the "safe ground ahead" cue
    "surf":     0xe2f7f1,   # foam ring right at the waterline
    # cold, dark WATER at the poles — deliberately not ice (header note 3)
    "polar":    0x123a52,
    # land
    "sand":     0xe3d7ac,   # beach
    "scrub":    0x7d8a55,   # dry coastal scrub
    "green":    0x3d7846,   # vegetated lowland
    "greenDk":  0x2a5636,   # dense interior
    "rock":     0x4c4a46,   # volcanic island rock
    "rockHi":   0x736d63,   # weathered high rock
    # traffic + industry
    "wake":     0xa9dfdc,   # painted boat wake
    "lane":     0x2a94ad,   # worn shipping lane
    "kelp":     0x1d6355,   # aquaculture / kelp farm grids
    "pan":      0x8f8a76,   # leveled ground — packed coral, not drab gray dirt
    "dock":     0x6d5b46,   # timber decking
    # structures
    "hullW":    0xdfe4e6, "hullR": 0xa85f42, "hullB": 0x2f5d78,
    "canvas":   0xe8e2d2,   # clean sail
    "canvasP":  0xbfae94,   # patched salvage sail
    "metalA":   0x7a7f85, "metalB": 0x565b60, "metalC": 0x3a3d40,
    "rust":     0x8a4b28, "steel": 0x9aa1a8, "timber": 0x6b563c,
    "amber":    0xffb347,   # work lights
    "green_l":  0x35ff9a,   # starboard / channel marker
    "red_l":    0xff4d4d,   # port / hazard
    "cloud":    0xffffff,
}

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT  = os.path.join(ROOT, "planets")
os.makedirs(os.path.join(OUT, "previews"), exist_ok=True)


# ---------------------------------------------------- NOISE (numpy, fast) --
# Identical machinery to build_cinder.py — value noise, hashed corners, blended.

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
    """p: (N,3) points → (N,) noise in [0,1]"""
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

    IMPORTANT: plain fbm() does NOT span [0,1] — it clusters tightly around 0.5
    with a typical spread of only about ±0.12. So `(fbm(...) - 0.5) * A` gives a
    swing around A/8, not A. That cost a whole build iteration: THE RING kept
    rendering as a hexagon despite a nominal 0.034-rad boundary wobble, because
    the wobble was really ±0.004 rad — under 2% of the atoll radius. Use this
    wherever the amplitude is supposed to MEAN something."""
    return np.clip((fbm(p, octaves, seed) - 0.5) * 4.0, -1.0, 1.0)

def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)

def ll_dir(lat, lon):
    """lat/lon degrees → unit direction, Blender coords (Z = north)"""
    la, lo = math.radians(lat), math.radians(lon)
    return np.array([math.cos(la) * math.cos(lo),
                     math.cos(la) * math.sin(lo),
                     math.sin(la)])

def tangents(d):
    """an orthonormal tangent pair at direction d"""
    up = np.array([0.0, 0.0, 1.0])
    if abs(float(d @ up)) > 0.94:
        up = np.array([1.0, 0.0, 0.0])
    t1 = np.cross(d, up); t1 /= np.linalg.norm(t1)
    t2 = np.cross(d, t1)
    return t1, t2

def slerp_dir(a, b, t):
    """point t of the way along the great circle from a to b"""
    om = math.acos(float(np.clip(a @ b, -1.0, 1.0)))
    if om < 1e-7:
        return a.copy()
    s = math.sin(om)
    return (math.sin((1 - t) * om) / s) * a + (math.sin(t * om) / s) * b

def step_along(d, fwd, ang):
    """walk `ang` radians from d in tangent direction fwd, along a great circle"""
    v = d * math.cos(ang) + fwd * math.sin(ang)
    return v / np.linalg.norm(v)


RING_DIR    = ll_dir(RING_LAT, RING_LON)
EYE_DIR     = ll_dir(EYE_LAT, EYE_LON)
RIG_DIR     = ll_dir(RIG["lat"], RIG["lon"])
BATTERY_DIR = ll_dir(BATTERY_LAT, BATTERY_LON)
for _s in LAND_SITES:
    _s["dir"] = ll_dir(_s["lat"], _s["lon"])

RING_T1, RING_T2 = tangents(RING_DIR)


# ------------------------------------------------------ THE ARCHIPELAGO --
# Land is built from CHAINS: strings of islands laid along a great-circle arc,
# the way real volcanic arcs and barrier chains actually run. Nothing here is a
# continent — the biggest single island is ~110 game units across. There is no
# safe bailout anywhere on this planet, which is the whole point.
#
# Each chain: (lat0, lon0, lat1, lon1, count, size_scale, height_scale)
CHAINS = [
    ( 22,  -95,    4,  -68,   9, 1.00, 1.00),
    (-46, -150,  -22, -128,   8, 0.85, 0.90),
    ( 55,   40,   34,   72,   7, 0.90, 1.05),
    (-12,  152,   14,  176,   9, 0.95, 0.95),
    ( 38, -175,   58, -142,   6, 0.80, 0.85),
    (-60,   84,  -38,  108,   7, 0.88, 0.92),
    (  2,   92,   24,  106,   6, 0.82, 0.88),
    (-28,   -8,   -6,   18,   8, 0.92, 1.00),
    ( 44,  118,   62,  150,   6, 0.78, 0.86),
    (-52,  -60,  -30,  -34,   7, 0.86, 0.94),
    ( 16,  -12,   34,   14,   6, 0.84, 0.90),
    (-18,  -78,    2,  -52,   7, 0.90, 0.98),
]

# ISLANDS: (dir, angular_radius, height). Built deterministically from SEED so
# re-runs are identical.
ISLANDS = []
_irng = random.Random(SEED + 101)

for lat0, lon0, lat1, lon1, count, ssz, shg in CHAINS:
    A, B = ll_dir(lat0, lon0), ll_dir(lat1, lon1)
    for k in range(count):
        t = (k + 0.5) / count
        base = slerp_dir(A, B, t)
        # jitter perpendicular to the chain so it isn't a ruler-straight line
        jt1, jt2 = tangents(base)
        off = jt2 * _irng.uniform(-0.045, 0.045)
        d = base + off
        d /= np.linalg.norm(d)
        # Sizing note: an island only breaks the surface where its gaussian
        # clears the ocean floor, so the DRY radius is always smaller than
        # `rad`. v1 used rad 0.026–0.052 with hgt barely above |FLOOR_DEEP| and
        # the planet came out 2.9% land — a few dozen specks in an empty sea.
        # Bigger rad AND more height headroom (hgt >> |FLOOR_DEEP|) so the dry
        # part approaches the full radius instead of ~77% of it.
        rad = _irng.uniform(0.042, 0.078) * ssz
        hgt = _irng.uniform(0.046, 0.066) * shg
        ISLANDS.append((d, rad, hgt))

# scattered loners between the chains — keeps the open ocean from being empty
for _ in range(30):
    d = ll_dir(math.degrees(math.asin(_irng.uniform(-0.93, 0.93))),
               _irng.uniform(-180, 180))
    if float(d @ RING_DIR) > math.cos(RING_R * 1.7):
        continue                       # don't litter the atoll
    ISLANDS.append((d, _irng.uniform(0.024, 0.050),
                    _irng.uniform(0.040, 0.056)))

# ---- guaranteed land under every land settlement. Placing a village and
# HOPING the procedural chains put an island there is how you end up with a
# stilt town in 3km of open water. Each site gets its own explicit island.
SITE_ISLANDS = {
    "Bulls Bay":    (0.098, 0.055),   # the biggest island on the planet
    "Shem":         (0.058, 0.040),
    "Breach Inlet": (0.052, 0.038),
}
for _s in LAND_SITES:
    rad, hgt = SITE_ISLANDS[_s["name"]]
    ISLANDS.append((_s["dir"], rad, hgt))

# BREACH INLET straddles a channel — give it a second island just offshore so
# there's an actual inlet to straddle.
_bi = next(s for s in LAND_SITES if s["name"] == "Breach Inlet")
_bt1, _bt2 = tangents(_bi["dir"])
ISLANDS.append((step_along(_bi["dir"], _bt2, 0.085), 0.044, 0.036))

# THE BATTERY sits on a shallow bank — a rise that stays UNDER water, so the
# wrecks are half-swamped and the water there reads bright. Not an island.
BANKS = [(BATTERY_DIR, 0.055, 0.014)]

print(f"archipelago: {len(ISLANDS)} islands across {len(CHAINS)} chains")


# ------------------------------------------------------- THE HEIGHT FIELD --
# One function decides the whole planet. See header notes 1 and 4.

def height_field(dirs, flatten=True, ripple=False):
    z = dirs[:, 2]

    # ---- ocean floor: rolling bathymetry, all of it below sea level
    elev = FLOOR_DEEP + (fbm(dirs * 2.2 + 4.4, 5, SEED + 3) - 0.5) * FLOOR_VAR
    # broad shelves so the deep/shallow color gradient has structure
    elev += smoothstep(0.48, 0.72, fbm(dirs * 3.4 + 11.1, 4, SEED + 9)) * 0.006

    # ---- ISLANDS: gaussian cones. The edge noise keeps coastlines from being
    # perfect circles — a ring of tidy dots reads as a bug, not a chain.
    # Two octaves of coastline wobble: a broad one for island SHAPE, and a fine
    # one at roughly face scale so the shoreline never settles onto a clean
    # iso-contour and staircase into a polygon (same artifact as the atoll).
    edge = (snoise(dirs * 9.0 + 2.2, 4, SEED + 21) * 0.30
            + snoise(dirs * 30.0 + 7.9, 3, SEED + 24) * 0.16)
    for d, rad, hgt in ISLANDS:
        a = np.arccos(np.clip(dirs @ d, -1.0, 1.0))
        rr = rad * (1.0 + edge)
        elev += np.exp(-(a / rr) ** 2) * hgt

    # ---- shallow BANKS (stay submerged — bright water, not land)
    for d, rad, hgt in BANKS:
        a = np.arccos(np.clip(dirs @ d, -1.0, 1.0))
        elev += np.exp(-(a / rad) ** 2) * hgt

    # ---- THE RING: the lagoon floor is SET (see LAGOON_FLOOR), then the crest
    # ring is laid on top of it.
    # Shape budget for the atoll — three separate knobs, and getting the ratio
    # between them wrong is what cost this feature two build iterations:
    #
    #   RING_LOBE  low-frequency, per-azimuth. Does ALL the heavy lifting on
    #              silhouette: makes the atoll decisively non-circular while
    #              keeping the crest a single connected ring.
    #   ripple     high-frequency, per-face. Breaks the crisp iso-contour that
    #              made v1–v3 staircase into a HEXAGON on the icosphere's
    #              triangular lattice. MUST stay well under RING_W — v4 set it
    #              to 0.048 against a 0.022 crest and the ring blew apart into
    #              a snowflake of disconnected islets.
    #   motu       per-azimuth crest height: thin spots and a couple of real
    #              passes, floored above 0 so the ring never fully parts.
    #
    # (The height grid always showed a clean ring — the hexagon was never the
    # math, it was flat-shaded colour on a coarse lattice. Verified directly
    # against azure_height.json rather than guessed at.)
    ang_ring = np.arccos(np.clip(dirs @ RING_DIR, -1.0, 1.0))
    az_ring  = np.arctan2(dirs @ RING_T2, dirs @ RING_T1)
    _ones = np.ones(len(dirs))
    # feeding cos/sin of the azimuth into 3D noise wraps seamlessly at ±π
    az_p = np.stack([np.cos(az_ring) * 2.6, np.sin(az_ring) * 2.6, _ones * 1.7], axis=-1)

    # LOW frequency on purpose. az_p traces a radius-2.6 circle through the
    # noise lattice, which is ~16 cells around — sampling the crest radius at
    # that rate gave a 14-pointed SNOWFLAKE, not an atoll. A radius-1.05 circle
    # is ~7 cells → three or four broad lobes, which is what real atolls do.
    az_lo = np.stack([np.cos(az_ring) * 1.05, np.sin(az_ring) * 1.05,
                      _ones * 3.1], axis=-1)
    ring_r = RING_R * (1.0 + RING_LOBE * snoise(az_lo, 2, SEED + 93))
    ang_w  = ang_ring + snoise(dirs * 26.0 + 17.3, 4, SEED + 96) * 0.011

    # the lagoon boundary follows the LOBED crest, not a circle of its own, so
    # the bright water is the same irregular shape as the reef around it
    inside = 1.0 - smoothstep(0.76, 0.99, ang_w / ring_r)
    lagoon = LAGOON_FLOOR + snoise(dirs * 15.0 + 21.7, 4, SEED + 97) * 0.0028
    elev = elev * (1.0 - inside * 0.92) + lagoon * (inside * 0.92)

    motu = np.clip(0.78 + 0.55 * snoise(az_p, 4, SEED + 88), 0.05, 1.5)
    elev += np.exp(-((ang_w - ring_r) / RING_W) ** 2) * RING_H * motu

    # ---- island relief: hills on whatever ended up above water
    land = smoothstep(SEA - 1.0, SEA - 1.0 + 0.006, elev)
    elev += land * (fbm(dirs * 14.0 + 6.6, 5, SEED + 40) - 0.5) * 0.016

    raw = 1.0 + elev

    # ---- THE CLAMP (header note 1). Everything below sea level becomes sea
    # level, in the mesh AND the grid. `depth` survives for the color pass only.
    m = np.maximum(raw, SEA)
    depth = np.clip(SEA - raw, 0.0, None)

    # ---- cosmetic chop. MESH ONLY — never in the grid (header note 4).
    if ripple:
        water = (raw < SEA).astype(np.float64)
        chop = (fbm(dirs * 46.0 + 13.7, 3, SEED + 61) - 0.5) * 2.0
        m = m + water * chop * RIPPLE_AMP

    # ---- level the settlement pans last, so a site always wins
    if flatten:
        for s in LAND_SITES:
            ac = np.arccos(np.clip(dirs @ s["dir"], -1.0, 1.0))
            t = 1.0 - smoothstep(s["ang"], s["ang"] * 1.9, ac)
            m = m * (1.0 - t) + s["h"] * t

    return m, {"depth": depth, "raw": raw, "elev": raw - 1.0, "z": z,
               "ang_ring": ang_ring, "land": land}

# auto-level each land site to its own island, exactly like CINDER's camps.
# Must run BEFORE any flatten=True call reads s["h"].
for _s in LAND_SITES:
    _hm, _ = height_field(_s["dir"][None, :], flatten=False)
    _s["h"] = float(_hm[0]) + 0.0012
    _above = (_s["h"] - SEA) * GAME_R
    print(f"  {_s['name']:<13} pan → {_s['h']:.5f}  ({_above:+.1f} game units above sea)")
    if _above < 4.0:
        print(f"  !! WARNING: {_s['name']} is within the lethal surf band — "
              f"raise its island in SITE_ISLANDS")


# ------------------------------------------------------------- THE FLEET --
# Sailing vessels, placed on OPEN WATER along the shipping lanes. Static
# geometry — but heeled over, varied in heading, and each one trailing a PAINTED
# wake. A wake implies motion hard enough that the eye stops noticing the hull
# isn't moving. Same trick as CINDER's painted ash-fall streak doing the job its
# cloud deck couldn't.
#
# They need no collision: they float on water that already kills you, so they
# physically cannot introduce a landing bug. They also double as ALTITUDE
# REFERENCES — skimming a featureless sea with lethal water below is
# disorienting, and a hull with a mast gives you something to judge height by.

def _is_water(d):
    m, _ = height_field(d[None, :], flatten=False)
    return float(m[0]) <= SEA + 1e-9

# shipping lanes: settlement → settlement great circles. Boats ride these, and
# the color pass paints them as worn tracks, so the traffic explains the lane.
LANES = [
    (LAND_SITES[0]["dir"], RIG_DIR),                    # Bulls Bay → Folly
    (LAND_SITES[0]["dir"], LAND_SITES[1]["dir"]),       # Bulls Bay → Shem
    (LAND_SITES[2]["dir"], LAND_SITES[0]["dir"]),       # Breach Inlet → Bulls Bay
    (RIG_DIR, LAND_SITES[2]["dir"]),                    # Folly → Breach Inlet
    (LAND_SITES[1]["dir"], BATTERY_DIR),                # Shem → The Battery
]

FLEET = []          # (dir, fwd_tangent, length_scale, kind, heel)
_frng = random.Random(SEED + 555)

# most of the fleet works the lanes
for A, B in LANES:
    for k in range(4):
        t = 0.16 + 0.68 * (k + _frng.uniform(-0.15, 0.15)) / 3.0
        d = slerp_dir(A, B, min(0.94, max(0.06, t)))
        jt1, jt2 = tangents(d)
        d = d + jt2 * _frng.uniform(-0.012, 0.012)
        d /= np.linalg.norm(d)
        if not _is_water(d):
            continue
        # heading roughly along the lane, wandering a bit
        along = B - d * float(d @ B)
        along /= np.linalg.norm(along)
        ang = _frng.uniform(-0.5, 0.5)
        t1, t2 = tangents(d)
        fwd = along * math.cos(ang) + np.cross(d, along) * math.sin(ang)
        fwd /= np.linalg.norm(fwd)
        kind = "salvage" if _frng.random() < 0.7 else "sloop"
        FLEET.append((d, fwd, _frng.uniform(0.85, 1.25), kind,
                      _frng.uniform(-0.22, 0.22)))

# a few loners out in open ocean
_tries = 0
while len(FLEET) < 26 and _tries < 400:
    _tries += 1
    d = ll_dir(math.degrees(math.asin(_frng.uniform(-0.86, 0.86))),
               _frng.uniform(-180, 180))
    if not _is_water(d):
        continue
    t1, t2 = tangents(d)
    a = _frng.uniform(0, 2 * math.pi)
    fwd = t1 * math.cos(a) + t2 * math.sin(a)
    FLEET.append((d, fwd, _frng.uniform(0.80, 1.15), "salvage",
                  _frng.uniform(-0.22, 0.22)))

# clean sloops moored off the capital — contrast against the working boats
_bb = LAND_SITES[0]
_bt1, _bt2 = tangents(_bb["dir"])
for k in range(3):
    d = step_along(_bb["dir"], _bt1 * math.cos(0.7 * k) + _bt2 * math.sin(0.7 * k),
                   _bb["ang"] * 1.6)
    if _is_water(d):
        t1, t2 = tangents(d)
        FLEET.append((d, t1, 0.8, "sloop", _frng.uniform(-0.10, 0.10)))

print(f"fleet: {len(FLEET)} vessels")


# ------------------------------------------------------------- COLOR PASS --
def hex_rgb(h):
    return np.array([(h >> 16 & 255) / 255.0, (h >> 8 & 255) / 255.0, (h & 255) / 255.0])

def lerp_col(a, b, t):
    t = t[:, None]
    return a[None, :] * (1 - t) + b[None, :] * t

def tint(base, color, t):
    t = t[:, None]
    return base * (1 - t) + color[None, :] * t

def arc_mask(dirs, A, B, width):
    """gaussian band along the great-circle arc A→B"""
    N = np.cross(A, B)
    n = np.linalg.norm(N)
    if n < 1e-9:
        return np.zeros(len(dirs))
    N = N / n
    mid = A + B
    mid = mid / np.linalg.norm(mid)
    half = math.acos(float(np.clip(A @ B, -1.0, 1.0))) * 0.5
    perp = np.abs(dirs @ N)
    along = np.arccos(np.clip(dirs @ mid, -1.0, 1.0))
    return (np.exp(-(perp / width) ** 2)
            * (1.0 - smoothstep(half * 0.85, half * 1.05, along)))

def face_colors(dirs, aux):
    """dirs: (F,3) unit face directions → (F,4) RGBA float colors"""
    depth, elev, z = aux["depth"], aux["elev"], aux["z"]

    # ---- WATER: the depth gradient. This is the single most important thing on
    # the planet — it's the only cue telling a pilot where solid ground starts,
    # on a world where guessing wrong is fatal. Deep water must read UNMISTAKABLY
    # different from reef shallows.
    dt = np.clip(depth / 0.026, 0.0, 1.0)          # 1 = abyss, 0 = waterline
    col = lerp_col(hex_rgb(PAL["reef"]), hex_rgb(PAL["shallow"]),
                   smoothstep(0.00, 0.10, dt))
    col = tint(col, hex_rgb(PAL["shelf"]),   smoothstep(0.08, 0.24, dt))
    col = tint(col, hex_rgb(PAL["ocean"]),   smoothstep(0.20, 0.42, dt))
    col = tint(col, hex_rgb(PAL["deep"]),    smoothstep(0.38, 0.68, dt))
    col = tint(col, hex_rgb(PAL["abyss"]),   smoothstep(0.66, 1.00, dt))

    # mottling so the open sea isn't a flat wash
    sea_n = fbm(dirs * 11.0 + 3.1, 4, SEED + 33)
    col = tint(col, hex_rgb(PAL["shelf"]), (depth > 0) * (sea_n - 0.5) * 0.10)

    # ---- KELP / AQUACULTURE GRIDS: rectilinear farm plots in the shallows near
    # each village. Painted only — costs nothing, and a grid is instantly read as
    # "somebody works here", which is what "densely occupied" actually looks like
    # from orbit.
    farm = np.zeros(len(dirs))
    for s in LAND_SITES:
        t1, t2 = tangents(s["dir"])
        u, v = dirs @ t1, dirs @ t2
        near = (1.0 - smoothstep(s["ang"] * 1.2, s["ang"] * 3.0,
                                 np.arccos(np.clip(dirs @ s["dir"], -1.0, 1.0))))
        g = (np.sin(u * 620.0) * np.sin(v * 620.0))
        farm = np.maximum(farm, near * smoothstep(0.25, 0.75, g))
    farm *= (depth > 0.0005) * (depth < 0.012)     # shallows only
    col = tint(col, hex_rgb(PAL["kelp"]), farm * 0.55)

    # ---- SHIPPING LANES: worn tracks between the ports. Broken up by noise and
    # kept faint — v1 painted them as hard straight spokes converging on Bulls
    # Bay, which read like scratches on the render rather than sea traffic.
    lane = np.zeros(len(dirs))
    for A, B in LANES:
        lane = np.maximum(lane, arc_mask(dirs, A, B, 0.0055))
    lane *= 0.35 + 1.05 * fbm(dirs * 20.0 + 5.5, 3, SEED + 91)
    col = tint(col, hex_rgb(PAL["lane"]), np.clip(lane, 0, 1) * (depth > 0) * 0.16)

    # ---- BOAT WAKES: a tapering streak behind every hull (see THE FLEET)
    wake = np.zeros(len(dirs))
    for d, fwd, ln, kind, heel in FLEET:
        tail = step_along(d, -fwd, 0.030 * ln)
        wake = np.maximum(wake, arc_mask(dirs, d, tail, 0.0016))
    col = tint(col, hex_rgb(PAL["wake"]), wake * (depth > 0) * 0.75)

    # ---- SURF: a foam ring hugging every waterline. Doubles as the fairness
    # cue — the bright band IS the "you are about to be over land" signal.
    # noise-modulated width so the foam ring is a broken surf line, not another
    # crisp iso-contour waiting to staircase on the lattice
    surf_w = 0.0014 + 0.0020 * fbm(dirs * 34.0 + 2.9, 3, SEED + 98)
    surf = (1.0 - smoothstep(0.0, 1.0, depth / surf_w)) * (depth > 0)
    col = tint(col, hex_rgb(PAL["surf"]), surf * 0.65)

    # ---- LAND: beach → scrub → green → rock by elevation
    lt = np.clip((elev - (SEA - 1.0)) / 0.030, 0.0, 1.0)
    is_land = (elev > (SEA - 1.0)).astype(np.float64)
    land_col = lerp_col(hex_rgb(PAL["sand"]), hex_rgb(PAL["scrub"]),
                        smoothstep(0.02, 0.12, lt))
    land_col = tint(land_col, hex_rgb(PAL["green"]),   smoothstep(0.10, 0.34, lt))
    land_col = tint(land_col, hex_rgb(PAL["greenDk"]), smoothstep(0.30, 0.58, lt))
    land_col = tint(land_col, hex_rgb(PAL["rock"]),    smoothstep(0.55, 0.80, lt))
    land_col = tint(land_col, hex_rgb(PAL["rockHi"]),  smoothstep(0.78, 1.00, lt))
    # canopy mottle so the greens aren't flat
    veg = fbm(dirs * 22.0 + 8.8, 4, SEED + 47)
    land_col = tint(land_col, hex_rgb(PAL["greenDk"]),
                    smoothstep(0.52, 0.78, veg) * 0.45)
    col = col * (1 - is_land)[:, None] + land_col * is_land[:, None]

    # ---- poles: cold, dark water. NO ICE — see header note 3.
    col = tint(col, hex_rgb(PAL["polar"]),
               smoothstep(0.88, 0.99, np.abs(z)) * (depth > 0) * 0.55)

    # ---- settlement pans, painted last so they override everything. The edge
    # is FEATHERED wide — a hard cut reads as a dinner plate dropped on the
    # island rather than ground that's been worked.
    for s in LAND_SITES:
        ac = np.arccos(np.clip(dirs @ s["dir"], -1.0, 1.0))
        col = tint(col, hex_rgb(PAL["pan"]),
                   (1.0 - smoothstep(s["ang"] * 0.50, s["ang"] * 1.06, ac)) * 0.88)

    # Per-face brightness jitter — what makes low-poly read as rich. Keyed to
    # DIRECTION, not face index: the hi-res atoll patch has ~2.4x finer faces
    # than the base mesh, and index-keyed jitter gave it a visibly different
    # grain that outlined the patch as a faint disc out in open water.
    col *= (1.0 + snoise(dirs * 150.0 + 31.0, 1, SEED + 5)[:, None] * 0.055)
    col = np.clip(col, 0.0, 1.0)

    return np.concatenate([col, np.ones((len(dirs), 1))], axis=1)


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
print("building terrain sphere…")
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=SUBDIV, radius=R)
planet = bpy.context.active_object
planet.name = "Azure"
me = planet.data

nv = len(me.vertices)
co = np.empty(nv * 3)
me.vertices.foreach_get("co", co)
co = co.reshape(-1, 3)
dirs = co / np.linalg.norm(co, axis=1)[:, None]

# ripple=True: the visible mesh gets chop. The grid bake below does NOT.
vm, _ = height_field(dirs, ripple=True)
vpos = dirs * (R * vm)[:, None]
me.vertices.foreach_set("co", vpos.ravel())
me.update()

# ---- cut a hole for the hi-res atoll patch (see below) BEFORE colouring, so
# the colour attribute is built against the final face list
PATCH_ANG  = RING_R * 1.30    # patch reaches this far out from the atoll centre
PATCH_CUT  = PATCH_ANG * 0.90 # base faces inside this are removed → 10% overlap
PATCH_N    = 120              # cells across the patch
PATCH_LIFT = 0.03             # BU the patch floats over the base (0.4 game units)

bm = bmesh.new()
bm.from_mesh(me)
bm.faces.ensure_lookup_table()
_rd_v, _cos_cut = Vector(RING_DIR.tolist()), math.cos(PATCH_CUT)
_kill = [f for f in bm.faces
         if f.calc_center_median().normalized().dot(_rd_v) > _cos_cut]
bmesh.ops.delete(bm, geom=_kill, context='FACES')
bm.to_mesh(me)
bm.free()
me.update()
print(f"  cut {len(_kill)} base faces to make room for the atoll patch")

nf = len(me.polygons)
centers = np.empty(nf * 3)
me.polygons.foreach_get("center", centers)
centers = centers.reshape(-1, 3)
fdirs = centers / np.linalg.norm(centers, axis=1)[:, None]
fm, faux = height_field(fdirs)
cols = face_colors(fdirs, faux)

_land_frac = 100.0 * float((faux["depth"] <= 0).sum()) / nf
print(f"  land coverage: {_land_frac:.1f}% of the base mesh")

attr = me.color_attributes.new(name="Col", type='FLOAT_COLOR', domain='CORNER')
attr.data.foreach_set("color", np.repeat(cols, 3, axis=0).ravel())

bpy.ops.object.shade_flat()
terrain_mat = make_material("Terrain", vertex_colors=True, roughness=0.55)
me.materials.append(terrain_mat)

# ------------------------------------------------------ HI-RES ATOLL PATCH --
# THE RING is the hero feature, and it is a big, smooth, CLOSED CURVE — the one
# shape that exposes the base mesh's resolution. At subdiv 7 the atoll is only
# ~12 faces in radius, and a thresholded ring that coarse renders as a HEXAGON
# no matter how the noise is tuned. Three iterations proved that the hard way
# (the baked height grid was a clean ring the entire time — the artifact was
# always flat-shaded colour on a coarse triangular lattice, never the math).
#
# The checklist's rule is "local hi-res patches, NOT global subdiv 8". So: a
# denser mesh covering just the atoll, laid over the hole cut above.
#
# Why there is no visible seam: the patch border sits out in OPEN WATER, where
# height_field() clamps everything to exactly SEA. Patch and base therefore
# agree to the micron precisely where they meet — the one place on this planet
# where two different sampling densities are guaranteed to produce the same
# answer. That is also why the overlap ring is safe: nothing can poke through
# flat water.
#
# The height GRID is untouched. It bakes from height_field() directly and has
# never depended on mesh resolution at all.
print("  building the hi-res atoll patch…")
_pt1, _pt2 = tangents(RING_DIR)
_lin = np.linspace(-1.0, 1.0, PATCH_N + 1)
_gu, _gv = np.meshgrid(_lin, _lin, indexing='ij')
_tanr = math.tan(PATCH_ANG)
_pdir = (RING_DIR[None, None, :]
         + _pt1[None, None, :] * (_gu * _tanr)[..., None]
         + _pt2[None, None, :] * (_gv * _tanr)[..., None])
_pdir = _pdir / np.linalg.norm(_pdir, axis=-1, keepdims=True)
_pflat = _pdir.reshape(-1, 3)
_pm, _ = height_field(_pflat, ripple=True)
_pverts = _pflat * (R * _pm + PATCH_LIFT)[:, None]

# (t1, t2, d) is right-handed — cross(t1, t2) == d — so this winding faces out
_angc = np.arccos(np.clip(_pflat @ RING_DIR, -1.0, 1.0)).reshape(PATCH_N + 1, -1)
_tris = []
for i in range(PATCH_N):
    for j in range(PATCH_N):
        if max(_angc[i, j], _angc[i + 1, j],
               _angc[i, j + 1], _angc[i + 1, j + 1]) > PATCH_ANG:
            continue                      # trim the square grid to a disc
        a = i * (PATCH_N + 1) + j
        b = (i + 1) * (PATCH_N + 1) + j
        c = (i + 1) * (PATCH_N + 1) + j + 1
        d = i * (PATCH_N + 1) + j + 1
        _tris.append((a, b, c))
        _tris.append((a, c, d))

_pmesh = bpy.data.meshes.new("RingPatchMesh")
_pmesh.from_pydata(_pverts.tolist(), [], _tris)
_pmesh.update()
patch = bpy.data.objects.new("RingPatch", _pmesh)
bpy.context.collection.objects.link(patch)

_ta = np.array(_tris)
_pc = _pverts[_ta].mean(axis=1)
_pfd = _pc / np.linalg.norm(_pc, axis=1)[:, None]
_, _pfaux = height_field(_pfd)
_pcols = face_colors(_pfd, _pfaux)
_pattr = _pmesh.color_attributes.new(name="Col", type='FLOAT_COLOR', domain='CORNER')
_pattr.data.foreach_set("color", np.repeat(_pcols, 3, axis=0).ravel())
_pmesh.materials.append(terrain_mat)

bpy.ops.object.select_all(action='DESELECT')
bpy.context.view_layer.objects.active = patch
patch.select_set(True)
bpy.ops.object.shade_flat()
patch.select_set(False)
_base_edge = math.sqrt(4 * math.pi * R * R / 81920.0)
print(f"  patch: {len(_tris)} tris, cell ≈ {2 * _tanr * R / PATCH_N:.2f} BU "
      f"vs base ≈ {_base_edge:.2f} BU ({_base_edge / (2 * _tanr * R / PATCH_N):.1f}x finer)")


# ------------------------------------------------------ STRUCTURE HELPERS --
def surf_quat(d, fwd):
    """local +Z → surface normal d, +X → fwd projected into the tangent plane"""
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

def _ico(base_pt, rot, off, scale, mat, objs, subd=1):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=subd, radius=1.0,
                                          location=base_pt + rot @ Vector(off))
    b = bpy.context.active_object
    b.scale = Vector(scale)
    b.rotation_mode = 'QUATERNION'; b.rotation_quaternion = rot
    b.data.materials.append(mat); objs.append(b); return b

def join_as(objs, name):
    """collapse a pile of primitives into one named object"""
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

metalA = make_material("MetalA", color_hex=PAL["metalA"], roughness=0.85)
metalB = make_material("MetalB", color_hex=PAL["metalB"], roughness=0.75)
metalC = make_material("MetalC", color_hex=PAL["metalC"], roughness=0.90)
rust_m = make_material("Rust",   color_hex=PAL["rust"],   roughness=0.95)
steel  = make_material("Steel",  color_hex=PAL["steel"],  roughness=0.40)
timber = make_material("Timber", color_hex=PAL["timber"], roughness=0.95)
dock_m = make_material("Dock",   color_hex=PAL["dock"],   roughness=0.92)
hullW  = make_material("HullW",  color_hex=PAL["hullW"],  roughness=0.45)
hullR  = make_material("HullR",  color_hex=PAL["hullR"],  roughness=0.80)
hullB  = make_material("HullB",  color_hex=PAL["hullB"],  roughness=0.55)
canvas = make_material("Canvas", color_hex=PAL["canvas"], roughness=0.95)
canvasP= make_material("CanvasP",color_hex=PAL["canvasP"],roughness=0.98)
amber  = make_material("Amber",  color_hex=PAL["amber"],
                       emission_hex=PAL["amber"], strength=3.0)
greenL = make_material("GreenL", color_hex=PAL["green_l"],
                       emission_hex=PAL["green_l"], strength=3.0)
redL   = make_material("RedL",   color_hex=PAL["red_l"],
                       emission_hex=PAL["red_l"], strength=3.2)


# ---------------------------------------------------------- SETTLEMENTS --
print("raising the settlements…")

def make_port(base_pt, rot, fx, fy, h, rng, objs):
    """BULLS BAY — a working capital. Warehouses, cranes, tanks, terraces."""
    k = rng.random()
    if k < 0.30:
        # warehouse / shed with a pitched roof
        _box(base_pt, rot, (0, 0, h * 0.5), (fx, fy, h),
             rng.choice([metalA, metalB, timber]), objs)
        _cone(base_pt, rot, (0, 0, h + fy * 0.22), fx * 0.80, 0.0, fy * 0.44,
              rust_m, objs, verts=4)
    elif k < 0.50:
        # terraced block — stacked setbacks running up the slope
        for t in range(rng.randint(2, 4)):
            s = 1.0 - t * 0.22
            _box(base_pt, rot, (0, 0, h * (0.5 + t * 0.85)),
                 (fx * s, fy * s, h), rng.choice([metalA, metalC]), objs)
    elif k < 0.64:
        # storage tank
        _cyl(base_pt, rot, (0, 0, h * 0.6), fx * 0.48, h * 1.2, metalB, objs, verts=12)
        _cyl(base_pt, rot, (0, 0, h * 1.22), fx * 0.48, h * 0.06, steel, objs, verts=12)
    elif k < 0.70:
        # Harbour crane — tower, jib, counterweight.
        # Two things v1 got wrong and made the whole port look like a dropped
        # box of scaffolding poles: the jib was fx*2.6 long (≈58 game units off
        # a 20-unit shed), and its OFFSET was passed through the rotated
        # quaternion, so it swung out to an arbitrary spot instead of sitting on
        # top of its own tower. Place with `rot`, then override the axis.
        th = h * 1.8
        _cyl(base_pt, rot, (0, 0, th * 0.5), 0.09 * MS, th, metalC, objs, verts=8)
        jib = _cyl(base_pt, rot, (fx * 0.45, 0, th), 0.045 * MS, fx * 1.4,
                   steel, objs, verts=6)
        jib.rotation_quaternion = rot @ Matrix.Rotation(math.pi / 2, 4,
                                                        'Y').to_quaternion()
        _box(base_pt, rot, (-fx * 0.30, 0, th),
             (fx * 0.26, fy * 0.26, h * 0.24), metalB, objs)
    elif k < 0.94:
        # dockside shack with a lit window
        _box(base_pt, rot, (0, 0, h * 0.45), (fx * 0.8, fy * 0.8, h * 0.9),
             timber, objs)
        _box(base_pt, rot, (fx * 0.41, 0, h * 0.55),
             (0.03 * MS, fy * 0.30, h * 0.26), amber, objs)
    else:
        # Comms / light mast. Was h*3.0 (≈50 game units) at 12% frequency, and
        # a dozen of them turned the skyline into a pincushion of poles. Half
        # the height, half as many.
        _cyl(base_pt, rot, (0, 0, h * 0.8), 0.05 * MS, h * 1.6, metalC, objs, verts=6)
        _ico(base_pt, rot, (0, 0, h * 1.64), (0.09 * MS,) * 3, redL, objs)

def make_stilt(base_pt, rot, fx, fy, h, rng, objs):
    """SHEM / BREACH INLET — stilt villages. Everything stands on legs."""
    legh = h * 1.1
    for sx in (-1, 1):
        for sy in (-1, 1):
            _cyl(base_pt, rot, (sx * fx * 0.38, sy * fy * 0.38, legh * 0.5),
                 0.045 * MS, legh, timber, objs, verts=6)
    k = rng.random()
    if k < 0.55:
        # hut on the platform
        _box(base_pt, rot, (0, 0, legh + h * 0.40), (fx, fy, h * 0.80),
             rng.choice([timber, rust_m, metalA]), objs)
        _cone(base_pt, rot, (0, 0, legh + h * 0.86), fx * 0.82, 0.0, fy * 0.40,
              rust_m, objs, verts=4)
    elif k < 0.78:
        # open drying rack — frame + hanging nets
        _box(base_pt, rot, (0, 0, legh + 0.02 * MS), (fx, fy, 0.05 * MS),
             dock_m, objs)
        for r in range(3):
            _box(base_pt, rot, (fx * (r - 1) * 0.5, 0, legh + h * 0.45),
                 (0.035 * MS, fy * 0.9, h * 0.8), timber, objs)
    else:
        # water tank on legs
        _cyl(base_pt, rot, (0, 0, legh + h * 0.42), fx * 0.42, h * 0.85,
             metalB, objs, verts=10)
    # a lit lantern on roughly a third of them
    if rng.random() < 0.34:
        _ico(base_pt, rot, (fx * 0.45, fy * 0.45, legh + h * 0.95),
             (0.055 * MS,) * 3, amber, objs)

BUILDERS = {"port": make_port, "stilt": make_stilt}

for site in LAND_SITES:
    cd = Vector(site["dir"].tolist())
    t1 = cd.cross(Vector((0, 0, 1))).normalized()
    t2 = cd.cross(t1)
    ground = R * site["h"]
    cr = site["ang"] * R
    step = 0.66 * MS
    rng2 = random.Random(SEED + sum(ord(ch) for ch in site["name"]))
    build = BUILDERS[site["kind"]]
    parts = []
    n = int(math.ceil(cr / step))
    apron_x = cr * 0.42          # keep the +t1 edge clear as a landing apron

    # Collect every legal cell FIRST, then shuffle and take what we need.
    # v1 walked the grid in order and stopped once it hit `structures`, which
    # packed all 58 of Bulls Bay's buildings into the first four columns and
    # left two thirds of the pan bare. Shuffling spreads them over the site.
    cells = []
    for gi in range(-n, n + 1):
        for gj in range(-n, n + 1):
            u = gi * step + rng2.uniform(-0.22 * MS, 0.22 * MS)
            v = gj * step + rng2.uniform(-0.22 * MS, 0.22 * MS)
            if math.hypot(u, v) > cr * 0.86:
                continue
            if u > apron_x:
                continue
            cells.append((u, v))
    rng2.shuffle(cells)
    if len(cells) < site["structures"]:
        print(f"  !! {site['name']}: only {len(cells)} cells for "
              f"{site['structures']} structures — widen ang or shrink step")
    for u, v in cells[:site["structures"]]:
        d = (cd * R + t1 * u + t2 * v).normalized()
        fx, fy = rng2.uniform(0.38, 0.70) * MS, rng2.uniform(0.38, 0.70) * MS
        hh = rng2.uniform(0.24, 0.52) * MS
        build(d * ground, surf_quat(d, t1), fx, fy, hh, rng2, parts)
    built = min(len(cells), site["structures"])

    # ---- waterfront: a pier running off the seaward edge, with channel
    # markers. This is what makes a cluster of boxes read as a PORT.
    cq = surf_quat(cd, t1)
    cbase = cd * ground
    pier_dir = -t2
    for pi in range(6):
        off = pier_dir * (cr * (0.55 + pi * 0.13))
        p = (cd * R + off).normalized()
        _box(p * ground, surf_quat(p, t1), (0, 0, 0.03 * MS),
             (0.55 * MS, 0.22 * MS, 0.06 * MS), dock_m, parts)
        if pi % 2 == 0:
            _cyl(p * ground, surf_quat(p, t1), (0, 0, -0.30 * MS),
                 0.05 * MS, 0.70 * MS, timber, parts, verts=6)
    # channel markers at the pier head — green to starboard, red to port
    head = (cd * R + pier_dir * (cr * 1.40)).normalized()
    for sgn, m_ in ((1, greenL), (-1, redL)):
        mk = (head * R + t1 * (0.9 * MS) * sgn).normalized()
        _cyl(mk * (R * SEA), surf_quat(mk, t1), (0, 0, 0.35 * MS),
             0.05 * MS, 0.70 * MS, metalC, parts, verts=6)
        _ico(mk * (R * SEA), surf_quat(mk, t1), (0, 0, 0.74 * MS),
             (0.075 * MS,) * 3, m_, parts)

    join_as(parts, site["name"].replace(" ", ""))
    print(f"  {site['name']}: {built} structures")


# ------------------------------------------------------------ FOLLY (RIG) --
# The hero landing. A salvage platform on pylons in THE RING's lagoon. The deck
# is the ONLY safe surface for hundreds of units in every direction.
#
# The pad cone in BODIES is deliberately SMALLER than the deck (see the printout
# at the end): a cone WIDER than the deck would let you "land" on invisible
# ground out over open water. Undershooting the deck edge should kill you —
# that's the point of the place.
print("building Folly (the rig)…")
rd = Vector(RIG_DIR.tolist())
rt1 = rd.cross(Vector((0, 0, 1))).normalized()
rt2 = rd.cross(rt1)
sea_pt = rd * (R * SEA)
rq = surf_quat(rd, rt1)
DECK_R = RIG["deck_r"]
DECK_Z = R * RIG["deck_top"]        # deck top above sea, in Blender units
rig_parts = []

# pylons down into the water
for pk in range(8):
    a = pk * math.pi / 4.0
    off = (rt1 * math.cos(a) + rt2 * math.sin(a)) * (DECK_R * 0.78)
    p = sea_pt + off
    _cyl(p, rq, (0, 0, DECK_Z * 0.5 - 0.5), 0.16 * MS, DECK_Z + 1.0,
         metalC, rig_parts, verts=8)
# cross-bracing
for pk in range(8):
    a0, a1 = pk * math.pi / 4.0, (pk + 1) * math.pi / 4.0
    p0 = sea_pt + (rt1 * math.cos(a0) + rt2 * math.sin(a0)) * (DECK_R * 0.78)
    p1 = sea_pt + (rt1 * math.cos(a1) + rt2 * math.sin(a1)) * (DECK_R * 0.78)
    mid = (p0 + p1) * 0.5 + rd * (DECK_Z * 0.45)
    span = (p1 - p0).length
    bq = surf_quat((mid - rd * 0).normalized(), (p1 - p0).normalized())
    bq = bq @ Matrix.Rotation(math.pi / 2, 4, 'Y').to_quaternion()
    bpy.ops.mesh.primitive_cylinder_add(vertices=6, radius=0.06 * MS,
                                        depth=span, location=mid)
    br = bpy.context.active_object
    br.rotation_mode = 'QUATERNION'; br.rotation_quaternion = bq
    br.data.materials.append(rust_m); rig_parts.append(br)

# THE DECK — an octagonal slab. This is the landing surface.
_cyl(sea_pt, rq, (0, 0, DECK_Z - 0.10), DECK_R, 0.22, metalA, rig_parts, verts=8)
_cyl(sea_pt, rq, (0, 0, DECK_Z + 0.01), DECK_R * 0.97, 0.03, metalB,
     rig_parts, verts=8)

# deck gear, all pushed to ONE side so the landing half stays clear
deck_base = sea_pt + rd * DECK_Z
rrng = random.Random(SEED + 909)
for gk in range(14):
    a = rrng.uniform(math.pi * 0.35, math.pi * 1.15)
    rr = rrng.uniform(0.30, 0.80) * DECK_R
    off = (rt1 * math.cos(a) + rt2 * math.sin(a)) * rr
    p = deck_base + off
    kind = rrng.random()
    if kind < 0.40:
        # shipping containers, stacked and rusting
        for st in range(rrng.randint(1, 3)):
            _box(p, rq, (0, 0, 0.20 * MS + st * 0.40 * MS),
                 (0.90 * MS, 0.42 * MS, 0.38 * MS),
                 rrng.choice([rust_m, metalB, hullR]), rig_parts)
    elif kind < 0.62:
        _cyl(p, rq, (0, 0, 0.34 * MS), 0.26 * MS, 0.68 * MS, metalB,
             rig_parts, verts=10)
    elif kind < 0.80:
        _box(p, rq, (0, 0, 0.30 * MS), (0.60 * MS, 0.55 * MS, 0.60 * MS),
             metalA, rig_parts)
        _box(p, rq, (0.31 * MS, 0, 0.34 * MS),
             (0.03 * MS, 0.20 * MS, 0.18 * MS), amber, rig_parts)
    else:
        # scrap heap
        for sk in range(4):
            _ico(p, rq, (rrng.uniform(-0.3, 0.3) * MS, rrng.uniform(-0.3, 0.3) * MS,
                         0.14 * MS),
                 (rrng.uniform(0.10, 0.22) * MS,) * 3, rust_m, rig_parts)

# the derrick — the rig's silhouette, and your visual fix on final approach.
# v1 stood it 3.0*MS tall (≈96 game units) and it dwarfed the 40u deck like a
# radio tower on a dinner plate. Half that reads as rig gear, not a landmark.
dq = rq
_cyl(deck_base, dq, (-DECK_R * 0.60, 0, 0.75 * MS), 0.10 * MS, 1.5 * MS,
     metalC, rig_parts, verts=6)
for lk in range(3):
    _box(deck_base, dq, (-DECK_R * 0.60, 0, (0.30 + lk * 0.45) * MS),
         (0.34 * MS, 0.34 * MS, 0.035 * MS), steel, rig_parts)
_ico(deck_base, dq, (-DECK_R * 0.60, 0, 1.56 * MS), (0.09 * MS,) * 3,
     redL, rig_parts)

# perimeter hazard lights — the thing you actually aim at coming in
for pk in range(8):
    a = pk * math.pi / 4.0 + math.pi / 8.0
    off = (rt1 * math.cos(a) + rt2 * math.sin(a)) * (DECK_R * 0.93)
    _ico(deck_base + off, rq, (0, 0, 0.10 * MS), (0.065 * MS,) * 3,
         amber if pk % 2 == 0 else redL, rig_parts)

join_as(rig_parts, "Folly")


# --------------------------------------------------------------- THE FLEET --
print("launching the fleet…")

def make_boat(d, fwd, ln, kind, heel, objs):
    """One sailing vessel. Hull sits DRAFT below sea level so the cosmetic
    ripple never leaves it hovering over a trough (header note 4)."""
    dv = Vector(d.tolist())
    fv = Vector(fwd.tolist())
    base = dv * (R * (SEA - BOAT_DRAFT))
    q = surf_quat(dv, fv)
    # heel: lean the whole boat about its own forward axis
    q = q @ Matrix.Rotation(heel, 4, 'X').to_quaternion()

    # v1 was too fine-lined — a thin low hull under big white sails read as a
    # paper dart, not a boat. Beamier and more freeboard so the HULL carries the
    # silhouette and the sails just sit on top of it.
    L = 1.26 * ln          # hull length in Blender units → ~18 game units
    W = 0.44 * ln
    H = 0.28 * ln
    hm = {"salvage": hullR, "sloop": hullW}[kind]
    sm = {"salvage": canvasP, "sloop": canvas}[kind]

    # hull: a box for the body, a tapered cone for the bow.
    # Rotation(+π/2,'Y') maps local +Z onto local +X, so the cone's TIP points
    # forward. v1 used -π/2 and every boat in the fleet sailed stern-first.
    _box(base, q, (0, 0, H * 0.5), (L * 0.72, W, H), hm, objs)
    _cone(base, q, (L * 0.50, 0, H * 0.5), W * 0.52, 0.0, L * 0.34,
          hm, objs, verts=6).rotation_quaternion = (
              q @ Matrix.Rotation(math.pi / 2, 4, 'Y').to_quaternion())
    # deck + a small cabin
    _box(base, q, (0, 0, H * 1.02), (L * 0.70, W * 0.94, H * 0.10), timber, objs)
    _box(base, q, (-L * 0.16, 0, H * 1.28), (L * 0.24, W * 0.62, H * 0.42),
         timber if kind == "salvage" else hullW, objs)
    # mast + sails. Sails pulled in from v1 (0.30→0.24 base, 0.80→0.68 hoist)
    # so they read as canvas ON a boat instead of two loose paper triangles.
    MH = 0.92 * ln         # ~13 game units
    _cyl(base, q, (L * 0.06, 0, H + MH * 0.5), 0.026 * ln, MH, timber, objs, verts=6)
    # mainsail: a flattened triangular sheet, bellied to leeward
    sail = _cone(base, q, (L * 0.06 - MH * 0.10, W * 0.26, H + MH * 0.40),
                 MH * 0.24, 0.0, MH * 0.68, sm, objs, verts=3)
    sail.scale = Vector((1.0, 0.14, 1.0))
    # jib, forward of the mast
    jib = _cone(base, q, (L * 0.32, W * 0.17, H + MH * 0.28),
                MH * 0.15, 0.0, MH * 0.46, sm, objs, verts=3)
    jib.scale = Vector((1.0, 0.14, 1.0))
    if kind == "salvage":
        # deck crane + a couple of lashed drums — these are working boats
        _cyl(base, q, (-L * 0.34, 0, H + 0.16 * ln), 0.028 * ln, 0.32 * ln,
             rust_m, objs, verts=6)
        for dk in (-1, 1):
            _cyl(base, q, (-L * 0.30, dk * W * 0.32, H * 1.20), 0.055 * ln,
                 0.14 * ln, metalB, objs, verts=8)
    # stern lantern — boats are lit at night, which sells "inhabited"
    _ico(base, q, (-L * 0.40, 0, H * 1.30), (0.045 * ln,) * 3, amber, objs)

boat_parts = []
for d, fwd, ln, kind, heel in FLEET:
    make_boat(d, fwd, ln, kind, heel, boat_parts)

# ---- THE BATTERY: the wreck field. Same hulls, but broken — one capsized with
# its mast in the water, the rest stranded on the shallow bank. A landmark, and
# an obvious "somebody should salvage that" hook.
bd = BATTERY_DIR
bt1, bt2 = tangents(bd)
wrng = random.Random(SEED + 777)
for wk in range(5):
    a = wrng.uniform(0, 2 * math.pi)
    off = (bt1 * math.cos(a) + bt2 * math.sin(a)) * wrng.uniform(0.006, 0.026)
    d = bd + off
    d /= np.linalg.norm(d)
    fa = wrng.uniform(0, 2 * math.pi)
    t1, t2 = tangents(d)
    fwd = t1 * math.cos(fa) + t2 * math.sin(fa)
    # capsize the first one hard; list the others
    heel = (math.pi * 0.62) if wk == 0 else wrng.uniform(-0.75, 0.75)
    make_boat(d, fwd, wrng.uniform(0.9, 1.3), "salvage", heel, boat_parts)

join_as(boat_parts, "Boats")
print(f"  {len(FLEET)} working vessels + 5 wrecks at The Battery")


# ------------------------------------------------------------- THE CLOUDS --
# A low, flat weather deck (the EARTH fix: 1.04–1.06 R, squashed in Z) PLUS
# THE EYE — a logarithmic spiral of blobs with a clear centre. White on deep
# blue is exactly the case low-poly cloud blobs handle well; CINDER's failure
# was the opposite (opaque blobs on near-black).
print("puffing clouds + winding up The Eye…")
random.seed(SEED)
cloud_mat = make_material("Cloud", color_hex=PAL["cloud"],
                          emission_hex=PAL["cloud"], strength=0.10, roughness=1.0)
cloud_objs = []

def cloud_blob(pos, quat, sx, sy, sz):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1.0, location=pos)
    b = bpy.context.active_object
    b.rotation_mode = 'QUATERNION'; b.rotation_quaternion = quat
    b.scale = (sx, sy, sz)
    cloud_objs.append(b)
    return b

# ordinary weather — kept off the rig so FOLLY's approach stays visible
systems, attempts = 0, 0
while systems < 16 and attempts < 260:
    attempts += 1
    u, v = random.random(), random.random()
    theta, phi = 2 * math.pi * u, math.acos(2 * v - 1)
    d = Vector((math.sin(phi) * math.cos(theta),
                math.sin(phi) * math.sin(theta), math.cos(phi)))
    if d.dot(Vector(RIG_DIR.tolist())) > math.cos(0.30):
        continue
    if d.dot(Vector(EYE_DIR.tolist())) > math.cos(EYE_R * 2.0):
        continue                       # the storm owns its own sky
    systems += 1
    quat = Vector((0, 0, 1)).rotation_difference(d)
    tan1 = d.cross(Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((1, 0, 0))).normalized()
    tan2 = d.cross(tan1)
    for _ in range(random.randint(3, 6)):
        off = tan1 * random.uniform(-7, 7) + tan2 * random.uniform(-4, 4)
        pos = d * (R * random.uniform(1.04, 1.06)) + off
        cloud_blob(pos, quat, random.uniform(4.0, 8.5),
                   random.uniform(3.0, 6.0), random.uniform(0.8, 1.5))

# ---- THE EYE. Four arms on a log spiral, thickening outward, with a hole in
# the middle you can actually fly down through.
ed = Vector(EYE_DIR.tolist())
et1 = ed.cross(Vector((0, 0, 1))).normalized()
et2 = ed.cross(et1)
equat = Vector((0, 0, 1)).rotation_difference(ed)
EYE_HOLE = EYE_R * 0.16
# 5 arms, not 4, each jittered in twist/length/thickness. Perfect N-fold
# symmetry is what made v1's atoll read as a hexagon; a storm with four
# identical arms has the same problem — it looks like a camera shutter.
_erng = random.Random(SEED + 404)
for arm in range(5):
    a0 = arm * (2.0 * math.pi / 5.0) + _erng.uniform(-0.16, 0.16)
    twist = 2.5 + _erng.uniform(-0.35, 0.35)
    reach = 1.0 + _erng.uniform(-0.10, 0.06)
    steps = 16
    for si in range(steps):
        t = si / (steps - 1.0)
        ang = EYE_HOLE + (EYE_R * reach - EYE_HOLE) * (t ** 0.85)
        sweep = a0 + t * twist
        dirv = ed * math.cos(ang) + (et1 * math.cos(sweep) +
                                     et2 * math.sin(sweep)) * math.sin(ang)
        dirv.normalize()
        # arms get wider as they wrap outward, but stay FLAT — a storm should
        # be a spiral of cloud decks, not a stack of dumplings
        w = (3.2 + 7.0 * t) * _erng.uniform(0.86, 1.14)
        pos = dirv * (R * (1.045 + 0.010 * (1.0 - t)))
        # orient the blob along the arm so it reads as a band, not a bead
        tang = (et1 * -math.sin(sweep) + et2 * math.cos(sweep))
        cloud_blob(pos, surf_quat(dirv, tang), w,
                   (1.8 + 2.2 * t) * _erng.uniform(0.85, 1.15),
                   0.50 + 0.35 * t)
# a tight wall right around the eye — what makes the hole read as a hole
for wk in range(12):
    a = wk * math.pi / 6.0
    dirv = (ed * math.cos(EYE_HOLE * 1.35) +
            (et1 * math.cos(a) + et2 * math.sin(a)) * math.sin(EYE_HOLE * 1.35))
    dirv.normalize()
    tang = (et1 * -math.sin(a) + et2 * math.cos(a))
    cloud_blob(dirv * (R * 1.052), surf_quat(dirv, tang), 2.6, 1.4, 1.5)

clouds = join_as(cloud_objs, "Clouds")
clouds.data.materials.append(cloud_mat)
# origin must be the PLANET CENTER — the game spins this node, and a spin about
# anything else flings the whole deck sideways
bpy.ops.object.select_all(action='DESELECT')
clouds.select_set(True)
bpy.context.view_layer.objects.active = clouds
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
bpy.ops.object.select_all(action='DESELECT')


# ------------------------------------------------------------ EXPORT GLB --
glb_path = os.path.join(OUT, "azure.glb")
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=glb_path, export_format='GLB')
print(f"wrote {glb_path}")


# ----------------------------------------------------- EXPORT HEIGHT GRID --
# ripple=False — the grid is authoritative and must stay dead flat over water
# (header note 4). 1280x640 → ~7u cells at AZURE's 1425u game radius.
print("baking height grid…")
GW, GH = 1280, 640
gy, gx = np.mgrid[0:GH, 0:GW]
lon = (gx + 0.5) / GW * 2 * np.pi - np.pi
lat = np.pi / 2 - (gy + 0.5) / GH * np.pi
gdirs = np.stack([np.cos(lat) * np.cos(lon),
                  np.cos(lat) * np.sin(lon),
                  np.sin(lat)], axis=-1).reshape(-1, 3)
gm, _ = height_field(gdirs, ripple=False)
lo, hi = float(gm.min()), float(gm.max())
q = np.round((gm - lo) / (hi - lo) * 255).astype(np.uint8)

with open(os.path.join(OUT, "azure_height.json"), "w") as f:
    json.dump({"w": GW, "h": GH, "min": lo, "max": hi,
               "b64": base64.b64encode(q.tobytes()).decode()}, f)
print(f"wrote azure_height.json  (height range {lo:.4f} … {hi:.4f})")

# ---- SANITY: the water test the game will run must actually separate water
# from land. Quantization is the risk — if `lo` is far below SEA, one uint8 step
# can be worth more than the 1-game-unit death threshold and the sea would
# quantize to something the test misses.
_step_game = (hi - lo) / 255.0 * GAME_R
print(f"  grid quantization step: {_step_game:.2f} game units per uint8 level")
_sea_q = round((SEA - lo) / (hi - lo) * 255)
_sea_back = lo + (hi - lo) * _sea_q / 255.0
print(f"  sea level {SEA:.4f} → uint8 {_sea_q} → decodes to {_sea_back:.5f} "
      f"({(_sea_back - SEA) * GAME_R:+.2f} game units)")
if abs(_sea_back - SEA) * GAME_R > 1.0:
    print("  !! sea level does not round-trip inside 1 game unit — widen the "
          "death epsilon in space-flight.html to match, or the surf will lie")


# --------------------------------------------------------------- PREVIEWS --
print("rendering previews (Cycles CPU)…")
scene.render.engine = 'CYCLES'
scene.cycles.samples = 16
scene.cycles.device = 'CPU'
scene.render.resolution_x = scene.render.resolution_y = 900
scene.view_settings.view_transform = 'Standard'

world = bpy.data.worlds.new("Space")
world.color = (0.004, 0.004, 0.006)
scene.world = world

def aim(obj, target):
    d = (target - obj.location).normalized()
    obj.rotation_mode = 'QUATERNION'
    obj.rotation_quaternion = d.to_track_quat('-Z', 'Y')

bpy.ops.object.light_add(type='SUN', location=(300, -300, 200))
sun = bpy.context.active_object
sun.data.energy = 3.2                  # a temperate world — softer than CINDER
aim(sun, Vector((0, 0, 0)))
bpy.ops.object.light_add(type='SUN', location=(-300, 300, -150))
fill = bpy.context.active_object
fill.data.energy = 0.45                # bounce off all that water
aim(fill, Vector((0, 0, 0)))

bpy.ops.object.camera_add()
cam = bpy.context.active_object
scene.camera = cam

def cam_over(lat, lon, dist, elev_deg, az_deg):
    """Camera `dist` out from the GROUND POINT at (lat,lon), `elev_deg` above
    the local horizon on bearing `az_deg`."""
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

# v2 shot Folly from 32° up and the vertical derrick projected almost flat —
# impossible to tell whether the rig was built right. Look DOWN at it instead.
_rig   = cam_over(RIG["lat"], RIG["lon"], 18, 58, 40)
_ring  = cam_over(RING_LAT, RING_LON, 62, 62, 25)     # the whole atoll + lagoon
_bulls = cam_over(-14, 62, 44, 40, 55)
_shem  = cam_over(26, 118, 30, 34, -70)
_batt  = cam_over(BATTERY_LAT, BATTERY_LON, 26, 26, 80)
_boat  = cam_over(float(math.degrees(math.asin(FLEET[0][0][2]))),
                  float(math.degrees(math.atan2(FLEET[0][0][1], FLEET[0][0][0]))),
                  9, 48, 60)

SHOTS = [
    ("azure_preview_a.png",       Vector(ll_dir(6, -35).tolist()) * 330,
                                  Vector((0, 0, 0)), 3.2, False),   # THE RING face
    ("azure_preview_b.png",       Vector(ll_dir(-18, 90).tolist()) * 330,
                                  Vector((0, 0, 0)), 3.2, False),   # far face
    ("azure_preview_eye.png",     Vector(ll_dir(EYE_LAT, EYE_LON).tolist()) * 250,
                                  Vector((0, 0, 0)), 3.2, False),   # the cyclone
    ("azure_preview_night.png",   Vector(ll_dir(-10, 60).tolist()) * 300,
                                  Vector((0, 0, 0)), 0.05, False),  # lit ports
    ("azure_preview_folly.png",   _rig[0],   _rig[1],   3.0, True),
    ("azure_preview_ring.png",    _ring[0],  _ring[1],  3.0, True),
    ("azure_preview_bullsbay.png",_bulls[0], _bulls[1], 3.0, True),
    ("azure_preview_shem.png",    _shem[0],  _shem[1],  3.0, True),
    ("azure_preview_battery.png", _batt[0],  _batt[1],  3.0, True),
    ("azure_preview_boat.png",    _boat[0],  _boat[1],  3.0, True),
]
for fname, pos, target, energy, relight in SHOTS:
    sun.data.energy = energy
    fill.data.energy = 0.45 if energy > 1.0 else 0.02
    sun.location = light_for(target) if relight else SUN_HOME
    aim(sun, Vector((0, 0, 0)))
    cam.location = pos
    aim(cam, target)
    scene.render.filepath = os.path.join(OUT, "previews", fname)
    bpy.ops.render.render(write_still=True)
    print(f"wrote {fname}")

# ------------------------------------------------------- THE BODIES ENTRY --
# Printed so the numbers in space-flight.html can't drift from the numbers the
# mesh was actually built with.
print("\n" + "=" * 70)
print("BODIES entry for space-flight.html — copy these EXACT numbers:")
print("=" * 70)
print(f'    seaLevel: {SEA},          // water at or below this = shipBreach()')
_pad_ang = (DECK_R * 0.86) / R
print(f'    pads: [')
print(f'      // FOLLY — the rig deck. ang is 86% of the {DECK_R * SCALE:.0f}u deck '
      f'radius on purpose:')
print(f'      // the cone must never be WIDER than the deck or you land on air.')
print(f'      {{ lat: {RIG["lat"]}, lon: {RIG["lon"]}, ang: {_pad_ang:.4f}, '
      f'top: {SEA + RIG["deck_top"]:.4f} }},')
for s in LAND_SITES:
    print(f'      {{ lat: {s["lat"]}, lon: {s["lon"]}, ang: {s["ang"] * 0.80:.4f}, '
          f'top: {s["h"]:.5f} }},   // {s["name"]} — top == the leveled pan')
print(f'    ],')
print(f'    spin: 0.003,   // was 0.015 — a parked ship RIDES the rotation')
print("=" * 70)

print("\nDONE — azure.glb + azure_height.json + previews")
