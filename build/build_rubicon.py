"""
build_rubicon.py — SpaceSuck planet factory, planet #2: RUBICON
==============================================================
A red-desert super-Earth on the far side of the system, the bigger, meaner
cousin of EARTH. Same machinery as build_earth.py (edit the numbers, re-run
headless, get fresh files — the .blend is never saved), but recolored to rust,
with the ridge noise cranked for canyon-and-mesa relief and NO city or landing
pad: RUBICON is a wild frontier you set down on anywhere, so Charleston keeps
its bank monopoly.

    blender -b -P build_rubicon.py

Outputs (written next to this script):
    rubicon.glb           — the planet mesh: flat-shaded low-poly desert with
                            per-face colors, dusty polar caps, dust clouds
    rubicon_height.json   — 1280x640 lat/lon height grid (base64 uint8). The
                            game samples this for the EXACT ground height under
                            the ship — that's what makes landing work.
    rubicon_preview_*.png — Cycles renders so you can eyeball it without Blender

Built at radius 100 Blender units, same as earth.glb; the game scales the GLB
up by cfg.radius/100 (RUBICON is 3200u in the BODIES config → scale 32). Do NOT
change R to make it bigger — change `radius` in space-flight.html.

How the terrain works, in one breath: every vertex direction on the sphere gets
a "continent mask" (a sum of soft blobs, with noise-wiggled edges), the mask +
fractal + ridged noise decide the elevation; the dry basins stay at exactly
radius 100 (flat), land and canyon-country rise above it. The same function
paints the colors and fills the height grid, so what you see, what you collide
with, and what the game samples all agree.
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
SUBDIV     = 7          # icosphere subdivisions: 7 → 327,680 triangles, ~12MB.
SEED       = 137        # change this for a totally different-looking world.

# RUBICON has ONE settlement: RustHollow, a small and DANGEROUS pirate market —
# an underground bazaar dug into a low basin on the far side from Earth. Smaller
# and grungier than Charleston, and no bank/outfitter: you come here to fence
# cargo and take your chances. You can still set down on open desert anywhere.
SETTLEMENTS = [
    {"name": "RustHollow", "lat": -18.0, "lon": 12.0, "ang": 0.055, "h": 1.008,
     "structures": 46},
]
# a small, rough landing pad at the market's edge (much smaller than Earth's)
PAD_LAT, PAD_LON = -18.5, 15.0
PAD_H   = 1.009        # pad plateau height (surface multiplier)
PAD_ANG = 0.02         # pad flatten radius, radians of arc (a small rough deck)

# continents: (lat, lon, width_radians, strength) — soft blobs summed into a
# landmass mask. RUBICON is a DESERT world: mostly land, so the blobs are wide
# and strong and cover most of the sphere; the sparse gaps become dry basins.
# These are INVENTED geography, not Earth.
CONTINENTS = [
    # equatorial supercontinent belt — near-continuous land around the middle
    (2, 0, 0.52, 1.05), (6, 62, 0.46, 1.00), (-6, 122, 0.52, 1.00),
    (0, 182, 0.46, 1.00), (8, -118, 0.50, 1.00), (-8, -58, 0.46, 0.98),
    # mid-latitude highlands — canyon-and-mesa country
    (40, 28, 0.40, 0.95), (46, 150, 0.36, 0.90), (38, -92, 0.40, 0.95),
    (-40, 92, 0.40, 0.92), (-44, -32, 0.36, 0.90), (-38, -152, 0.40, 0.90),
    # polar highlands — kept modest so the poles read as red rock, not a
    # towering white massif (only a thin dust cap crowns them)
    (74, 40, 0.46, 0.80), (-76, -20, 0.46, 0.80),
    # a couple of DELIBERATELY absent zones — no blob near (24,-150) or
    # (-18, 8) — those sink to dry basin floor. That's the variety.
]

# palette — red-desert identity. Authored as sRGB hex, exported raw so the
# in-game colors land close (the game renders linear passthrough).
PAL = {
    "deep":    0x3a1508,   # deep dry basin floor
    "shallow": 0x6e2b12,   # basin edge
    "sand":    0xc86b34,   # dune / plateau
    "grass":   0x9c5a2a,   # scrubland (green slot, repurposed)
    "forest":  0x7a3f1e,   # dark mesa / dry scrub
    "rock":    0x8a4b2f,   # canyon rock (base; strata gradient overrides on relief)
    "strataLo": 0x521e0c, "strataMid": 0x923f1c, "strataHi": 0xac5626,  # rock layers floor→rim (deep rust)
    "snow":    0xcaa46a,   # warm pale dust — small accent on the highest ridges only
    "ice":     0xc19a70,   # dusty polar caps (warm, not white; small + ragged now)
    "cloud":   0xcdb598,   # tan dust cloud (muted so it doesn't blow out white)
    # pirate market — scavenged scrap palette + hazard lights
    "camp":    0x241d18, "padR":   0x2f2b28,
    "metalA":  0x6e4a38, "metalB": 0x55585c, "metalC": 0x3a3a3e,
    "contA":   0x8a4a2a, "contB":  0x3e5240, "contC":  0x7a6f5a,
    "tent":    0x8a5038, "hazard": 0xff6a1a, "redlite": 0xd11f1f,
    "salt":    0xc7b493, "saltCrack": 0x8f7a5c, "boulder": 0x6e3a22,  # salt pans + rocks
    # kept so nothing crashes if referenced; unused (no city/pad on RUBICON)
    "pad":     0x3a4148, "beacon":  0xffb066, "asphalt": 0x24282e,
    "towerA":  0x6b7280, "towerB": 0x4b5563, "towerC": 0x94a3b8,
    "towerLit": 0x3a3f4a, "window": 0xffcf8a,
}

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)   # repo root — this builder lives in build/; assets live one level up

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
    """sharp mountain ridges: fold the noise around its midline"""
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

# hero rift geometry: a great-circle canyon defined by the plane normal RIFT_N
# (points near this circle get carved) and a midpoint RIFT_M on the arc that
# gates how long the canyon runs. tuned to slash across the equatorial face.
_RA, _RB = ll_dir(-4, -38), ll_dir(8, 66)
RIFT_N = np.cross(_RA, _RB); RIFT_N = RIFT_N / np.linalg.norm(RIFT_N)
RIFT_M = ll_dir(2, 14)
PAD_DIR = ll_dir(PAD_LAT, PAD_LON)

# ------------------------------------------------------- THE HEIGHT FIELD --
# One function decides the whole planet. dirs: (N,3) unit vectors.
# Returns the surface multiplier m (basin floor = exactly 1.0, land > 1.0)
# plus the intermediate values the coloring pass needs.

def height_field(dirs):
    z = dirs[:, 2]                                     # sin(latitude)

    # continent mask: sum of soft angular blobs
    mask = np.zeros(len(dirs))
    for lat, lon, width, strength in CONTINENTS:
        d = ll_dir(lat, lon)
        ang = np.arccos(np.clip(dirs @ d, -1.0, 1.0))
        mask += strength * np.exp(-(ang / width) ** 2)

    # wiggle the basin edges so nothing looks like a perfect circle
    mask += (fbm(dirs * 2.3 + 7.7, 5, SEED) - 0.5) * 0.55

    land  = smoothstep(0.48, 0.60, mask)               # 0 = basin, 1 = land
    core  = smoothstep(0.58, 0.92, mask)               # highland interior
    hills = (fbm(dirs * 6.0 + 3.3, 5, SEED + 40) - 0.5) * 2.0
    ridge = ridged(dirs * 4.6 + 1.1, 5, SEED + 80)     # finer ridges = rounder limb

    # canyon-and-mesa relief. dropped the ridge amplitude (0.075 → 0.05) so the
    # SILHOUETTE reads as a sphere, not a potato — the drama comes back as strata
    # color (in the color pass) and the hero rift below, not a bumpy outline.
    elev = land * (0.014 + 0.006 * hills) + core * ridge * 0.05 * land
    elev = np.maximum(elev, 0.0)

    # dusty polar caps: thin, feathered, true-poles-only. high-freq + big edge
    # noise breaks up the old spilled-milk blob into a ragged dust cap.
    ice = smoothstep(0.965, 0.995, np.abs(z) + (fbm(dirs * 8.0, 4, SEED + 7) - 0.5) * 0.07)
    elev = np.maximum(elev, ice * 0.006)

    # HERO RIFT — a Valles-Marineris canyon slashing across the equator. carved
    # LAST so the max() clamps above can't fill it back in. it goes through the
    # ONE height function, so the mesh, the colors, and the sampled height grid
    # all agree — you can actually fly down into it and set down on the floor.
    perp   = np.abs(dirs @ RIFT_N)                          # ~sin(dist from the rift plane)
    alongM = np.arccos(np.clip(dirs @ RIFT_M, -1.0, 1.0))   # dist from the rift's midpoint
    rift = np.exp(-(perp / 0.05) ** 2) * smoothstep(0.95, 0.6, alongM)
    elev = elev - rift * 0.055

    m = 1.0 + elev

    # flatten the pirate settlement footprint + its landing pad into plateaus, so
    # the market sits on level ground and the sampled height grid agrees (same
    # trick as Earth's Charleston). pad after the camp so the pad wins any overlap.
    for c in SETTLEMENTS:
        cd = ll_dir(c["lat"], c["lon"])
        ang_c = np.arccos(np.clip(dirs @ cd, -1.0, 1.0))
        t = 1.0 - smoothstep(c["ang"], c["ang"] * 1.9, ang_c)
        m = m * (1.0 - t) + c["h"] * t
    ang_pad = np.arccos(np.clip(dirs @ PAD_DIR, -1.0, 1.0))
    t = 1.0 - smoothstep(PAD_ANG, PAD_ANG * 2.6, ang_pad)
    m = m * (1.0 - t) + PAD_H * t

    return m, {"mask": mask, "land": land, "elev": m - 1.0, "ice": ice, "z": z}

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

def face_colors(dirs):
    """dirs: (F,3) unit face directions → (F,4) RGBA float colors"""
    m, aux = height_field(dirs)
    mask, elev, ice, z = aux["mask"], aux["elev"], aux["ice"], aux["z"]
    n_scrub = fbm(dirs * 4.5 + 11.1, 4, SEED + 21)     # scrubland patchiness

    # start as dry basin floor: basin-edge red near the rim, dark in the deeps
    depth = smoothstep(0.50, 0.28, mask)
    col = lerp_col(hex_rgb(PAL["shallow"]), hex_rgb(PAL["deep"]), depth)

    is_land = elev > 0.0065

    # dune belt at the low land edges
    dune = is_land & (elev < 0.012) & (mask < 0.58)
    col[dune] = hex_rgb(PAL["sand"])

    # scrubland plains: patchy scrub-to-mesa reds
    scrub_t = smoothstep(0.35, 0.75, n_scrub)
    scrub = lerp_col(hex_rgb(PAL["grass"]), hex_rgb(PAL["forest"]), scrub_t)
    plains = is_land & ~dune
    col[plains] = scrub[plains]

    # SALT FLATS — the lowest, flattest dry-basin floors go pale + cracked, a
    # dead lakebed. patchy (noise-gated) so not every basin is a salt pan.
    salt_n = fbm(dirs * 8.0 + 4.4, 3, SEED + 33)
    salt = (~is_land) & (mask < 0.34) & (salt_n > 0.46)
    col[salt] = hex_rgb(PAL["salt"])
    cracks = salt & (fbm(dirs * 24.0, 2, SEED + 91) > 0.62)   # darker crack veins
    col[cracks] = hex_rgb(PAL["saltCrack"])

    # canyon rock colored by elevation: dark iron-red floor → rust → clay-ochre
    # rim. the gradient rides the relief, so canyon walls read as layered (dark
    # at the bottom, lighter up top) — a warm RED planet, no pale wash-out.
    rocky = is_land & (elev > 0.016)
    et = np.clip(elev / 0.05, 0.0, 1.0)
    rock_col = lerp_col(hex_rgb(PAL["strataLo"]), hex_rgb(PAL["strataMid"]),
                        smoothstep(0.0, 0.45, et))
    rock_col = tint(rock_col, hex_rgb(PAL["strataHi"]), smoothstep(0.6, 1.0, et))
    col[rocky] = rock_col[rocky]

    # thin, warm, feathered polar caps — true poles only, no big pale blob
    caps = is_land & (np.abs(z) > 0.975)
    col[caps] = hex_rgb(PAL["snow"])
    icy = ice > 0.5
    col[icy] = hex_rgb(PAL["ice"])

    # pirate market ground: a scorched dark pan under the structures + a rough
    # dark pad deck (painted LAST so they override the terrain colors)
    for c in SETTLEMENTS:
        cd = ll_dir(c["lat"], c["lon"])
        ang_c = np.arccos(np.clip(dirs @ cd, -1.0, 1.0))
        col[ang_c < c["ang"] * 0.92] = hex_rgb(PAL["camp"])
    ang_padc = np.arccos(np.clip(dirs @ PAD_DIR, -1.0, 1.0))
    col[ang_padc < PAD_ANG * 1.5] = hex_rgb(PAL["padR"])

    # per-face brightness jitter — the thing that makes low-poly look rich
    rng = np.random.default_rng(SEED)
    col *= (1.0 + (rng.random(len(dirs))[:, None] - 0.5) * 0.10)
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
planet.name = "Rubicon"
me = planet.data

nv = len(me.vertices)
co = np.empty(nv * 3)
me.vertices.foreach_get("co", co)
co = co.reshape(-1, 3)
dirs = co / np.linalg.norm(co, axis=1)[:, None]

m, _ = height_field(dirs)
me.vertices.foreach_set("co", (dirs * (R * m)[:, None]).ravel())
me.update()

# per-face colors, painted onto the mesh corners (all 3 corners of a
# triangle get the same color → each facet is one flat tint)
nf = len(me.polygons)
centers = np.empty(nf * 3)
me.polygons.foreach_get("center", centers)
centers = centers.reshape(-1, 3)
fdirs = centers / np.linalg.norm(centers, axis=1)[:, None]
cols = face_colors(fdirs)

attr = me.color_attributes.new(name="Col", type='FLOAT_COLOR', domain='CORNER')
attr.data.foreach_set("color", np.repeat(cols, 3, axis=0).ravel())

bpy.ops.object.shade_flat()
me.materials.append(make_material("Terrain", vertex_colors=True, roughness=0.94))

# ------------------------------------------------------- PIRATE SETTLEMENT --
# RustHollow: a small, dangerous underground market. Low scavenged structures —
# cargo-container stacks, market tents, fuel tanks, watchtowers with red hazard
# lights, and dark ramps down into the bazaar below. Same local-frame trick as
# Earth's city: build each piece in a +Z-up frame, drop it onto the sphere via
# base_pt + rot @ offset (rot maps local +Z onto the surface normal d).
print("raising the pirate market…")

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

def _ico(base_pt, rot, off, scale, mat, objs, subd=2):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=subd, radius=1.0,
                                          location=base_pt + rot @ Vector(off))
    b = bpy.context.active_object
    b.scale = Vector(scale)
    b.rotation_mode = 'QUATERNION'; b.rotation_quaternion = rot
    b.data.materials.append(mat); objs.append(b); return b

metal_mats = [make_material("MetalA", color_hex=PAL["metalA"], roughness=0.92),
              make_material("MetalB", color_hex=PAL["metalB"], roughness=0.85),
              make_material("MetalC", color_hex=PAL["metalC"], roughness=0.9)]
cont_mats  = [make_material("ContA", color_hex=PAL["contA"], roughness=0.85),
              make_material("ContB", color_hex=PAL["contB"], roughness=0.85),
              make_material("ContC", color_hex=PAL["contC"], roughness=0.85)]
tent_mat   = make_material("Tent", color_hex=PAL["tent"], roughness=1.0)
hazard_mat = make_material("Hazard", color_hex=PAL["hazard"],
                           emission_hex=PAL["hazard"], strength=3.0)
red_mat    = make_material("RedLite", color_hex=PAL["redlite"],
                           emission_hex=PAL["redlite"], strength=3.5)
hole_mat   = make_material("Hole", color_hex=0x0a0806, roughness=1.0)

def make_hab(base_pt, rot, fx, fy, h, rng, objs):
    """pick a scrappy market structure and build it"""
    k = rng.random()
    if k < 0.26:
        # CARGO CONTAINER stack — long low boxes in scavenged colors
        _box(base_pt, rot, (0, 0, 0.17), (fx * 1.4, fy * 0.7, 0.34),
             cont_mats[rng.randrange(3)], objs)
        if rng.random() < 0.55:
            _box(base_pt, rot, (0, 0, 0.52), (fx * 1.3, fy * 0.66, 0.32),
                 cont_mats[rng.randrange(3)], objs)
    elif k < 0.46:
        # market TENT / inflatable hab — a squashed dome
        _ico(base_pt, rot, (0, 0, 0.0), (fx * 0.95, fy * 0.95, h * 0.75), tent_mat, objs)
    elif k < 0.58:
        # FUEL TANK — upright cylinder capped with an amber hazard light
        r = min(fx, fy) * 0.5
        _cyl(base_pt, rot, (0, 0, h * 0.5), r, h, metal_mats[1], objs, verts=10)
        _ico(base_pt, rot, (0, 0, h + 0.06), (0.05, 0.05, 0.05), hazard_mat, objs, subd=1)
    elif k < 0.70:
        # WATCHTOWER — a tall rough post + cab + red warning light (danger)
        th = h * 2.2
        _box(base_pt, rot, (0, 0, th * 0.5), (fx * 0.5, fy * 0.5, th), metal_mats[2], objs)
        _box(base_pt, rot, (0, 0, th + 0.1), (fx * 0.8, fy * 0.8, 0.16), metal_mats[0], objs)
        _ico(base_pt, rot, (0, 0, th + 0.28), (0.06, 0.06, 0.06), red_mat, objs, subd=1)
    elif k < 0.82:
        # UNDERGROUND ENTRANCE — a low frame around a black hole (the ramp down
        # into the bazaar) + an amber light. "the market is below."
        _box(base_pt, rot, (0, 0, 0.11), (fx * 1.2, fy * 1.2, 0.22), metal_mats[2], objs)
        _box(base_pt, rot, (0, 0, 0.02), (fx * 0.7, fy * 0.7, 0.10), hole_mat, objs)
        if rng.random() < 0.6:
            _ico(base_pt, rot, (fx * 0.5, fy * 0.5, 0.3), (0.04, 0.04, 0.04),
                 hazard_mat, objs, subd=1)
    else:
        # plain SHACK / warehouse — a low rusty box, maybe a vent unit on top
        _box(base_pt, rot, (0, 0, h * 0.5), (fx, fy, h), metal_mats[rng.randrange(3)], objs)
        if rng.random() < 0.5:
            _box(base_pt, rot, (rng.uniform(-fx * 0.2, fx * 0.2),
                                rng.uniform(-fy * 0.2, fy * 0.2), h + 0.05),
                 (0.12, 0.12, 0.1), metal_mats[1], objs)

for camp in SETTLEMENTS:
    cd = Vector(ll_dir(camp["lat"], camp["lon"]).tolist())
    t1 = cd.cross(Vector((0, 0, 1))).normalized()
    t2 = cd.cross(t1)
    ground = R * camp["h"]
    cr = camp["ang"] * R
    step = 0.85                          # tighter packing than Earth — a shanty
    rng2 = random.Random(SEED + sum(ord(ch) for ch in camp["name"]))
    parts = []
    built = 0
    padv = Vector(PAD_DIR.tolist())
    n = int(math.ceil(cr / step))
    for gi in range(-n, n + 1):
        if built >= camp["structures"]:
            break
        for gj in range(-n, n + 1):
            if built >= camp["structures"]:
                break
            u = gi * step + rng2.uniform(-0.22, 0.22)
            v = gj * step + rng2.uniform(-0.22, 0.22)
            if math.hypot(u, v) > cr * 0.9:
                continue
            d = (cd * R + t1 * u + t2 * v).normalized()
            if d.dot(padv) > math.cos(PAD_ANG * 2.4):
                continue                 # keep the pad clear
            fx, fy = rng2.uniform(0.45, 0.85), rng2.uniform(0.45, 0.85)
            hh = rng2.uniform(0.28, 0.62)
            make_hab(d * ground, surf_quat(d, t1), fx, fy, hh, rng2, parts)
            built += 1
    print(f"  {camp['name']}: {built} structures, {len(parts)} parts")

    # ---- the rough landing pad: a dark octagonal deck + amber hazard posts ----
    pu = Vector(PAD_DIR.tolist())
    pquat = surf_quat(pu, t1)
    pc = pu * (R * PAD_H)
    pad_deck = make_material("PadDeck", color_hex=PAL["padR"], roughness=0.7)
    _cyl(pc, pquat, (0, 0, 0.2), 1.8, 0.4, pad_deck, parts, verts=8)
    for kk in range(4):
        a = kk / 4.0 * 2.0 * math.pi
        ox, oy = math.cos(a) * 1.55, math.sin(a) * 1.55
        _box(pc, pquat, (ox, oy, 0.35), (0.08, 0.08, 0.5), metal_mats[2], parts)
        _ico(pc, pquat, (ox, oy, 0.62), (0.07, 0.07, 0.07), hazard_mat, parts, subd=1)

    bpy.ops.object.select_all(action='DESELECT')
    for b in parts:
        b.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    cobj = bpy.context.active_object
    cobj.name = "Camp_" + camp["name"]
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# ---------------------------------------------------------------- BOULDERS --
# a few boulder fields strewn on the highland relief — ground-scale detail so a
# low fly-through has something to bank around. irregular low-poly rocks sitting
# on the sampled surface (NOT in the height grid — pure decoration).
print("scattering boulders…")
boulder_mat = make_material("Boulder", color_hex=PAL["boulder"], roughness=0.95)
padc = Vector(PAD_DIR.tolist())
boulders = []
random.seed(SEED + 5)
fields, attempts = 0, 0
while fields < 8 and attempts < 250:
    attempts += 1
    uu, vv = random.random(), random.random()
    th, ph = 2 * math.pi * uu, math.acos(2 * vv - 1)
    d = Vector((math.sin(ph) * math.cos(th), math.sin(ph) * math.sin(th), math.cos(ph)))
    if abs(d.z) > 0.88:                       # not at the poles
        continue
    if d.dot(padc) > math.cos(0.14):          # not on the market
        continue
    hm, _ = height_field(np.array([[d.x, d.y, d.z]]))
    if float(hm[0]) < 1.006:                  # only on relief/land, not basin floor
        continue
    fields += 1
    tan1 = d.cross(Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((1, 0, 0))).normalized()
    tan2 = d.cross(tan1)
    for _ in range(random.randint(4, 9)):
        pdir = (d * R + tan1 * random.uniform(-3, 3) + tan2 * random.uniform(-3, 3)).normalized()
        phm, _ = height_field(np.array([[pdir.x, pdir.y, pdir.z]]))
        pr = R * float(phm[0])
        sz = random.uniform(0.12, 0.42)
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=1.0,
                                              location=pdir * (pr + sz * 0.3))
        bl = bpy.context.active_object
        bl.scale = (sz, sz * random.uniform(0.7, 1.1), sz * random.uniform(0.5, 0.8))
        bl.rotation_mode = 'QUATERNION'
        bl.rotation_quaternion = surf_quat(pdir, tan1)   # lie flat on the ground
        bl.data.materials.append(boulder_mat)
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
    print(f"  {len(boulders)} boulders in {fields} fields")

# ---------------------------------------------------------------- CLOUDS --
# Sparse tan dust clouds — thinner and fewer than Earth's weather (a desert
# sky). Each system is 3-6 overlapping squashed blobs.
print("puffing dust clouds…")
random.seed(SEED)
cloud_mat = make_material("Cloud", color_hex=PAL["cloud"],
                          emission_hex=PAL["cloud"], strength=0.06, roughness=1.0)
cloud_objs = []
systems = 0
attempts = 0
while systems < 9 and attempts < 200:
    attempts += 1
    # random point on the sphere
    u, v = random.random(), random.random()
    theta, phi = 2 * math.pi * u, math.acos(2 * v - 1)
    d = Vector((math.sin(phi) * math.cos(theta),
                math.sin(phi) * math.sin(theta), math.cos(phi)))
    systems += 1
    quat = Vector((0, 0, 1)).rotation_difference(d)
    # local tangent axes so blobs can drift sideways within the system
    tan1 = d.cross(Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((1, 0, 0))).normalized()
    tan2 = d.cross(tan1)
    for _ in range(random.randint(3, 6)):
        off = (tan1 * random.uniform(-7, 7) + tan2 * random.uniform(-4, 4))
        pos = d * (R * random.uniform(1.04, 1.06)) + off   # low, flat dust deck
        sx, sy, sz = (random.uniform(4.0, 9.0), random.uniform(3.0, 6.0),
                      random.uniform(0.7, 1.3))
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1.0, location=pos)
        blob = bpy.context.active_object
        blob.rotation_mode = 'QUATERNION'
        blob.rotation_quaternion = quat
        blob.scale = (sx, sy, sz)
        cloud_objs.append(blob)

bpy.ops.object.select_all(action='DESELECT')
for c in cloud_objs:
    c.select_set(True)
bpy.context.view_layer.objects.active = cloud_objs[0]
bpy.ops.object.join()
clouds = bpy.context.active_object
clouds.name = "Clouds"                 # NAME MATTERS — the game spins this node
bpy.ops.object.shade_flat()
clouds.data.materials.append(cloud_mat)
# bake the transform so the object's origin is the PLANET CENTER — the game
# spins this node, and a spin around anything else flings the clouds sideways
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# ------------------------------------------------------------ EXPORT GLB --
glb_path = os.path.join(ROOT, "planets", "rubicon.glb")
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=glb_path, export_format='GLB')
print(f"wrote {glb_path}")

# ----------------------------------------------------- EXPORT HEIGHT GRID --
# Equirectangular grid of the SAME height function, quantized to uint8.
# The game bilinearly samples this to get ground height under the ship.
# 1280x640 → ~15.7u cells at RUBICON's 3200u in-game radius (matches Earth's
# fineness on the bigger world).
print("baking height grid…")
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

with open(os.path.join(ROOT, "planets", "rubicon_height.json"), "w") as f:
    json.dump({"w": GW, "h": GH, "min": lo, "max": hi,
               "b64": base64.b64encode(q.tobytes()).decode()}, f)
print("wrote rubicon_height.json")

# --------------------------------------------------------------- PREVIEWS --
print("rendering previews (Cycles CPU)…")
scene.render.engine = 'CYCLES'
scene.cycles.samples = 16
scene.cycles.device = 'CPU'
scene.render.resolution_x = scene.render.resolution_y = 900
scene.view_settings.view_transform = 'Standard'

world = bpy.data.worlds.new("Space")
world.color = (0.005, 0.005, 0.01)
scene.world = world

def aim(obj, target):
    d = (target - obj.location).normalized()
    obj.rotation_mode = 'QUATERNION'
    obj.rotation_quaternion = d.to_track_quat('-Z', 'Y')

bpy.ops.object.light_add(type='SUN', location=(300, -300, 200))
sun = bpy.context.active_object
sun.data.energy = 4.0
aim(sun, Vector((0, 0, 0)))
bpy.ops.object.light_add(type='SUN', location=(-300, 300, -150))
fill = bpy.context.active_object
fill.data.energy = 0.35                # faint fill so shadows aren't void
aim(fill, Vector((0, 0, 0)))

bpy.ops.object.camera_add()
cam = bpy.context.active_object
scene.camera = cam

SHOTS = [
    ("rubicon_preview_a.png",     Vector(ll_dir(16, 14).tolist()) * 330,
                                  Vector((0, 0, 0))),                     # rift-bearing face
    ("rubicon_preview_b.png",     Vector(ll_dir(12, 125).tolist()) * 330,
                                  Vector((0, 0, 0))),                     # far face
    ("rubicon_preview_pole.png",  Vector(ll_dir(68, 20).tolist()) * 300,
                                  Vector((0, 0, 0))),                     # dusty cap
    ("rubicon_preview_close.png", Vector(ll_dir(20, -2).tolist()) * 150,  # oblique along the rift
                                  Vector(ll_dir(-2, 26).tolist()) * 96),
    ("rubicon_preview_market.png", Vector(ll_dir(-10, 5).tolist()) * 131, # pirate market, oblique
                                   Vector(ll_dir(-19, 13).tolist()) * 100),
]
for fname, pos, target in SHOTS:
    cam.location = pos
    aim(cam, target)
    scene.render.filepath = os.path.join(ROOT, "planets", "previews", fname)
    bpy.ops.render.render(write_still=True)
    print(f"wrote {fname}")

print("DONE — rubicon.glb + rubicon_height.json + previews")
