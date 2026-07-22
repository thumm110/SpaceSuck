"""
build_icon.py — SpaceSuck desktop icon factory
==============================================
Blender is the art department. This script is the master (same pattern as
build_earth.py): edit the numbers, re-run headless, get a fresh icon. The
.blend is never saved — everything is regenerated from code.

    blender -b -P build_icon.py

Outputs (written next to this script):
    icon.png   — 512x512 RGBA hero render of ussthumm.glb on a transparent
                 background. SpaceSuck.desktop points at it, so re-run this
                 after rebuilding the ship in ~/Blender/spaceship/build_ship.py
                 and the desktop launcher picks the new one up for free.

Two things here are less obvious than they look:

  * The lights are SUNs, not area lights. Sun strength is irradiance, so it
    doesn't fall off with distance — exposure holds no matter what scale
    ussthumm.glb happens to be exported at, and nothing needs re-tuning when the
    ship changes size.

  * The camera fit is exact: it projects every mesh vertex and binary-searches
    the pullback, then centres with lens shift. Fitting a bounding *sphere*
    instead leaves the ship floating in a third of the frame — the hull is
    wide and flat (7.7 x 7.8 x 2.4), so a sphere massively over-pads it. At
    48px on the desktop that difference is the whole ballgame.
"""

import math
import os

import bpy
import numpy as np
from mathutils import Quaternion, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)   # repo root — this builder lives in build/; assets live one level up
SHIP = os.path.join(ROOT, "ship", "ussthumm.glb")
OUT = os.path.join(ROOT, "icon")  # Blender appends .png — icon.png stays at repo root (desktop launcher points here)

SIZE = 512      # square: what GNOME wants for a desktop icon
MARGIN = 0.04   # fraction of the frame left clear around the ship
SAMPLES = 128
ROLL = 22       # camera roll, degrees. The hull is near-square in plan view,
                # so this is a tightness knob, not a tilt knob: it lays the
                # silhouette along the frame's diagonal, which is the longest
                # line in a square. 0 and -67 both render the ship smaller.

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SHIP)

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit("no meshes imported from " + SHIP)


def world_vertices(objs):
    """Every evaluated vertex in world space, as an (N, 3) array."""
    deps = bpy.context.evaluated_depsgraph_get()
    chunks = []
    for o in objs:
        ev = o.evaluated_get(deps)
        me = ev.to_mesh()
        co = np.empty(len(me.vertices) * 3, dtype=np.float64)
        me.vertices.foreach_get("co", co)
        m = np.array(ev.matrix_world)
        chunks.append(co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3])
        ev.to_mesh_clear()
    return np.vstack(chunks)


P = world_vertices(meshes)
center = Vector((P.min(axis=0) + P.max(axis=0)) / 2)
radius = float(np.linalg.norm(P - np.array(center), axis=1).max())
print(f"SHIP: {len(P)} verts  center={center}  radius={radius:.3f}")

# Thruster nozzles glow, and the hull gets a faint self-lit floor so it never
# reads as a black blob — the same treatment the game applies at runtime.
for m in bpy.data.materials:
    if not m.use_nodes:
        continue
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    if not bsdf:
        continue
    color = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
    strength = bsdf.inputs.get("Emission Strength")
    if color is None or strength is None:
        continue
    color.default_value = bsdf.inputs["Base Color"].default_value
    strength.default_value = 12.0 if m.name.startswith("EngineGlow") else 0.12

scene = bpy.context.scene
# Resolution before the camera: angle_x/angle_y depend on the frame aspect.
scene.render.resolution_x = SIZE
scene.render.resolution_y = SIZE

