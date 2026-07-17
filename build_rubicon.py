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
from mathutils import Vector

# ---------------------------------------------------------------- CONFIG --
R          = 100.0      # base radius in Blender units — MUST stay 100 (loader
                        #   divides by 100). Bigger planet = bigger cfg.radius.
SUBDIV     = 7          # icosphere subdivisions: 7 → 327,680 triangles, ~12MB.
SEED       = 137        # change this for a totally different-looking world.

# RUBICON is uncolonized: no cities, no landing pad. You land on open terrain.
CITIES = []

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
    "rock":    0x8a4b2f,   # canyon rock
    "snow":    0xd8b48a,   # warm peak dust — dust on the highest ridges, not snow
    "ice":     0xd7c3a3,   # pale dust polar caps (kept small + warm)
    "cloud":   0xcdb598,   # tan dust cloud (muted so it doesn't blow out white)
    # kept so nothing crashes if referenced; unused (no city/pad on RUBICON)
    "pad":     0x3a4148, "beacon":  0xffb066, "asphalt": 0x24282e,
    "towerA":  0x6b7280, "towerB": 0x4b5563, "towerC": 0x94a3b8,
    "towerLit": 0x3a3f4a, "window": 0xffcf8a,
}

HERE = os.path.dirname(os.path.abspath(__file__))

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
    ridge = ridged(dirs * 3.8 + 1.1, 5, SEED + 80)

    # canyon-and-mesa relief: ridge term cranked to ~1.8x Earth's for a
    # dramatically rugged desert; hills roughen the dunes and plateaus
    elev = land * (0.014 + 0.006 * hills) + core * ridge * 0.075 * land
    elev = np.maximum(elev, 0.0)

    # dusty polar caps: slightly raised, land or not. Kept SMALL — a red
    # desert wears only a thin dust cap at the true poles (lat > ~72°).
    ice = smoothstep(0.945, 0.985, np.abs(z) + (fbm(dirs * 5.0, 3, SEED + 7) - 0.5) * 0.05)
    elev = np.maximum(elev, ice * 0.006)

    m = 1.0 + elev
    return m, {"mask": mask, "land": land, "elev": m - 1.0, "ice": ice, "z": z}

# ------------------------------------------------------------- COLOR PASS --
def hex_rgb(h):
    return np.array([(h >> 16 & 255) / 255.0, (h >> 8 & 255) / 255.0, (h & 255) / 255.0])

def lerp_col(a, b, t):
    t = t[:, None]
    return a[None, :] * (1 - t) + b[None, :] * t

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

    # canyon rock fills the bulk of the highland relief — the red we want
    rocky = is_land & (elev > 0.028)
    col[rocky] = hex_rgb(PAL["rock"])

    # dusty caps ONLY on the very tippy-top ridge peaks and the true poles
    caps = (is_land & (elev > 0.090)) | (is_land & (np.abs(z) > 0.955))
    col[caps] = hex_rgb(PAL["snow"])

    icy = ice > 0.40
    col[icy] = hex_rgb(PAL["ice"])

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
        pos = d * (R * random.uniform(1.095, 1.115)) + off
        sx, sy, sz = (random.uniform(3.5, 8.0), random.uniform(2.6, 5.5),
                      random.uniform(1.1, 2.0))
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
glb_path = os.path.join(HERE, "rubicon.glb")
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

with open(os.path.join(HERE, "rubicon_height.json"), "w") as f:
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
    ("rubicon_preview_a.png",     Vector(ll_dir(12, -55).tolist()) * 330,
                                  Vector((0, 0, 0))),                     # one face
    ("rubicon_preview_b.png",     Vector(ll_dir(12, 125).tolist()) * 330,
                                  Vector((0, 0, 0))),                     # far face
    ("rubicon_preview_pole.png",  Vector(ll_dir(68, 20).tolist()) * 300,
                                  Vector((0, 0, 0))),                     # dusty cap
    ("rubicon_preview_close.png", Vector(ll_dir(2, 5).tolist()) * 150,    # canyon close-up
                                  Vector(ll_dir(2, 5).tolist()) * 100),
]
for fname, pos, target in SHOTS:
    cam.location = pos
    aim(cam, target)
    scene.render.filepath = os.path.join(HERE, fname)
    bpy.ops.render.render(write_still=True)
    print(f"wrote {fname}")

print("DONE — rubicon.glb + rubicon_height.json + previews")
