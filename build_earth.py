"""
build_earth.py — SpaceSuck planet factory, planet #1: EARTH
============================================================
Blender is the art department. This script is the master (same pattern as
build_ship.py): edit the numbers, re-run headless, get fresh files. The
.blend is never saved — everything is regenerated from code.

    blender -b -P build_earth.py

Outputs (written next to this script):
    earth.glb           — the planet mesh: flat-shaded low-poly terrain with
                          per-face colors, polar ice, cloud blobs, and a
                          landing pad + beacon at Charleston, SC
    earth_height.json   — 512x256 lat/lon height grid (base64 uint8). The
                          game samples this to know the EXACT ground height
                          under the ship — that's what makes landing work
                          without raycasting 80k triangles every frame.
    earth_preview_*.png — Cycles renders so you can eyeball the planet
                          without opening Blender

The planet is built at radius 100 Blender units; the game scales it up to
whatever radius the BODIES config says (300 → scale factor 3).

How the terrain works, in one breath: every vertex direction on the sphere
gets a "continent mask" (a sum of soft blobs placed at real Earth lat/lons,
with noise-wiggled coastlines), and the mask + fractal noise decide the
elevation; the ocean stays at exactly radius 100 (flat water), land rises
above it. The same function paints the colors and fills the height grid, so
what you see, what you collide with, and what the game samples all agree.
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
R          = 100.0      # base (sea-level) radius in Blender units
SUBDIV     = 6          # icosphere subdivisions: 6 → 81,920 triangles
SEED       = 71

# landing pad — Charleston, SC. lat north+, lon east+ (west is negative)
PAD_LAT, PAD_LON = 32.9, -80.0
PAD_H      = 1.012      # pad plateau height (surface multiplier)
PAD_ANG    = 0.05       # pad flatten radius, radians of arc (~5u at r=100)

# continents: (lat, lon, width_radians, strength) — soft blobs that sum
# into a landmass mask. Widths/strengths are ART, tuned via the previews.
CONTINENTS = [
    # Africa
    (5, 20, 0.40, 1.00), (24, 13, 0.26, 0.80), (-20, 25, 0.26, 0.85),
    # Eurasia
    (52, 20, 0.28, 0.85), (58, 62, 0.32, 0.95), (64, 105, 0.36, 1.00),
    (35, 108, 0.28, 0.90), (21, 78, 0.19, 0.85), (24, 45, 0.22, 0.80),
    (13, 103, 0.16, 0.70),
    # North America
    (57, -102, 0.34, 1.00), (41, -100, 0.28, 0.90), (65, -152, 0.20, 0.80),
    (23, -102, 0.17, 0.75), (34, -81, 0.17, 0.85),   # ← east coast: the pad
    # Greenland
    (73, -41, 0.15, 0.80),
    # South America
    (-8, -60, 0.28, 0.95), (-25, -63, 0.22, 0.85), (-42, -70, 0.14, 0.70),
    # Australia + islands
    (-25, 134, 0.23, 0.90), (37, 138, 0.09, 0.60), (-42, 172, 0.08, 0.55),
    (54, -3, 0.08, 0.60),
    # Antarctica
    (-90, 0, 0.40, 1.10),
]

# palette — authored as web-style sRGB hex, exported raw so the in-game
# colors land close to these values (the game renders linear passthrough)
PAL = {
    "deep":    0x0b2e55, "shallow": 0x2e83a0, "sand": 0xc9b77e,
    "grass":   0x4d8f3a, "forest":  0x2f6b2f, "rock": 0x7a6a52,
    "snow":    0xf2f7fa, "ice":     0xe8f2f7,
    "pad":     0x3a4148, "beacon":  0xffb066, "cloud": 0xffffff,
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

PAD_DIR = ll_dir(PAD_LAT, PAD_LON)

# ------------------------------------------------------- THE HEIGHT FIELD --
# One function decides the whole planet. dirs: (N,3) unit vectors.
# Returns the surface multiplier m (ocean = exactly 1.0, land > 1.0) plus
# the intermediate values the coloring pass needs.

def height_field(dirs):
    z = dirs[:, 2]                                     # sin(latitude)

    # continent mask: sum of soft angular blobs
    mask = np.zeros(len(dirs))
    for lat, lon, width, strength in CONTINENTS:
        d = ll_dir(lat, lon)
        ang = np.arccos(np.clip(dirs @ d, -1.0, 1.0))
        mask += strength * np.exp(-(ang / width) ** 2)

    # wiggle the coastlines so nothing looks like a perfect circle
    mask += (fbm(dirs * 2.3 + 7.7, 5, SEED) - 0.5) * 0.55

    land  = smoothstep(0.48, 0.60, mask)               # 0 = sea, 1 = land
    core  = smoothstep(0.62, 0.95, mask)               # continental interior
    hills = (fbm(dirs * 6.0 + 3.3, 5, SEED + 40) - 0.5) * 2.0
    ridge = ridged(dirs * 3.6 + 1.1, 5, SEED + 80)

    elev = land * (0.012 + 0.005 * hills) + core * ridge * 0.042 * land
    elev = np.maximum(elev, 0.0)

    # polar ice sheets: slightly raised, ocean or not
    ice = smoothstep(0.885, 0.96, np.abs(z) + (fbm(dirs * 5.0, 3, SEED + 7) - 0.5) * 0.07)
    elev = np.maximum(elev, ice * 0.006)

    m = 1.0 + elev

    # flatten a disc for the landing pad — terrain blends into a plateau
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

def face_colors(dirs):
    """dirs: (F,3) unit face directions → (F,4) RGBA float colors"""
    m, aux = height_field(dirs)
    mask, elev, ice, z = aux["mask"], aux["elev"], aux["ice"], aux["z"]
    n_forest = fbm(dirs * 4.5 + 11.1, 4, SEED + 21)    # forest patchiness

    # start as ocean: shallow teal near the coast, navy in the deeps
    depth = smoothstep(0.50, 0.28, mask)
    col = lerp_col(hex_rgb(PAL["shallow"]), hex_rgb(PAL["deep"]), depth)

    is_land = elev > 0.0065

    beach = is_land & (elev < 0.014) & (mask < 0.62)
    col[beach] = hex_rgb(PAL["sand"])

    green_t = smoothstep(0.35, 0.75, n_forest)
    greens = lerp_col(hex_rgb(PAL["grass"]), hex_rgb(PAL["forest"]), green_t)
    plains = is_land & ~beach
    col[plains] = greens[plains]

    rocky = is_land & (elev > 0.031)
    col[rocky] = hex_rgb(PAL["rock"])

    snow = (is_land & (elev > 0.052)) | (is_land & (np.abs(z) > 0.88))
    col[snow] = hex_rgb(PAL["snow"])

    icy = ice > 0.25
    col[icy] = hex_rgb(PAL["ice"])

    # pad plateau gets its own concrete color
    ang_pad = np.arccos(np.clip(dirs @ PAD_DIR, -1.0, 1.0))
    col[ang_pad < PAD_ANG * 1.4] = hex_rgb(PAL["pad"]) * 1.6

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
planet.name = "Earth"
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
me.materials.append(make_material("Terrain", vertex_colors=True, roughness=0.92))

# ----------------------------------------------------- LANDING PAD + BEACON --
print("placing landing pad at Charleston…")
pad_up = Vector(PAD_DIR.tolist())
pad_quat = Vector((0, 0, 1)).rotation_difference(pad_up)
pad_center = pad_up * (R * PAD_H)

bpy.ops.mesh.primitive_cylinder_add(radius=4.6, depth=0.6,
                                    location=pad_center + pad_up * 0.25)
pad = bpy.context.active_object
pad.name = "LandingPad"
pad.rotation_mode = 'QUATERNION'
pad.rotation_quaternion = pad_quat
pad.data.materials.append(make_material("Pad", color_hex=PAL["pad"], roughness=0.6))

# beacon: a glowing pylon at the pad's edge — visible from way out
tangent = pad_up.cross(Vector((0, 0, 1))).normalized()
bpy.ops.mesh.primitive_cylinder_add(radius=0.35, depth=5.0,
                                    location=pad_center + tangent * 4.2 + pad_up * 2.2)
beacon = bpy.context.active_object
beacon.name = "Beacon"
beacon.rotation_mode = 'QUATERNION'
beacon.rotation_quaternion = pad_quat
beacon.data.materials.append(make_material("BeaconGlow", color_hex=PAL["beacon"],
                                           emission_hex=PAL["beacon"], strength=4.0))

# ---------------------------------------------------------------- CLOUDS --
print("puffing clouds…")
random.seed(SEED)
cloud_mat = make_material("Cloud", color_hex=PAL["cloud"],
                          emission_hex=PAL["cloud"], strength=0.12, roughness=1.0)
# each cloud SYSTEM is 3-6 overlapping squashed blobs — lone spheres read
# as eggs; clusters read as weather
cloud_objs = []
systems = 0
attempts = 0
while systems < 14 and attempts < 200:
    attempts += 1
    # random point on the sphere
    u, v = random.random(), random.random()
    theta, phi = 2 * math.pi * u, math.acos(2 * v - 1)
    d = Vector((math.sin(phi) * math.cos(theta),
                math.sin(phi) * math.sin(theta), math.cos(phi)))
    if d.dot(pad_up) > math.cos(0.45):
        continue                       # keep the sky over the pad clear
    systems += 1
    quat = Vector((0, 0, 1)).rotation_difference(d)
    # local tangent axes so blobs can drift sideways within the system
    tan1 = d.cross(Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((1, 0, 0))).normalized()
    tan2 = d.cross(tan1)
    for _ in range(random.randint(3, 6)):
        off = (tan1 * random.uniform(-7, 7) + tan2 * random.uniform(-4, 4))
        pos = d * (R * random.uniform(1.06, 1.075)) + off
        sx, sy, sz = (random.uniform(3.5, 8.0), random.uniform(2.6, 5.5),
                      random.uniform(1.3, 2.4))
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
clouds.name = "Clouds"
bpy.ops.object.shade_flat()
clouds.data.materials.append(cloud_mat)
# bake the transform so the object's origin is the PLANET CENTER — the game
# spins this node, and a spin around anything else flings the clouds sideways
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# ------------------------------------------------------------ EXPORT GLB --
glb_path = os.path.join(HERE, "earth.glb")
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=glb_path, export_format='GLB')
print(f"wrote {glb_path}")

# ----------------------------------------------------- EXPORT HEIGHT GRID --
# Equirectangular grid of the SAME height function, quantized to uint8.
# The game bilinearly samples this to get ground height under the ship.
print("baking height grid…")
GW, GH = 512, 256
gy, gx = np.mgrid[0:GH, 0:GW]
lon = (gx + 0.5) / GW * 2 * np.pi - np.pi
lat = np.pi / 2 - (gy + 0.5) / GH * np.pi
gdirs = np.stack([np.cos(lat) * np.cos(lon),
                  np.cos(lat) * np.sin(lon),
                  np.sin(lat)], axis=-1).reshape(-1, 3)
gm, _ = height_field(gdirs)
lo, hi = float(gm.min()), float(gm.max())
q = np.round((gm - lo) / (hi - lo) * 255).astype(np.uint8)

with open(os.path.join(HERE, "earth_height.json"), "w") as f:
    json.dump({"w": GW, "h": GH, "min": lo, "max": hi,
               "b64": base64.b64encode(q.tobytes()).decode()}, f)
print("wrote earth_height.json")

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
    ("earth_preview_west.png", ll_dir(18, -60) * 330, Vector((0, 0, 0))),   # Americas
    ("earth_preview_east.png", ll_dir(18, 95) * 330, Vector((0, 0, 0))),    # Asia/Oz
    ("earth_preview_pad.png",  Vector(PAD_DIR.tolist()) * 170,
                               Vector(PAD_DIR.tolist()) * 100),             # pad close-up
]
for fname, pos, target in SHOTS:
    cam.location = Vector(pos.tolist()) if not isinstance(pos, Vector) else pos
    aim(cam, target)
    scene.render.filepath = os.path.join(HERE, fname)
    bpy.ops.render.render(write_still=True)
    print(f"wrote {fname}")

print("DONE — earth.glb + earth_height.json + previews")
