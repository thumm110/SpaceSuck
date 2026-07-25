"""
build_cinder.py — SpaceSuck planet factory, planet #3: CINDER
============================================================
The inner scorched world. A small, dark, molten rock that orbits close enough to
HELIOS that it never cooled off: black basalt highlands, gray ash plains, a
cratered face, and a network of GLOWING lava veins that light the night side.
The hero feature is THE MAW — a broad shield volcano with a lava lake sitting in
its caldera, big enough to fly down into.

Same machinery as build_earth.py / build_rubicon.py (edit the numbers, re-run
headless, get fresh files — the .blend is never saved):

    blender -b -P build_cinder.py

Outputs (written next to this script):
    cinder.glb           — the planet mesh: flat-shaded low-poly basalt with
                           per-face colors, a separate EMISSIVE lava mesh, two
                           industrial outposts, ash clouds, an eruption plume
    cinder_height.json   — 1280x640 lat/lon height grid (base64 uint8). The game
                           samples this for the EXACT ground height under the
                           ship — that's what makes landing work.
    cinder_preview_*.png — Cycles renders so you can eyeball it without Blender

--------------------------------------------------------------------------
TWO THINGS THAT ARE DIFFERENT FROM EARTH/RUBICON — read before editing
--------------------------------------------------------------------------

1. LAVA IS ITS OWN MESH. The terrain uses vertex colors, and glTF vertex colors
   only multiply BASE color — they can't drive emission. So the glowing bits are
   extracted into a separate "Lava" object built from the same faces, lifted a
   hair off the surface, with three emissive materials (hot core / lava / cooling
   ember). The game's planet loader passes GLB materials through untouched, so
   emissiveFactor arrives intact.
   The bundled GLTFLoader.js does NOT support KHR_materials_emissive_strength,
   so emissive intensity is effectively clamped to 1 in game. Get brightness
   from the COLOR (near-white-hot cores), not from the strength number.

2. CINDER IS SMALL — 900u in game vs RUBICON's 3200. The GLB is still modeled at
   R=100 and the game scales by cfg.radius/100, so the scale factor here is 9x,
   not 32x. A building authored at RUBICON's Blender sizes would come out 3.5x
   too small. That's what MS is for: every STRUCTURE dimension and settlement
   footprint gets multiplied by MS so the outposts end up the same PHYSICAL size
   in game. Planet-relative things (clouds, caldera, craters, noise frequency)
   are NOT scaled by MS — they should look right relative to the ball.
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
R          = 100.0      # base radius in Blender units — MUST stay 100 (loader
                        #   divides by 100). Bigger planet = bigger cfg.radius.
SUBDIV     = 7          # icosphere subdivisions. Blender's count is 1-BASED:
                        #   20 * 4^(n-1), so 7 → 81,920 triangles (~13MB GLB).
                        #   Same as EARTH and RUBICON — don't bump it to 8.
SEED       = 11         # matches CINDER's seed in the game's BODIES config.

# model scale: CINDER is 900u in game (scale 9) vs RUBICON's 3200u (scale 32).
# multiply STRUCTURE sizes + settlement footprints by this so an outpost is the
# same physical size in game as RustHollow's shacks. See the header note.
MS = 32.0 / 9.0         # ≈ 3.56

LAVA_LIFT = 0.05        # how far the lava mesh floats off the terrain, in
                        #   Blender units, to beat z-fighting (0.45u in game)

# CINDER has TWO small industrial outposts — both smaller than RUBICON's
# RustHollow (46 structures). Nobody LIVES here; these are company sites working
# the heat. "h" (pan height) is filled in automatically below from the local
# terrain, so moving a camp doesn't leave it on a mesa or in a hole.
SETTLEMENTS = [
    # ore smelting camp on the volcano's outer flank — tapping the molten stuff
    {"name": "Slagworks", "lat": 19.0, "lon": -52.0, "ang": 0.135,
     "structures": 24, "kind": "slag"},
    # thermal-management station out on a cold ash plain — banks of radiator
    # fins dumping the heat the smelters make. Yes, it's an HVAC joke.
    {"name": "Heatsink",  "lat": -33.0, "lon": 104.0, "ang": 0.120,
     "structures": 20, "kind": "heat"},
]

# HERO FEATURE — "The Maw": a broad shield volcano with a lava lake in its
# caldera. Angles are radians of arc; at CINDER's 900u game radius, 0.13 rad is
# a ~117u-radius lake and the shield spreads to ~300u. Big enough to fly into.
CALDERA_LAT, CALDERA_LON = 5.0, 30.0
SHIELD_W    = 0.30      # gaussian width of the volcano's broad cone
SHIELD_H    = 0.095     # peak elevation (surface multiplier offset)
LAKE_R      = 0.13      # lava lake radius (radians of arc)
LAKE_H      = 0.030     # lake floor elevation → ~58u deep below the rim in game

# volcanic provinces: (lat, lon, width_radians, strength) — soft blobs summed
# into a highland mask, exactly like EARTH's continents but meaning "raised
# basalt country" instead of "land". The gaps between them are ASH PLAINS: flat,
# gray, boring on purpose, so the highlands and lava read as the interesting bit.
PROVINCES = [
    (8, 26, 0.44, 1.05), (-4, -14, 0.38, 0.95), (22, -60, 0.40, 0.98),
    (-30, 96, 0.34, 0.88), (14, 128, 0.42, 1.00), (-18, 168, 0.38, 0.92),
    (40, -140, 0.36, 0.90), (-46, -104, 0.34, 0.86), (52, 74, 0.32, 0.82),
    (-58, 12, 0.30, 0.78), (68, 160, 0.30, 0.76),
    # deliberately EMPTY: nothing near (-10, 60) or (34, -170) — those sink to
    # ash plain. Heatsink sits on one of them.
]

# palette — scorched identity. Authored as sRGB hex, exported raw so in-game
# colors land close (the game renders linear passthrough).
PAL = {
    "ash":      0x39352f,   # ash plain floor (the "sea level" of this world)
    "ashDeep":  0x2a2724,   # deepest ash basins
    "ashLight": 0x555049,   # wind-scoured pale ash
    "basalt":   0x2b2523,   # dark volcanic rock
    "basaltHi": 0x4d423a,   # sun-bleached high basalt
    "obsidian": 0x151316,   # near-black volcanic glass fields
    "sulfur":   0xb2963c,   # sulfur crust fringing the hot zones
    "sulfurLt": 0xd6c069,   # brighter sulfur bloom
    "emberLo":  0x5e2109,   # cooling crust, well away from a vein
    "emberHi":  0xa8380d,   # hot crust right at the vein's edge
    "polar":    0x2c2f36,   # cold, dead, faintly blue-gray crust at the poles
    "cloud":    0x5c5550,   # ash/smoke deck (dark — this is not weather)
    "plume":    0x4a423d,   # eruption column over the caldera
    # lava — three heat stops. Brightness comes from COLOR (see header note 1).
    "lavaCore": 0xffc24d,   # hottest fissure core (kept off pure white — at
                            #   emissive intensity 1 a near-white core reads as
                            #   SNOW from orbit, which is a bad look on a lava world)
    "lavaMid":  0xff7a1a,   # running orange lava
    "lavaEdge": 0x8f2a08,   # crusting-over dark ember
    # outposts — industrial, sooty, company-owned
    "pan":      0x1c1917,   # scorched leveled ground under a camp
    "metalA":   0x6a5a4c, "metalB": 0x4e5257, "metalC": 0x33322f,
    "rust":     0x7a4526, "steel":  0x8a8f96, "soot":   0x201d1a,
    "finA":     0x9aa2aa,   # radiator fin face (bright — reads at a distance)
    "finB":     0x5f666d,   # fin edge / frame
    "pipe":     0x59616a,
    "amber":    0xffb347,   # work lights
    "redlite":  0xd11f1f,   # hazard beacons
    "pour":     0xff9a2e,   # molten pour glow at the smelters
}

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)   # masters live in ~/Blender/spacesuck; assets land in planets/
OUT  = os.path.join(ROOT, "planets")
os.makedirs(os.path.join(OUT, "previews"), exist_ok=True)

# ---------------------------------------------------- NOISE (numpy, fast) --
# Value noise: hash the 8 corners of the grid cell each point sits in, then
# blend. Same idea as the JS noise in space-flight.html, just vectorized.

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
    u = f * f * (3.0 - 2.0 * f)          # smoothstep fade
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

def ridged(p, octaves, seed):
    """sharp folded ridges — used here for LAVA VEINS, not mountains"""
    n = fbm(p, octaves, seed)
    return (1.0 - np.abs(2.0 * n - 1.0)) ** 2

def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)

def ll_dir(lat, lon):
    """lat/lon degrees → unit direction, Blender coords (Z = north)"""
    la, lo = math.radians(lat), math.radians(lon)
    return np.array([math.cos(la) * math.cos(lo),
                     math.cos(la) * math.sin(lo),
                     math.sin(la)])

CALDERA_DIR = ll_dir(CALDERA_LAT, CALDERA_LON)
for _c in SETTLEMENTS:
    _c["dir"] = ll_dir(_c["lat"], _c["lon"])

# tangent frame at the caldera — gives the flank lava channels an azimuth to
# run down, and the ash-fall streak a downwind direction.
CAL_T1 = np.cross(CALDERA_DIR, np.array([0.0, 0.0, 1.0]))
CAL_T1 = CAL_T1 / np.linalg.norm(CAL_T1)
CAL_T2 = np.cross(CALDERA_DIR, CAL_T1)
CHANNEL_AZ = [0.35, 1.55, 2.70, -1.10, -2.35]   # five spillways off the rim

# THE SCAR — a graben (a collapsed trench) on the far side from The Maw, so the
# caldera isn't the only place worth diving into. Defined like RUBICON's rift:
# a great circle (plane normal GRABEN_N) gated to an arc around GRABEN_M.
_GA, _GB = ll_dir(48, 150), ll_dir(30, -150)
GRABEN_N = np.cross(_GA, _GB); GRABEN_N = GRABEN_N / np.linalg.norm(GRABEN_N)
GRABEN_M = ll_dir(41, 177)

# a crashed hulk half-buried out on an empty ash plain — pure landmark
HULK_LAT, HULK_LON = -12.0, 66.0
HULK_DIR = ll_dir(HULK_LAT, HULK_LON)


def _clear_of_camps(d, pad=2.2):
    return all(float(d @ c["dir"]) < math.cos(c["ang"] * pad) for c in SETTLEMENTS)

# impact craters — generated deterministically from SEED so re-runs match, but
# kept off the caldera (which would look silly) and off the poles.
_crng = random.Random(SEED + 300)
CRATERS = []
while len(CRATERS) < 17:
    clat = math.degrees(math.asin(_crng.uniform(-0.94, 0.94)))
    cd = ll_dir(clat, _crng.uniform(-180, 180))
    if float(cd @ CALDERA_DIR) > math.cos(0.44):
        continue                                   # don't punch the volcano
    CRATERS.append((cd, _crng.uniform(0.030, 0.105), _crng.uniform(0.006, 0.019)))

# CINDER CONES — secondary vents. Small cones with their own summit pits; some
# are still active (they get lava in the pit and a glow). These do most of the
# work of making the surface read as VOLCANIC rather than just cratered.
_vrng = random.Random(SEED + 700)
CONES = []
while len(CONES) < 20:
    d = ll_dir(math.degrees(math.asin(_vrng.uniform(-0.92, 0.92))),
               _vrng.uniform(-180, 180))
    if float(d @ CALDERA_DIR) > math.cos(0.22) or not _clear_of_camps(d):
        continue
    CONES.append((d, _vrng.uniform(0.018, 0.042), _vrng.uniform(0.010, 0.026),
                  _vrng.random() < 0.45))

# COLLAPSED LAVA TUBES — steep round pits punched into the plains. A few still
# have something molten at the bottom.
PITS = []
while len(PITS) < 15:
    d = ll_dir(math.degrees(math.asin(_vrng.uniform(-0.90, 0.90))),
               _vrng.uniform(-180, 180))
    if float(d @ CALDERA_DIR) > math.cos(0.20) or not _clear_of_camps(d):
        continue
    PITS.append((d, _vrng.uniform(0.010, 0.024), _vrng.uniform(0.008, 0.020),
                 _vrng.random() < 0.40))

# ------------------------------------------------------------ LAVA FIELD --
# Where the glowing stuff is. Called from inside height_field (the veins carve
# shallow grooves so lava sits DOWN in a crack, not painted on flat ground), and
# its output rides along in the aux dict so the color pass and the lava-mesh
# builder use the exact same numbers.

def lava_field(dirs):
    # regional heat: only part of the world is still active. the rest is dead
    # cold basalt, which is what makes the hot side read as hot.
    hot = smoothstep(0.40, 0.62, fbm(dirs * 1.5 + 2.2, 4, SEED + 61))

    # THE VEIN NETWORK. ridged() folds noise around its own midline, so its
    # output sits MOSTLY near 1 — thin filaments only appear at the very top of
    # its range. Threshold it low and you get CONTINENTS of lava instead of
    # cracks (v1 did exactly that: half the planet came out molten). 0.955+ is
    # roughly the top few percent, which is what a crack network should be.
    rr = ridged(dirs * 3.4 + 5.5, 5, SEED + 13)
    vein = smoothstep(0.955, 0.992, rr) * hot
    vein = vein * (0.45 + 0.55 * fbm(dirs * 11.0 + 3.1, 3, SEED + 29))

    ang = np.arccos(np.clip(dirs @ CALDERA_DIR, -1.0, 1.0))

    # the caldera lava lake — jitter the shoreline so it isn't a clean circle,
    # then break the surface into drifting crust plates. The plate term has to
    # swing the FULL 0..1 range: raw fbm hovers around 0.5, which lands every
    # face in the same "mid" heat bucket and paints the lake one flat orange.
    angj = ang + (fbm(dirs * 22.0 + 31.0, 3, SEED + 83) - 0.5) * 0.030
    lake = 1.0 - smoothstep(LAKE_R * 0.86, LAKE_R * 1.04, angj)
    # floor at 0.45, NOT 0.28: the lava mesh only takes faces above 0.30, so a
    # darker crust plate would drop straight out of the mesh and leave a bare
    # hole in the middle of the lake.
    plates = smoothstep(0.38, 0.62, fbm(dirs * 20.0 + 8.8, 3, SEED + 47))
    lake = lake * (0.45 + 0.55 * plates)

    # FLANK CHANNELS — lava spilling off the rim and running downslope. This is
    # what gives The Maw its radial "spider" silhouette from orbit; a lava lake
    # sitting alone in a pit reads as a dot and nothing more.
    azw = np.arctan2(dirs @ CAL_T2, dirs @ CAL_T1)
    azw = azw + (fbm(dirs * 5.0 + 13.3, 3, SEED + 101) - 0.5) * 0.45   # meander
    span = (smoothstep(LAKE_R * 0.90, LAKE_R * 1.25, ang)
            * (1.0 - smoothstep(0.26, 0.40, ang)))
    chan = np.zeros(len(dirs))
    for a0 in CHANNEL_AZ:
        da = (azw - a0 + np.pi) % (2 * np.pi) - np.pi
        chan = np.maximum(chan, np.exp(-(da / 0.085) ** 2))
    chan = chan * span

    # active cinder-cone summits and the hot collapse pits
    vent = np.zeros(len(dirs))
    for cd_, rad, _h, act in CONES:
        if not act:
            continue
        a = np.arccos(np.clip(dirs @ cd_, -1.0, 1.0))
        vent = np.maximum(vent, 1.0 - smoothstep(rad * 0.16, rad * 0.34, a))
    for cd_, rad, _d, hotpit in PITS:
        if not hotpit:
            continue
        a = np.arccos(np.clip(dirs @ cd_, -1.0, 1.0))
        vent = np.maximum(vent, 1.0 - smoothstep(rad * 0.45, rad * 0.72, a))

    # a molten seam running down the middle of the graben floor
    perp  = np.abs(dirs @ GRABEN_N)
    along = np.arccos(np.clip(dirs @ GRABEN_M, -1.0, 1.0))
    seam = (np.exp(-(perp / 0.008) ** 2) * smoothstep(0.78, 0.44, along)
            * smoothstep(0.35, 0.62, fbm(dirs * 6.0 + 21.0, 3, SEED + 131)))

    total = np.maximum.reduce([vein, lake, chan * 0.95, vent, seam])

    # the outposts cleared their ground — no lava inside a camp footprint
    for c in SETTLEMENTS:
        ac = np.arccos(np.clip(dirs @ c["dir"], -1.0, 1.0))
        total = total * smoothstep(c["ang"] * 1.25, c["ang"] * 1.85, ac)

    return {"total": np.clip(total, 0.0, 1.0), "vein": vein, "lake": lake,
            "chan": chan, "vent": vent, "seam": seam, "rr": rr, "hot": hot}

# ------------------------------------------------------- THE HEIGHT FIELD --
# One function decides the whole planet. dirs: (N,3) unit vectors.
# Returns the surface multiplier m (ash plain floor ≈ 1.0, highlands above)
# plus the intermediate values the coloring pass needs.

def height_field(dirs, flatten=True):
    z = dirs[:, 2]                                     # sin(latitude)

    # highland mask: sum of soft angular blobs (see PROVINCES)
    mask = np.zeros(len(dirs))
    for lat, lon, width, strength in PROVINCES:
        d = ll_dir(lat, lon)
        ang = np.arccos(np.clip(dirs @ d, -1.0, 1.0))
        mask += strength * np.exp(-(ang / width) ** 2)

    # wiggle the province edges so nothing looks like a perfect circle
    mask += (fbm(dirs * 2.5 + 7.7, 5, SEED + 3) - 0.5) * 0.55

    high  = smoothstep(0.46, 0.60, mask)               # 0 = ash plain, 1 = highland
    core  = smoothstep(0.58, 0.94, mask)               # highland interior
    hills = (fbm(dirs * 6.5 + 3.3, 5, SEED + 40) - 0.5) * 2.0
    rough = ridged(dirs * 5.2 + 1.1, 5, SEED + 80)     # blocky basalt relief

    # base relief. amplitude kept modest so the LIMB still reads as a sphere —
    # the drama on this world comes from the caldera and the glow, not lumps.
    elev = high * (0.012 + 0.006 * hills) + core * rough * 0.045 * high
    elev = np.maximum(elev, 0.0)

    # ash plains get a faint dune ripple so they aren't dead flat to fly over
    elev += (1.0 - high) * (fbm(dirs * 9.0 + 5.9, 3, SEED + 55) - 0.5) * 0.004

    # ---- IMPACT CRATERS: a bowl plus a raised rim, both through the height
    # field so the collision grid knows about them and you can set down inside.
    for cd, rad, dep in CRATERS:
        a = np.arccos(np.clip(dirs @ cd, -1.0, 1.0))
        t = np.clip(a / rad, 0.0, 1.0)
        bowl = -dep * (1.0 - t * t) * (1.0 - smoothstep(0.82, 1.0, t))
        rim  = dep * 0.45 * np.exp(-((a - rad) / (rad * 0.28)) ** 2)
        elev += bowl + rim

    # ---- CINDER CONES: secondary vents, each with its own summit pit. These
    # break up the limb and give a low fly-through something to weave around.
    for cd_, rad, hgt, _act in CONES:
        a = np.arccos(np.clip(dirs @ cd_, -1.0, 1.0))
        elev += np.exp(-(a / rad) ** 2) * hgt
        elev -= (1.0 - smoothstep(rad * 0.22, rad * 0.42, a)) * hgt * 0.62

    # ---- COLLAPSED LAVA TUBES: steep-sided round pits punched in the plains
    for cd_, rad, dep, _h in PITS:
        a = np.arccos(np.clip(dirs @ cd_, -1.0, 1.0))
        elev -= dep * (1.0 - smoothstep(rad * 0.62, rad, a))

    # ---- THE MAW: broad shield cone, then blow the top off into a caldera.
    ang_cal = np.arccos(np.clip(dirs @ CALDERA_DIR, -1.0, 1.0))
    elev += np.exp(-(ang_cal / SHIELD_W) ** 2) * SHIELD_H
    pit = 1.0 - smoothstep(LAKE_R, LAKE_R * 1.45, ang_cal)   # 1 in the pit
    elev = elev * (1.0 - pit) + LAKE_H * pit
    # a raised RIM ring just outside the pit. Without it the shield's own slope
    # is all you get and the caldera reads as a flat orange patch painted on a
    # hill rather than a hole with a wall around it.
    elev += np.exp(-((ang_cal - LAKE_R * 1.55) / (LAKE_R * 0.34)) ** 2) * 0.021

    # ---- THE SCAR: the graben trench, carved on the far side from The Maw
    perp  = np.abs(dirs @ GRABEN_N)
    along = np.arccos(np.clip(dirs @ GRABEN_M, -1.0, 1.0))
    graben = np.exp(-(perp / 0.024) ** 2) * smoothstep(0.80, 0.42, along)
    elev -= graben * 0.042

    # ---- LAVA GROOVES: carved LAST (like RUBICON's rift) so nothing above can
    # fill them back in. Shallow — the lava mesh sits down in the crack.
    lav = lava_field(dirs)
    elev -= lav["vein"] * 0.007 + lav["chan"] * 0.005

    m = 1.0 + elev

    # ---- level the outpost pans so the structures sit flat and the sampled
    # height grid agrees. Done last so a camp always wins.
    if flatten:
        for c in SETTLEMENTS:
            ac = np.arccos(np.clip(dirs @ c["dir"], -1.0, 1.0))
            t = 1.0 - smoothstep(c["ang"], c["ang"] * 1.9, ac)
            m = m * (1.0 - t) + c["h"] * t

    return m, {"mask": mask, "high": high, "elev": m - 1.0, "z": z,
               "lava": lav, "ang_cal": ang_cal, "graben": graben}

# auto-level each camp to whatever the terrain does there, so moving a
# settlement doesn't strand it on a mesa or drop it in a hole. Must run BEFORE
# any flatten=True call reads c["h"].
for _c in SETTLEMENTS:
    _hm, _ = height_field(_c["dir"][None, :], flatten=False)
    _c["h"] = float(_hm[0]) + 0.0012          # a hair proud of the local ground
    print(f"  {_c['name']} pan height → {_c['h']:.5f}")

# ------------------------------------------------------------- COLOR PASS --
def hex_rgb(h):
    return np.array([(h >> 16 & 255) / 255.0, (h >> 8 & 255) / 255.0, (h & 255) / 255.0])

def lerp_col(a, b, t):
    t = t[:, None]
    return a[None, :] * (1 - t) + b[None, :] * t

def tint(base, color, t):
    """pull a per-face color ARRAY toward a single color by weight t (per face)"""
    t = t[:, None]
    return base * (1 - t) + color[None, :] * t

def arc_mask(dirs, A, B, width):
    """gaussian band along the great-circle arc A→B. Used for haul roads."""
    N = np.cross(A, B); N = N / np.linalg.norm(N)
    mid = A + B; mid = mid / np.linalg.norm(mid)
    half = math.acos(float(np.clip(A @ B, -1.0, 1.0))) * 0.5
    perp = np.abs(dirs @ N)
    along = np.arccos(np.clip(dirs @ mid, -1.0, 1.0))
    return (np.exp(-(perp / width) ** 2)
            * (1.0 - smoothstep(half * 0.85, half * 1.05, along)))

# scoured haul tracks running out of each camp — company traffic, painted only
ROADS = [
    (SETTLEMENTS[0]["dir"], ll_dir(11.0, -33.0), 0.0085),   # Slagworks → the Maw
    (SETTLEMENTS[0]["dir"], ll_dir(28.0, -64.0), 0.0060),   # spur to the workings
    (SETTLEMENTS[1]["dir"], ll_dir(-24.0, 118.0), 0.0075),  # Heatsink → outfield
]

def face_colors(dirs, aux):
    """dirs: (F,3) unit face directions → (F,4) RGBA float colors"""
    elev, z, high = aux["elev"], aux["z"], aux["high"]
    lav = aux["lava"]

    # ---- base: ash plains → basalt highlands, by elevation
    et = np.clip(elev / 0.07, 0.0, 1.0)
    plain = lerp_col(hex_rgb(PAL["ashDeep"]), hex_rgb(PAL["ash"]),
                     smoothstep(0.0, 0.18, et))
    col = tint(plain, hex_rgb(PAL["basalt"]), smoothstep(0.10, 0.42, et))
    col = tint(col, hex_rgb(PAL["basaltHi"]), smoothstep(0.55, 1.0, et))

    # wind-scoured pale streaks out on the open ash — keeps the plains alive
    scour = (1.0 - high) * smoothstep(0.55, 0.78, fbm(dirs * 7.5 + 1.7, 4, SEED + 17))
    col = tint(col, hex_rgb(PAL["ashLight"]), scour * 0.8)

    # ---- obsidian glass fields: patchy near-black sheets on the highlands
    glass = high * smoothstep(0.60, 0.80, fbm(dirs * 5.5 + 12.3, 4, SEED + 71))
    col = tint(col, hex_rgb(PAL["obsidian"]), glass * 0.9)

    # ---- CRATERS: dark ponded floors, and bright ejecta rays flung out from
    # the big ones. The rays are what make craters read from ORBIT — a bowl
    # alone is just a shadow at this scale.
    floor = np.zeros(len(dirs))
    rays  = np.zeros(len(dirs))
    for cd_, rad, _dep in CRATERS:
        a = np.arccos(np.clip(dirs @ cd_, -1.0, 1.0))
        floor = np.maximum(floor, 1.0 - smoothstep(rad * 0.55, rad * 0.95, a))
        if rad < 0.075:
            continue                       # only the big ones throw rays
        t1 = np.cross(cd_, np.array([0.0, 0.0, 1.0]))
        t1 = t1 / np.linalg.norm(t1)
        t2 = np.cross(cd_, t1)
        raz = np.arctan2(dirs @ t2, dirs @ t1)
        streak = 0.5 + 0.5 * np.cos(raz * 9.0 + rad * 137.0)
        band = smoothstep(rad * 4.2, rad * 1.05, a)
        rays = np.maximum(rays, band * smoothstep(0.60, 0.93, streak))
    col = tint(col, hex_rgb(PAL["obsidian"]), floor * 0.55)
    col = tint(col, hex_rgb(PAL["ashLight"]), rays * 0.5)

    # ---- EMBER HALO: fake the light the lava throws. `rr` is the same ridged
    # field the veins are cut from, so raising it to a power gives a smooth
    # falloff that hugs every crack for free — no extra noise, no real lights.
    prox = np.clip((lav["rr"] - 0.80) / 0.20, 0.0, 1.0) * lav["hot"]
    col = tint(col, hex_rgb(PAL["emberLo"]), (prox ** 2) * 0.85)
    col = tint(col, hex_rgb(PAL["emberHi"]), (prox ** 4) * 0.85)

    # fresh flows down the channels are near-black glass, cooler than the vein
    col = tint(col, hex_rgb(PAL["obsidian"]),
               smoothstep(0.25, 0.75, lav["chan"]) * 0.7)
    col = tint(col, hex_rgb(PAL["emberHi"]), (lav["chan"] ** 2) * 0.55)

    # the caldera's inner wall and the graben floor both glow from below
    wall = 1.0 - smoothstep(LAKE_R * 1.0, LAKE_R * 1.9, aux["ang_cal"])
    col = tint(col, hex_rgb(PAL["emberHi"]), wall * 0.55)
    col = tint(col, hex_rgb(PAL["obsidian"]), smoothstep(0.30, 0.85, aux["graben"]) * 0.6)
    col = tint(col, hex_rgb(PAL["emberLo"]), (lav["seam"] ** 0.5) * 0.7)

    # ---- SULFUR: yellow mineral crusts on the OUTER fringe of each hot zone —
    # the only cool color on the planet. Without it, everything is black+orange.
    sn = fbm(dirs * 8.5 + 9.4, 3, SEED + 77)
    lin = np.clip((lav["rr"] - 0.72) / 0.26, 0.0, 1.0) * lav["hot"]
    fringe = lin * (1.0 - lin) * 4.0                 # peaks mid-band, 0 at both ends
    col = tint(col, hex_rgb(PAL["sulfur"]), fringe * smoothstep(0.48, 0.66, sn) * 0.9)
    col = tint(col, hex_rgb(PAL["sulfurLt"]), fringe * smoothstep(0.68, 0.80, sn) * 0.7)

    # ---- ASH FALL: a dark plume-shadow deposit downwind of The Maw
    azc = np.arctan2(dirs @ CAL_T2, dirs @ CAL_T1)
    fall = (np.exp(-(azc / 0.60) ** 2)
            * smoothstep(LAKE_R, 0.55, aux["ang_cal"])
            * (1.0 - smoothstep(0.60, 1.15, aux["ang_cal"])))
    col = tint(col, hex_rgb(PAL["soot"]), fall * 0.45)

    # ---- poles: no ice on a world this hot, just cold dead crust. Subtle.
    col = tint(col, hex_rgb(PAL["polar"]), smoothstep(0.90, 0.99, np.abs(z)) * 0.7)

    # ---- the crashed hulk's scorch mark
    ah = np.arccos(np.clip(dirs @ HULK_DIR, -1.0, 1.0))
    col = tint(col, hex_rgb(PAL["soot"]), (1.0 - smoothstep(0.010, 0.024, ah)) * 0.8)

    # ---- haul roads, then the scorched outpost pans on top of them. Both are
    # painted LAST so they override the terrain. The pan edge is FEATHERED —
    # a hard cut reads as a dinner plate dropped on the ground.
    for A, B, w in ROADS:
        col = tint(col, hex_rgb(PAL["soot"]), arc_mask(dirs, A, B, w) * 0.75)
    for c in SETTLEMENTS:
        ac = np.arccos(np.clip(dirs @ c["dir"], -1.0, 1.0))
        col = tint(col, hex_rgb(PAL["pan"]),
                   1.0 - smoothstep(c["ang"] * 0.80, c["ang"] * 1.02, ac))

    # per-face brightness jitter — the thing that makes low-poly look rich
    rng = np.random.default_rng(SEED)
    col *= (1.0 + (rng.random(len(dirs))[:, None] - 0.5) * 0.12)
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
        # input names moved around across Blender versions — try both
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
planet.name = "Cinder"
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

# per-face colors, painted onto the mesh corners (all 3 corners of a
# triangle get the same color → each facet is one flat tint)
nf = len(me.polygons)
centers = np.empty(nf * 3)
me.polygons.foreach_get("center", centers)
centers = centers.reshape(-1, 3)
fdirs = centers / np.linalg.norm(centers, axis=1)[:, None]
fm, faux = height_field(fdirs)
cols = face_colors(fdirs, faux)

attr = me.color_attributes.new(name="Col", type='FLOAT_COLOR', domain='CORNER')
attr.data.foreach_set("color", np.repeat(cols, 3, axis=0).ravel())

bpy.ops.object.shade_flat()
me.materials.append(make_material("Terrain", vertex_colors=True, roughness=0.95))

# ------------------------------------------------------------- LAVA MESH --
# Pull the glowing faces out of the terrain into their own object. See header
# note 1 for WHY this can't just be a vertex-color trick.
print("pouring lava…")
lava_str = faux["lava"]["total"]
sel = np.where(lava_str > 0.30)[0]
print(f"  {len(sel)} lava faces of {nf} ({100.0*len(sel)/nf:.1f}%)")

pv = np.empty(nf * 3, dtype=np.int32)   # Blender int props are int32 — dtype matters
me.polygons.foreach_get("vertices", pv)
tris = pv.reshape(-1, 3)[sel]

used = np.unique(tris)
remap = np.full(nv, -1, dtype=np.int64)
remap[used] = np.arange(len(used))
new_tris = remap[tris]
# lift off the surface so it doesn't z-fight the terrain it was cut from
lverts = dirs[used] * (R * vm[used] + LAVA_LIFT)[:, None]

lmesh = bpy.data.meshes.new("LavaMesh")
lmesh.from_pydata(lverts.tolist(), [], new_tris.tolist())
lmesh.update()
lava_obj = bpy.data.objects.new("Lava", lmesh)
bpy.context.collection.objects.link(lava_obj)

# three heat stops as separate material slots — glTF splits them into separate
# primitives on export, so we get a hot/mid/cool gradient with no textures.
# Two deliberate choices here:
#   strength stays at 1.0 — the game's GLTFLoader ignores
#   KHR_materials_emissive_strength, so in-game emission is exactly
#   emissiveFactor at intensity 1; anything higher only lies to the previews.
#
#   BASE color is near-black while EMISSION carries the lava color. Setting both
#   to the lava color double-counts (lit base + emission) and clips the hot
#   faces to flat white on the sunlit side. Dark base = the emissive color is
#   what you actually see, day or night, which is also how it reads in game.
for m_ in (make_material("LavaCore", color_hex=0x2a1206,
                         emission_hex=PAL["lavaCore"], strength=1.0, roughness=0.6),
           make_material("LavaMid",  color_hex=0x1f0d05,
                         emission_hex=PAL["lavaMid"],  strength=1.0, roughness=0.7),
           make_material("LavaEdge", color_hex=0x160903,
                         emission_hex=PAL["lavaEdge"], strength=1.0, roughness=0.85)):
    lmesh.materials.append(m_)

s = lava_str[sel]
midx = np.where(s > 0.86, 0, np.where(s > 0.58, 1, 2)).astype(np.int32)
lmesh.polygons.foreach_set("material_index", midx)
lmesh.update()

bpy.ops.object.select_all(action='DESELECT')
bpy.context.view_layer.objects.active = lava_obj
lava_obj.select_set(True)
bpy.ops.object.shade_flat()
lava_obj.select_set(False)

# ------------------------------------------------------------- OUTPOSTS --
# Two small company sites. Same local-frame trick as EARTH's city: build each
# piece in a +Z-up frame, then drop it onto the sphere via base_pt + rot @ offset
# (rot maps local +Z onto the surface normal d). All dimensions are × MS — see
# header note 2 or the buildings come out 3.5x too small in game.
print("raising the outposts…")

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

def _ico(base_pt, rot, off, scale, mat, objs, subd=2):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=subd, radius=1.0,
                                          location=base_pt + rot @ Vector(off))
    b = bpy.context.active_object
    b.scale = Vector(scale)
    b.rotation_mode = 'QUATERNION'; b.rotation_quaternion = rot
    b.data.materials.append(mat); objs.append(b); return b

metal_mats = [make_material("MetalA", color_hex=PAL["metalA"], roughness=0.92),
              make_material("MetalB", color_hex=PAL["metalB"], roughness=0.82),
              make_material("MetalC", color_hex=PAL["metalC"], roughness=0.90)]
rust_mat  = make_material("Rust",  color_hex=PAL["rust"],  roughness=0.95)
soot_mat  = make_material("Soot",  color_hex=PAL["soot"],  roughness=1.00)
steel_mat = make_material("Steel", color_hex=PAL["steel"], roughness=0.45)
finA_mat  = make_material("FinA",  color_hex=PAL["finA"],  roughness=0.35)
finB_mat  = make_material("FinB",  color_hex=PAL["finB"],  roughness=0.55)
pipe_mat  = make_material("Pipe",  color_hex=PAL["pipe"],  roughness=0.60)
amber_mat = make_material("Amber", color_hex=PAL["amber"],
                          emission_hex=PAL["amber"], strength=3.0)
red_mat   = make_material("RedLite", color_hex=PAL["redlite"],
                          emission_hex=PAL["redlite"], strength=3.5)
pour_mat  = make_material("Pour", color_hex=PAL["pour"],
                          emission_hex=PAL["pour"], strength=5.0)

def make_slag(base_pt, rot, fx, fy, h, rng, objs):
    """SLAGWORKS — ore smelting. Tall stacks, silos, gantries, slag heaps."""
    k = rng.random()
    if k < 0.22:
        # SMELTER STACK — squat furnace box + a tall chimney with a hot mouth
        _box(base_pt, rot, (0, 0, h * 0.5), (fx * 1.1, fy * 1.1, h), soot_mat, objs)
        ch = h * 2.6
        _cyl(base_pt, rot, (0, 0, ch * 0.5), min(fx, fy) * 0.30, ch, metal_mats[2], objs)
        _cyl(base_pt, rot, (0, 0, ch + 0.02 * MS), min(fx, fy) * 0.26, 0.08 * MS,
             pour_mat, objs)                       # glowing chimney mouth
    elif k < 0.40:
        # ORE SILO — fat cylinder with a cone cap and a discharge chute
        r = min(fx, fy) * 0.62
        _cyl(base_pt, rot, (0, 0, h * 0.9), r, h * 1.8, rust_mat, objs, verts=12)
        _cone(base_pt, rot, (0, 0, h * 1.8 + h * 0.28), r, r * 0.25, h * 0.56,
              metal_mats[0], objs)
        _box(base_pt, rot, (r * 0.9, 0, h * 0.35), (fx * 0.22, fy * 0.22, h * 0.7),
             metal_mats[2], objs)
    elif k < 0.56:
        # CONVEYOR GANTRY — a long raised belt on legs, running off downslope
        L = fx * 3.4
        _box(base_pt, rot, (0, 0, h * 1.25), (L, fy * 0.34, h * 0.24),
             metal_mats[1], objs)
        for lx in (-L * 0.38, 0.0, L * 0.38):
            _box(base_pt, rot, (lx, 0, h * 0.6), (fx * 0.13, fy * 0.13, h * 1.2),
                 metal_mats[2], objs)
    elif k < 0.70:
        # SLAG HEAP — a dumped pile of spoil, still cooling at the base
        _ico(base_pt, rot, (0, 0, h * 0.10), (fx * 1.5, fy * 1.35, h * 0.85),
             soot_mat, objs)
        if rng.random() < 0.6:
            _ico(base_pt, rot, (fx * 0.5, fy * 0.3, 0.02 * MS),
                 (fx * 0.30, fy * 0.26, h * 0.14), pour_mat, objs, subd=1)
    elif k < 0.84:
        # CRUCIBLE CAR / ladle on rails — a drum with a molten glow inside
        _cyl(base_pt, rot, (0, 0, h * 0.55), min(fx, fy) * 0.55, h * 0.9,
             metal_mats[0], objs, verts=12)
        _cyl(base_pt, rot, (0, 0, h * 1.02), min(fx, fy) * 0.46, h * 0.10,
             pour_mat, objs, verts=12)
        _box(base_pt, rot, (0, 0, h * 0.06), (fx * 1.3, fy * 0.5, h * 0.12),
             metal_mats[2], objs)
    else:
        # plain WORKSHOP shed — a low sooty box, maybe a vent unit on the roof
        _box(base_pt, rot, (0, 0, h * 0.5), (fx, fy, h), metal_mats[rng.randrange(3)], objs)
        if rng.random() < 0.55:
            _box(base_pt, rot, (rng.uniform(-fx * 0.2, fx * 0.2),
                                rng.uniform(-fy * 0.2, fy * 0.2), h + 0.04 * MS),
                 (fx * 0.28, fy * 0.28, 0.09 * MS), metal_mats[1], objs)
        if rng.random() < 0.4:
            _ico(base_pt, rot, (fx * 0.55, fy * 0.55, h * 1.05),
                 (0.05 * MS, 0.05 * MS, 0.05 * MS), amber_mat, objs, subd=1)

def make_heat(base_pt, rot, fx, fy, h, rng, objs):
    """HEATSINK — thermal management. Fin banks, coolant tanks, cooling towers."""
    k = rng.random()
    if k < 0.34:
        # RADIATOR FIN BANK — the signature piece. A row of thin tall plates on
        # a frame. This is the thing that should read from orbit as "not rock".
        nfin = rng.randint(5, 8)
        span = fy * 2.0
        _box(base_pt, rot, (0, 0, h * 0.12), (fx * 1.5, span * 0.62, h * 0.24),
             finB_mat, objs)
        for i in range(nfin):
            t = (i / (nfin - 1.0) - 0.5) * span
            _box(base_pt, rot, (0, t, h * 0.95),
                 (fx * 1.35, span * 0.045, h * 1.45), finA_mat, objs)
        _box(base_pt, rot, (fx * 0.78, 0, h * 0.95),
             (fx * 0.10, span * 0.66, h * 1.5), finB_mat, objs)
    elif k < 0.52:
        # COOLANT TANK — a horizontal drum in a cradle, with an end cap
        r = min(fx, fy) * 0.55
        rq = rot @ Matrix.Rotation(math.pi / 2, 4, 'Y').to_quaternion()
        _cyl(base_pt, rq, (-r * 1.1, 0, 0), r, fx * 2.2, steel_mat, objs, verts=14)
        for cx in (-fx * 0.6, fx * 0.6):
            _box(base_pt, rot, (cx, 0, r * 0.35), (fx * 0.18, fy * 0.9, r * 0.7),
                 finB_mat, objs)
    elif k < 0.68:
        # COOLING TOWER — a tapered stack venting a plume of waste heat
        th = h * 2.6
        _cone(base_pt, rot, (0, 0, th * 0.5), min(fx, fy) * 0.85,
              min(fx, fy) * 0.52, th, metal_mats[1], objs, verts=14)
        _cyl(base_pt, rot, (0, 0, th + 0.03 * MS), min(fx, fy) * 0.54, 0.07 * MS,
             finB_mat, objs, verts=14)
        _ico(base_pt, rot, (0, 0, th + 0.13 * MS),
             (0.05 * MS, 0.05 * MS, 0.05 * MS), red_mat, objs, subd=1)
    elif k < 0.84:
        # PUMPHOUSE — low block with an exposed pipe run arcing out of the roof
        _box(base_pt, rot, (0, 0, h * 0.5), (fx, fy, h), metal_mats[0], objs)
        pr = min(fx, fy) * 0.16
        # NOTE the offset is expressed in the ROTATED frame: Ry(90°) maps
        # (x,y,z)→(z,y,-x), so x=-h*1.15 is what lifts the pipe to roof height.
        _cyl(base_pt, rot @ Matrix.Rotation(math.pi / 2, 4, 'Y').to_quaternion(),
             (-h * 1.15, fy * 0.3, 0), pr, fx * 2.6, pipe_mat, objs, verts=8)
        _cyl(base_pt, rot, (-fx * 0.9, fy * 0.3, h * 0.6), pr, h * 1.2,
             pipe_mat, objs, verts=8)
        if rng.random() < 0.5:
            _ico(base_pt, rot, (fx * 0.5, -fy * 0.5, h * 1.05),
                 (0.05 * MS, 0.05 * MS, 0.05 * MS), amber_mat, objs, subd=1)
    else:
        # CONTROL SHACK — small crew box on skids, the only warm-looking thing
        _box(base_pt, rot, (0, 0, h * 0.45), (fx * 0.85, fy * 0.85, h * 0.9),
             metal_mats[2], objs)
        _box(base_pt, rot, (0, 0, 0.03 * MS), (fx * 1.0, fy * 1.0, 0.06 * MS),
             finB_mat, objs)
        _ico(base_pt, rot, (0, 0, h * 1.05), (0.045 * MS, 0.045 * MS, 0.045 * MS),
             amber_mat, objs, subd=1)

BUILDERS = {"slag": make_slag, "heat": make_heat}

for camp in SETTLEMENTS:
    cd = Vector(camp["dir"].tolist())
    t1 = cd.cross(Vector((0, 0, 1))).normalized()
    t2 = cd.cross(t1)
    ground = R * camp["h"]
    cr = camp["ang"] * R
    step = 0.74 * MS                     # grid pitch, scaled with the buildings
    rng2 = random.Random(SEED + sum(ord(ch) for ch in camp["name"]))
    build = BUILDERS[camp["kind"]]
    parts, built = [], 0
    n = int(math.ceil(cr / step))
    # keep the +t1 edge of the pan CLEAR — that flat strip is where you set the
    # ship down. There's no pad on CINDER; the whole planet is landable, so the
    # apron just needs to be empty and level, which the pan flatten guarantees.
    apron_x = cr * 0.42
    for gi in range(-n, n + 1):
        if built >= camp["structures"]:
            break
        for gj in range(-n, n + 1):
            if built >= camp["structures"]:
                break
            u = gi * step + rng2.uniform(-0.22 * MS, 0.22 * MS)
            v = gj * step + rng2.uniform(-0.22 * MS, 0.22 * MS)
            if math.hypot(u, v) > cr * 0.86:
                continue
            if u > apron_x:
                continue                 # leave the landing apron open
            d = (cd * R + t1 * u + t2 * v).normalized()
            # a touch smaller than RUBICON's shacks: on a 900u world a camp is
            # only ~10 BU across here, and RUBICON-sized boxes filled it with
            # four giant buildings instead of reading as a work site.
            fx, fy = rng2.uniform(0.38, 0.70) * MS, rng2.uniform(0.38, 0.70) * MS
            hh = rng2.uniform(0.24, 0.52) * MS
            build(d * ground, surf_quat(d, t1), fx, fy, hh, rng2, parts)
            built += 1

    # ---- camp dressing: the stuff that makes a cluster of boxes read as a
    # WORKED site rather than randomly placed geometry. All of it is cosmetic.
    cbase = cd * ground
    cq = surf_quat(cd, t1)
    # pipe trunks running the length of the camp. Rx(90°) maps (x,y,z)→(x,-z,y),
    # so an offset of (a, b, 0) lands at t1*a lifted b off the ground.
    prq = cq @ Matrix.Rotation(math.pi / 2, 4, 'X').to_quaternion()
    for poff in (-0.34, 0.30):
        _cyl(cbase, prq, (poff * cr, 0.28 * MS, 0.0), 0.09 * MS, cr * 1.5,
             pipe_mat, parts, verts=8)

    # antenna masts with red air-hazard lights
    for ax, ay in ((-0.55, -0.30), (0.08, 0.62), (-0.22, -0.70)):
        d = (cd * R + t1 * (cr * ax) + t2 * (cr * ay)).normalized()
        q, p = surf_quat(d, t1), d * ground
        mh = 1.7 * MS
        _cyl(p, q, (0, 0, mh * 0.5), 0.04 * MS, mh, metal_mats[2], parts, verts=6)
        _box(p, q, (0, 0, mh * 0.74), (0.30 * MS, 0.045 * MS, 0.045 * MS),
             metal_mats[1], parts)
        _ico(p, q, (0, 0, mh + 0.06 * MS), (0.05 * MS,) * 3, red_mat, parts, subd=1)

    # loose crates and drums — clutter reads as "people work here"
    for _ in range(14):
        u = rng2.uniform(-cr * 0.80, min(apron_x, cr * 0.80))
        v = rng2.uniform(-cr * 0.80, cr * 0.80)
        if math.hypot(u, v) > cr * 0.84:
            continue
        d = (cd * R + t1 * u + t2 * v).normalized()
        q, p = surf_quat(d, t1), d * ground
        sc = rng2.uniform(0.10, 0.22) * MS
        if rng2.random() < 0.35:
            _cyl(p, q, (0, 0, sc * 0.6), sc * 0.45, sc * 1.2, rust_mat, parts, verts=8)
        else:
            _box(p, q, (0, 0, sc * 0.5), (sc * rng2.uniform(0.9, 1.7), sc, sc),
                 rust_mat if rng2.random() < 0.5 else metal_mats[1], parts)

    # ---- one LANDMARK per camp: the silhouette you recognize from the air
    if camp["kind"] == "slag":
        # GANTRY CRANE straddling the workings, with a glowing ladle slung under
        d = (cd * R + t1 * (-cr * 0.30) + t2 * (cr * 0.08)).normalized()
        q, p = surf_quat(d, t1), d * ground
        gh, gs = 2.0 * MS, cr * 0.42
        for lx in (-gs, gs):
            _box(p, q, (lx, 0, gh * 0.5), (0.13 * MS, 0.13 * MS, gh),
                 metal_mats[1], parts)
        _box(p, q, (0, 0, gh), (gs * 2.3, 0.17 * MS, 0.17 * MS), metal_mats[0], parts)
        _box(p, q, (gs * 0.30, 0, gh * 0.74), (0.36 * MS, 0.32 * MS, 0.36 * MS),
             rust_mat, parts)
        _ico(p, q, (gs * 0.30, 0, gh * 0.50), (0.11 * MS,) * 3, pour_mat, parts, subd=1)
    else:
        # THE MAIN BANK — one big wall of radiator fins along the camp's edge.
        # This is the thing you spot from the air and go "that's Heatsink".
        d = (cd * R + t1 * (-cr * 0.60)).normalized()
        q, p = surf_quat(d, t1), d * ground
        _box(p, q, (0, 0, 0.09 * MS), (1.15 * MS, cr * 1.10, 0.18 * MS), finB_mat, parts)
        for i in range(11):
            _box(p, q, (0, (i / 10.0 - 0.5) * cr * 1.02, 0.80 * MS),
                 (1.00 * MS, 0.045 * MS, 1.50 * MS), finA_mat, parts)
        # + a sky-facing radiator dish (it dumps heat straight to space)
        d = (cd * R + t1 * (-cr * 0.20) + t2 * (-cr * 0.46)).normalized()
        q, p = surf_quat(d, t1), d * ground
        mh = 1.5 * MS
        _cyl(p, q, (0, 0, mh * 0.5), 0.08 * MS, mh, metal_mats[1], parts, verts=8)
        _cone(p, q, (0, 0, mh + 0.16 * MS), 0.13 * MS, 0.62 * MS, 0.32 * MS,
              finA_mat, parts, verts=16)
        _ico(p, q, (0, 0, mh + 0.46 * MS), (0.05 * MS,) * 3, red_mat, parts, subd=1)

    # four amber marker posts around the open apron — reads as "set down here"
    # without pretending to be a pad (no deck, so no height-grid mismatch).
    for mx, my in ((0.60, -0.55), (0.60, 0.55), (0.95, -0.55), (0.95, 0.55)):
        d = (cd * R + t1 * (cr * mx) + t2 * (cr * my)).normalized()
        q = surf_quat(d, t1)
        p = d * ground
        _box(p, q, (0, 0, 0.22 * MS), (0.07 * MS, 0.07 * MS, 0.44 * MS),
             metal_mats[2], parts)
        _ico(p, q, (0, 0, 0.50 * MS), (0.055 * MS, 0.055 * MS, 0.055 * MS),
             amber_mat, parts, subd=1)

    bpy.ops.object.select_all(action='DESELECT')
    for b in parts:
        b.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    cobj = bpy.context.active_object
    cobj.name = "Camp_" + camp["name"]
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    print(f"  {camp['name']}: {built} structures, {len(parts)} parts")

# ------------------------------------------------------ VOLCANIC BOULDERS --
# Lava bombs and shattered basalt strewn on the highlands — ground-scale detail
# so a low fly-through has something to bank around. Sits ON the sampled surface
# (NOT in the height grid — pure decoration, you fly through it).
print("scattering lava bombs…")
boulder_mat = make_material("Boulder", color_hex=0x2f2926, roughness=0.96)
glow_rock   = make_material("GlowRock", color_hex=PAL["emberHi"],
                            emission_hex=PAL["lavaMid"], strength=2.0)
boulders = []
random.seed(SEED + 5)
fields, attempts = 0, 0
while fields < 9 and attempts < 300:
    attempts += 1
    uu, vv = random.random(), random.random()
    th, ph = 2 * math.pi * uu, math.acos(2 * vv - 1)
    d = Vector((math.sin(ph) * math.cos(th), math.sin(ph) * math.sin(th), math.cos(ph)))
    if abs(d.z) > 0.88:                                  # not at the poles
        continue
    dn = np.array([[d.x, d.y, d.z]])
    if any(float(dn[0] @ c["dir"]) > math.cos(c["ang"] * 2.0) for c in SETTLEMENTS):
        continue                                         # not in a camp
    hm, hax = height_field(dn)
    if float(hm[0]) < 1.008:                             # only on relief
        continue
    hot_here = float(hax["lava"]["rr"][0] * hax["lava"]["hot"][0])
    fields += 1
    tan1 = d.cross(Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((1, 0, 0))).normalized()
    tan2 = d.cross(tan1)
    for _ in range(random.randint(4, 9)):
        pdir = (d * R + tan1 * random.uniform(-3, 3) * MS
                      + tan2 * random.uniform(-3, 3) * MS).normalized()
        phm, _ = height_field(np.array([[pdir.x, pdir.y, pdir.z]]))
        pr = R * float(phm[0])
        sz = random.uniform(0.12, 0.42) * MS
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=1.0,
                                              location=pdir * (pr + sz * 0.3))
        bl = bpy.context.active_object
        bl.scale = (sz, sz * random.uniform(0.7, 1.1), sz * random.uniform(0.5, 0.8))
        bl.rotation_mode = 'QUATERNION'
        bl.rotation_quaternion = surf_quat(pdir, tan1)   # lie flat on the ground
        # rocks in the hot zones haven't finished cooling
        bl.data.materials.append(
            glow_rock if (hot_here > 0.55 and random.random() < 0.35) else boulder_mat)
        boulders.append(bl)
if boulders:
    bpy.ops.object.select_all(action='DESELECT')
    for b in boulders:
        b.select_set(True)
    bpy.context.view_layer.objects.active = boulders[0]
    bpy.ops.object.join()
    bpy.context.active_object.name = "Boulders"
    bpy.ops.object.shade_flat()
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    print(f"  {len(boulders)} rocks in {fields} fields")

# --------------------------------------------------------------- FUMAROLES --
# Small vent cones with a glowing throat and a wisp of steam, planted only on
# ground the lava field says is HOT. Candidates are generated and scored in ONE
# vectorized height_field call — evaluating the field per-candidate in a Python
# loop is what makes this kind of scatter crawl.
print("venting fumaroles…")
fum_rock  = make_material("Fumarole", color_hex=0x352d28, roughness=0.96)
fum_glow  = make_material("FumGlow", color_hex=PAL["lavaMid"],
                          emission_hex=PAL["lavaMid"], strength=1.0)
# dim: at orbital distance a bright steam wisp on a dark planet reads as a
# white speck, and 54 of them ring the limb like render noise
steam_mat = make_material("Steam", color_hex=0x4e4842,
                          emission_hex=0x4e4842, strength=0.04, roughness=1.0)

_frng = np.random.default_rng(SEED + 401)
cand = _frng.normal(size=(1600, 3))
cand = cand / np.linalg.norm(cand, axis=1)[:, None]
cm, cax = height_field(cand)
score = cax["lava"]["rr"] * cax["lava"]["hot"]
ok = (score > 0.62) & (np.abs(cand[:, 2]) < 0.90)
for c in SETTLEMENTS:
    ok &= (cand @ c["dir"]) < math.cos(c["ang"] * 2.0)
fum_idx = np.where(ok)[0][:54]

fums = []
frng = random.Random(SEED + 402)
for i in fum_idx:
    d = Vector(cand[i].tolist())
    q = surf_quat(d, d.cross(Vector((0, 0, 1)) if abs(d.z) < 0.9
                             else Vector((1, 0, 0))).normalized())
    p = d * (R * float(cm[i]))
    vr, vh = frng.uniform(0.22, 0.50) * MS, frng.uniform(0.25, 0.60) * MS
    _cone(p, q, (0, 0, vh * 0.5), vr, vr * 0.35, vh, fum_rock, fums, verts=8)
    _cyl(p, q, (0, 0, vh + 0.01 * MS), vr * 0.28, 0.05 * MS, fum_glow, fums, verts=8)
    if frng.random() < 0.35:                      # some of them are steaming
        for k in (1, 2, 3):
            t = k / 3.0
            _ico(p, q, (frng.uniform(-0.12, 0.12) * MS,
                        frng.uniform(-0.12, 0.12) * MS, vh + t * 1.5 * MS),
                 (0.24 * MS * t, 0.24 * MS * t, 0.17 * MS * t), steam_mat, fums, subd=1)
if fums:
    bpy.ops.object.select_all(action='DESELECT')
    for b in fums:
        b.select_set(True)
    bpy.context.view_layer.objects.active = fums[0]
    bpy.ops.object.join()
    bpy.context.active_object.name = "Fumaroles"
    bpy.ops.object.shade_flat()
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    print(f"  {len(fum_idx)} fumaroles ({len(fums)} parts)")

# ------------------------------------------------------------- THE HULK --
# A broken ship half-buried on an empty ash plain. Pure landmark — something to
# find out in the nothing. Placed in WORLD space (base_pt carries the position,
# the quaternion only carries orientation) so the tilted pieces stay predictable.
print("dropping the hulk…")
hull_mat = make_material("Hulk",     color_hex=0x5c5751, roughness=0.80)
hull_dk  = make_material("HulkDark", color_hex=0x33302c, roughness=0.90)
hd = Vector(HULK_DIR.tolist())
_hm, _ = height_field(np.array([HULK_DIR]))
ht1 = hd.cross(Vector((0, 0, 1))).normalized()
ht2 = hd.cross(ht1)
hp = hd * (R * float(_hm[0]))
hq = surf_quat(hd, ht1)

HK = MS * 0.62          # the wreck's own scale — a derelict freighter, but at
                        # full MS the debris field sprawled half a kilometer

def hplace(u, v, w):
    """world point offset from the hulk site: u along ht1, v along ht2, w up"""
    return hp + ht1 * (u * HK) + ht2 * (v * HK) + hd * (w * HK)

hulk = []
lie  = hq @ Matrix.Rotation(math.radians(78), 4, 'Y').to_quaternion()   # on its side
cant = hq @ Matrix.Rotation(math.radians(58), 4, 'Y').to_quaternion()   # snapped, nose down
# forward hull, then the aft section broken off behind it at a different angle
_cyl(hplace(-1.7, 0.0, 0.55), lie,  (0, 0, 0), 0.80 * HK, 5.4 * HK, hull_mat, hulk, verts=12)
_cyl(hplace(2.6, 0.5, 0.40), cant, (0, 0, 0), 0.66 * HK, 2.8 * HK, hull_dk,  hulk, verts=12)
# a sheared-off wing plate stuck in the ash, and a dead engine bell
_box(hplace(-0.3, 2.3, 0.35), hq @ Matrix.Rotation(math.radians(62), 4, 'X').to_quaternion(),
     (0, 0, 0), (2.6 * HK, 0.14 * HK, 1.5 * HK), hull_mat, hulk)
_cone(hplace(4.4, -0.4, 0.45), lie, (0, 0, 0), 0.30 * HK, 0.80 * HK, 1.1 * HK,
      hull_dk, hulk, verts=12)
# scorch debris scattered downrange of the impact
_hrng = random.Random(SEED + 555)
for _ in range(14):
    du, dv = _hrng.uniform(-6.5, 7.5), _hrng.uniform(-4.5, 4.5)
    dd = (hd * R + ht1 * (du * HK) + ht2 * (dv * HK)).normalized()
    _dm, _ = height_field(np.array([[dd.x, dd.y, dd.z]]))
    sz = _hrng.uniform(0.10, 0.34) * HK
    _box(dd * (R * float(_dm[0])), surf_quat(dd, ht1), (0, 0, sz * 0.4),
         (sz * _hrng.uniform(0.8, 2.0), sz, sz * 0.5),
         hull_mat if _hrng.random() < 0.6 else hull_dk, hulk)
bpy.ops.object.select_all(action='DESELECT')
for b in hulk:
    b.select_set(True)
bpy.context.view_layer.objects.active = hulk[0]
bpy.ops.object.join()
bpy.context.active_object.name = "Hulk"
bpy.ops.object.shade_flat()
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# -------------------------------------------------------- RIM WATCH POST --
# Four huts and a dish perched on the caldera rim, tucked between two of the
# lava channels. Gives the hero feature something human-scale to judge it by —
# without it The Maw is just a big hole with no sense of size.
print("staffing the rim post…")
_ra = LAKE_R * 1.55
_raz = -0.25                                    # azimuth: a gap between channels
rimd = (CALDERA_DIR * math.cos(_ra)
        + (CAL_T1 * math.cos(_raz) + CAL_T2 * math.sin(_raz)) * math.sin(_ra))
rimd = rimd / np.linalg.norm(rimd)
_rm, _ = height_field(rimd[None, :])
rv = Vector(rimd.tolist())
rt1 = rv.cross(Vector((0, 0, 1))).normalized()
rt2 = rv.cross(rt1)
rground = R * float(_rm[0])
post = []
_prng = random.Random(SEED + 606)
for pu, pv in ((-0.9, -0.7), (0.6, -1.1), (1.1, 0.8), (-0.5, 1.2)):
    d = (rv * R + rt1 * (pu * MS) + rt2 * (pv * MS)).normalized()
    q, p = surf_quat(d, rt1), d * rground
    hh = _prng.uniform(0.35, 0.55) * MS
    _box(p, q, (0, 0, hh * 0.5), (0.55 * MS, 0.55 * MS, hh), metal_mats[1], post)
    _ico(p, q, (0, 0, hh + 0.07 * MS), (0.05 * MS,) * 3, amber_mat, post, subd=1)
# the observation dish, aimed straight up
q, p = surf_quat(rv, rt1), rv * rground
_cyl(p, q, (0, 0, 0.9 * MS), 0.09 * MS, 1.8 * MS, metal_mats[2], post, verts=8)
_cone(p, q, (0, 0, 1.95 * MS), 0.15 * MS, 0.80 * MS, 0.34 * MS, finA_mat, post, verts=14)
_ico(p, q, (0, 0, 2.3 * MS), (0.05 * MS,) * 3, red_mat, post, subd=1)
bpy.ops.object.select_all(action='DESELECT')
for b in post:
    b.select_set(True)
bpy.context.view_layer.objects.active = post[0]
bpy.ops.object.join()
bpy.context.active_object.name = "RimPost"
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# --------------------------------------------------- NO CLOUD DECK (why) --
# EARTH and RUBICON both carry a "Clouds" node that the game spins. CINDER
# deliberately does NOT, and it should stay that way unless something changes:
#
#   Cloud decks here are opaque low-poly blobs. That works on EARTH because
#   white lumps on a blue ball still read as "cloud". On a near-black scorched
#   planet there is no color that works — tried twice. Thick+bright read as
#   gray boulders parked in orbit; wide+flat+pale read as ice sheets or scabs
#   painted on the ground, and both of them sat on top of the lava lake, which
#   is the one thing on this world you actually want to look at.
#
# So: no deck. The atmosphere shell in BODIES (0xcc5522) supplies the limb
# haze, and the ash-fall streak downwind of The Maw is PAINTED in the color
# pass instead of modeled. The game's `getObjectByName("Clouds")` lookup is
# already null-guarded, so its absence is a no-op.

# ------------------------------------------------------- ERUPTION PLUME --
# A smoke column standing over The Maw. Deliberately NOT named "Clouds" so the
# game leaves it alone and it stays anchored over the caldera instead of
# drifting off it with the ash layer.
print("venting the caldera…")
plume_mat = make_material("Plume", color_hex=0x2a2622,
                          emission_hex=0x2a2622, strength=0.02, roughness=1.0)
cdv = Vector(CALDERA_DIR.tolist())
pt1 = cdv.cross(Vector((0, 0, 1))).normalized()
pt2 = cdv.cross(pt1)
random.seed(SEED + 12)
plume_objs = []
for i in range(12):
    t = i / 11.0                                   # 0 at the shore, 1 up top
    # The column starts DOWNWIND OF THE SHORE, not over the middle. The lake is
    # LAKE_R*R ≈ 13 BU in radius; every earlier version started inside that and
    # parked an opaque gray lid on the one thing worth looking at.
    hgt = R * (1.0 + SHIELD_H + 0.015 + t * 0.20)
    drift = LAKE_R * R * 1.15 + (t ** 1.35) * 30.0
    pos = (cdv * hgt + pt1 * (drift + random.uniform(-1.2, 1.2))
                     + pt2 * random.uniform(-2.2, 2.2))
    sz = 0.8 + t * 2.2
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1.0, location=pos)
    b = bpy.context.active_object
    b.scale = (sz, sz * random.uniform(0.8, 1.1), sz * random.uniform(0.55, 0.8))
    plume_objs.append(b)
bpy.ops.object.select_all(action='DESELECT')
for b in plume_objs:
    b.select_set(True)
bpy.context.view_layer.objects.active = plume_objs[0]
bpy.ops.object.join()
plume = bpy.context.active_object
plume.name = "Plume"
bpy.ops.object.shade_flat()
plume.data.materials.append(plume_mat)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# ------------------------------------------------------------ EXPORT GLB --
glb_path = os.path.join(OUT, "cinder.glb")
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=glb_path, export_format='GLB')
print(f"wrote {glb_path}")

# ----------------------------------------------------- EXPORT HEIGHT GRID --
# Equirectangular grid of the SAME height function, quantized to uint8.
# The game bilinearly samples this to get ground height under the ship.
# 1280x640 → ~4.4u cells at CINDER's 900u in-game radius (finer than EARTH's,
# because the world is small — cheap, and landing feels solid).
print("baking height grid…")
GW, GH = 1280, 640
gy, gx = np.mgrid[0:GH, 0:GW]
lon = (gx + 0.5) / GW * 2 * np.pi - np.pi
lat = np.pi / 2 - (gy + 0.5) / GH * np.pi
gdirs = np.stack([np.cos(lat) * np.cos(lon),
                  np.cos(lat) * np.sin(lon),
                  np.sin(lat)], axis=-1).reshape(-1, 3)
gm, gaux = height_field(gdirs)          # keep the aux — the lava mask rides in it
lo, hi = float(gm.min()), float(gm.max())
q = np.round((gm - lo) / (hi - lo) * 255).astype(np.uint8)

with open(os.path.join(OUT, "cinder_height.json"), "w") as f:
    json.dump({"w": GW, "h": GH, "min": lo, "max": hi,
               "b64": base64.b64encode(q.tobytes()).decode()}, f)
print(f"wrote cinder_height.json  (height range {lo:.4f} … {hi:.4f})")

# ----------------------------------------------------- EXPORT LAVA HAZARD --
# The molten mask the game samples to decide whether the ground you just touched
# is survivable. Same 1280x640 grid, same base64 uint8 encoding, same row-major
# order as the height grid above, so the engine reads it with the existing
# sampler — only the file changes.
#
# GRADED 0-255, NOT BINARY, on purpose. The gradient is the fairness tier:
# crust edge is a burn you can power out of, molten core is not. AZURE's ocean
# is flat at exactly one height and physically can't offer that; CINDER gets it
# for free because lava_field() already returns a continuous field.
#
# `total` is the EXACT same array the colour pass and the emissive lava mesh are
# built from, so what glows is what burns — they cannot drift apart.
print("baking lava hazard mask…")
lava_g = gaux["lava"]["total"]
lava_q = np.round(np.clip(lava_g, 0.0, 1.0) * 255).astype(np.uint8)

# The camps are already carved out of the lava inside lava_field() itself, which
# multiplies by smoothstep(ang*1.25, ang*1.85, ac). Three extents have to line
# up here, and they do:
#     lava carve   zero out to ang * 1.25, back to full by 1.85
#     pan flatten  fully level to ang * 1.00, feathering out to 1.90
#     pan PAINT    the visible scorched ground ends at ang * 1.02
# So both the flat pan and the pan you can SEE sit entirely inside the zeroed
# lava — a camp cannot sit on a hot cell. Beyond 1.25 the ground is only partly
# leveled and no longer reads as camp, so lava returning there is correct.
#
# Checked against 1.25 (the carve boundary — everything inside is guaranteed
# zero) rather than the flatten's 1.9, which reaches out into terrain that is
# legitimately molten and produces a false alarm. Verified rather than assumed
# because Slagworks sits deliberately on the volcano's flank, and "an outpost
# you can't land at" is exactly the bug this check exists to catch.
for c in SETTLEMENTS:
    ac = np.arccos(np.clip(gdirs @ c["dir"], -1.0, 1.0))
    pan = ac <= c["ang"] * 1.25
    worst = float(lava_g[pan].max()) if pan.any() else 0.0
    flag = "  ok" if worst < 1e-6 else "   !! HOT PAN — camp is unlandable"
    print(f"  {c['name']:<10} peak lava over its landable pan: {worst:.5f}{flag}")

with open(os.path.join(OUT, "cinder_hazard.json"), "w") as f:
    json.dump({"w": GW, "h": GH, "min": 0.0, "max": 1.0,
               "b64": base64.b64encode(lava_q.tobytes()).decode()}, f)
print(f"wrote cinder_hazard.json  ({(lava_q > 128).mean() * 100:.1f}% molten core, "
      f"{((lava_q > 0) & (lava_q <= 128)).mean() * 100:.1f}% survivable crust edge)")

# --------------------------------------------------------------- PREVIEWS --
print("rendering previews (Cycles CPU)…")
scene.render.engine = 'CYCLES'
scene.cycles.samples = 16
scene.cycles.device = 'CPU'
scene.render.resolution_x = scene.render.resolution_y = 900
scene.view_settings.view_transform = 'Standard'

world = bpy.data.worlds.new("Space")
world.color = (0.004, 0.003, 0.003)
scene.world = world

def aim(obj, target):
    d = (target - obj.location).normalized()
    obj.rotation_mode = 'QUATERNION'
    obj.rotation_quaternion = d.to_track_quat('-Z', 'Y')

bpy.ops.object.light_add(type='SUN', location=(300, -300, 200))
sun = bpy.context.active_object
sun.data.energy = 4.5                  # CINDER is the INNER world — harsh light
aim(sun, Vector((0, 0, 0)))
bpy.ops.object.light_add(type='SUN', location=(-300, 300, -150))
fill = bpy.context.active_object
fill.data.energy = 0.30
aim(fill, Vector((0, 0, 0)))

bpy.ops.object.camera_add()
cam = bpy.context.active_object
scene.camera = cam

def cam_over(lat, lon, dist, elev_deg, az_deg):
    """Camera `dist` BU out from the GROUND POINT at (lat,lon), sitting
    `elev_deg` above the local horizon on bearing `az_deg`. Framing a
    settlement by picking two lat/lons and hoping gives you grazing tangent
    shots (v1 did exactly that) — this aims at the ground and stands back."""
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
    """Key light along the TARGET's own surface normal, swung to one side so we
    get raking shadow instead of a flat frontal wash. The system sun is fixed,
    so half the ground-level subjects sat on the night side and rendered as
    black mush — this relights per shot. Orbital shots keep the fixed sun."""
    n = target.normalized()
    t = n.cross(Vector((0, 0, 1)))
    t = t.normalized() if t.length > 1e-6 else Vector((1, 0, 0))
    return (n * 1.0 + t * 0.85).normalized() * 500

SUN_HOME = Vector((300, -300, 200))

_cal  = cam_over(CALDERA_LAT, CALDERA_LON, 74, 66, 150)
_slag = cam_over(19, -52, 62, 52, 45)
_heat = cam_over(-33, 104, 56, 52, -115)
_hulk = cam_over(HULK_LAT, HULK_LON, 70, 40, 55)
_scar = cam_over(41, 177, 46, 35, 90)

# (filename, camera position, look-at target, sun energy, relight-on-subject)
SHOTS = [
    ("cinder_preview_a.png",       Vector(ll_dir(8, 26).tolist()) * 330,
                                   Vector((0, 0, 0)), 4.5, False),   # caldera face
    ("cinder_preview_b.png",       Vector(ll_dir(-6, 150).tolist()) * 330,
                                   Vector((0, 0, 0)), 4.5, False),   # far face
    ("cinder_preview_night.png",   Vector(ll_dir(4, 20).tolist()) * 300,
                                   Vector((0, 0, 0)), 0.06, False),  # LAVA GLOW
    ("cinder_preview_caldera.png",  _cal[0],  _cal[1], 4.5, True),
    ("cinder_preview_slag.png",     _slag[0], _slag[1], 4.0, True),
    ("cinder_preview_heatsink.png", _heat[0], _heat[1], 4.0, True),
    ("cinder_preview_hulk.png",     _hulk[0], _hulk[1], 4.0, True),
    ("cinder_preview_scar.png",     _scar[0], _scar[1], 4.0, True),
]
for fname, pos, target, energy, relight in SHOTS:
    sun.data.energy = energy
    fill.data.energy = 0.30 if energy > 1.0 else 0.02
    sun.location = light_for(target) if relight else SUN_HOME
    aim(sun, Vector((0, 0, 0)))
    cam.location = pos
    aim(cam, target)
    scene.render.filepath = os.path.join(OUT, "previews", fname)
    bpy.ops.render.render(write_still=True)
    print(f"wrote {fname}")

print("DONE — cinder.glb + cinder_height.json + previews")