# 3/4 hero view. glTF import puts the nose at +Y in Blender space, so +Y is
# "in front of" the ship.
cam_data = bpy.data.cameras.new("IconCam")
cam_data.lens = 85  # slight telephoto flatters the hull
cam_data.sensor_fit = "AUTO"
cam = bpy.data.objects.new("IconCam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam

view_dir = Vector((0.78, 0.95, 0.5)).normalized()
cam.location = center + view_dir * (radius * 3)
aim = (center - cam.location).to_track_quat("-Z", "Y")
cam.rotation_euler = (aim @ Quaternion((0, 0, 1), math.radians(ROLL))).to_euler()
bpy.context.view_layer.update()

# --- exact fit ---------------------------------------------------------------
# In camera space the camera looks down -Z, so backing off by t along view_dir
# adds t to every vertex's depth and leaves x/y alone. That makes the projected
# size a clean monotonic function of t, which a binary search nails exactly.
mw = np.array(cam.matrix_world)
cam_space = (P - mw[:3, 3]) @ mw[:3, :3]  # world -> camera

# Derive both half-FOVs from the sensor rather than reading angle_x/angle_y.
# angle_y is computed from sensor_height and quietly ignores sensor_fit, so
# under AUTO it lies: it says 16.07deg where the true vertical FOV of a square
# frame is angle_x's 23.91deg. AUTO fits the sensor to the frame's LONGER side
# and the shorter side scales by the aspect ratio.
res_x, res_y = scene.render.resolution_x, scene.render.resolution_y
half = cam_data.sensor_width / (2 * cam_data.lens)  # tan(half-FOV) on the long side
if res_x >= res_y:
    tan_x, tan_y = half, half * res_y / res_x
else:
    tan_x, tan_y = half * res_x / res_y, half
limit = 0.5 - MARGIN


def project(pull):
    """Vertex positions in frame units at pullback `pull` (in-frame = |q| < 0.5)."""
    depth = -cam_space[:, 2] + pull
    return (cam_space[:, 0] / (depth * 2 * tan_x),
            cam_space[:, 1] / (depth * 2 * tan_y))


def half_extent(pull):
    u, v = project(pull)
    return max((u.max() - u.min()) / 2, (v.max() - v.min()) / 2)


lo = -float((-cam_space[:, 2]).min()) + radius * 0.01  # keeps every depth > 0
hi = radius * 50.0
for _ in range(80):
    mid = (lo + hi) / 2
    if half_extent(mid) > limit:
        lo = mid
    else:
        hi = mid

cam.location = cam.location + view_dir * hi
# Centre with lens shift, not by sliding the camera sideways: shift translates
# the projection, where a sideways move would swing the perspective too.
# Sign: shift moves the *frame*, so the content slides the opposite way —
# screen = projected - shift. Hence shift = the offset we want to cancel, NOT
# its negation. Getting this backwards doubles the error and clips the hull.
u, v = project(hi)
cam_data.shift_x = (u.min() + u.max()) / 2
cam_data.shift_y = (v.min() + v.max()) / 2
bpy.context.view_layer.update()
print(f"FIT: pull={hi:.3f} fills {half_extent(hi) * 2:.3f} of frame "
      f"shift=({cam_data.shift_x:+.3f}, {cam_data.shift_y:+.3f})")


def sun(name, energy, direction, color=(1, 1, 1)):
    d = bpy.data.lights.new(name, type="SUN")
    d.energy = energy
    d.color = color
    d.angle = math.radians(8)  # soft-ish shadow edges
    o = bpy.data.objects.new(name, d)
    scene.collection.objects.link(o)
    o.rotation_euler = (-Vector(direction)).to_track_quat("-Z", "Y").to_euler()
    return o


sun("Key", 4.5, (0.7, 1.0, 0.8))
sun("Fill", 1.4, (-1.0, 0.4, 0.1), color=(0.55, 0.7, 1.0))
sun("Rim", 5.0, (-0.4, -1.0, 0.35), color=(0.6, 0.85, 1.0))

world = bpy.data.worlds.new("IconWorld")
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (0.02, 0.05, 0.12, 1.0)  # faint cold ambient
bg.inputs[1].default_value = 1.0

scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
scene.render.film_transparent = True  # transparent PNG sits on any wallpaper
scene.view_settings.view_transform = "Standard"  # punchy beats filmic at 48px
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.render.filepath = OUT
bpy.ops.render.render(write_still=True)
print("DONE — icon.png")
