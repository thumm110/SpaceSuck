# build_raider.py — RAIDER: angular enemy fighter for SpaceSuck
# Run with:  blender --background --python build_raider.py
# Same workflow as build_ship.py (edit script, re-run headless, .blend is
# disposable) — but this one also exports raider.glb for the game directly.
#
# Design language is the OPPOSITE of the USS THUMM on purpose: where the
# player ship is curvy teal/orange with aqua engines, the raider is a
# flat-shaded black dagger with blood-red trim and RED engine glow, so a
# player can tell friend from foe by silhouette + color alone.
#
# Game hooks (space-flight.html conventions):
#   +Y forward        → exports as glTF -Z, the game's nose axis, no fixup
#   "EngineGlow" mat  → the loader boosts emissive on this material name
#   ThrusterL/R nodes → glow sprites anchor to these named parts
#   GunTipL/R nodes   → ready-made anchor points if enemies get blasters

import bpy
import bmesh
from math import pi, radians
from pathlib import Path

OUT = Path.home() / "Blender" / "raider"
OUT.mkdir(parents=True, exist_ok=True)

# ---------- fresh empty scene ----------
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# ---------- materials ----------
def principled(name, color, metallic, rough):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs['Base Color'].default_value = (*color, 1.0)
    if 'Metallic' in bsdf.inputs:
        bsdf.inputs['Metallic'].default_value = metallic
    if 'Roughness' in bsdf.inputs:
        bsdf.inputs['Roughness'].default_value = rough
    return m

def emission(name, color, strength):
    # dedicated emission node material (version-proof for glowing parts)
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    em = nt.nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = (*color, 1.0)
    em.inputs['Strength'].default_value = strength
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    nt.links.new(em.outputs['Emission'], out.inputs['Surface'])
    return m

# palette: near-black gunmetal + blood red — villain colors
MAT_HULL  = principled("Gunmetal",   (0.045, 0.045, 0.055), 0.85, 0.35)  # dark body
MAT_RED   = principled("BloodRed",   (0.55, 0.02, 0.02),    0.40, 0.42)  # bright trim
MAT_RED2  = principled("DriedRed",   (0.22, 0.01, 0.015),   0.50, 0.45)  # darker trim
MAT_DARK  = principled("EngineIron", (0.02, 0.02, 0.025),   0.90, 0.30)  # engines/guns
MAT_GLASS = principled("EvilCanopy", (0.02, 0.002, 0.003),  0.40, 0.08)  # red-black glass
MAT_GLOW  = emission("EngineGlow", (1.0, 0.08, 0.02), 10.0)              # RED engine glow

# ---------- helpers (same kit as build_ship.py) ----------
def finish(obj, name, mat, parent, smooth):
    obj.name = name
    obj.data.materials.append(mat)
    obj.parent = parent
    if smooth:
        for p in obj.data.polygons:
            p.use_smooth = True
    return obj

def sphere(name, loc, scl, mat, parent):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=1.0, location=loc)
    o = bpy.context.active_object
    o.scale = scl
    return finish(o, name, mat, parent, True)

def cylinder(name, loc, rot, r, depth, mat, parent):
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=r, depth=depth, location=loc, rotation=rot)
    return finish(bpy.context.active_object, name, mat, parent, True)

def cone(name, loc, rot, r, depth, mat, parent):
    bpy.ops.mesh.primitive_cone_add(vertices=48, radius1=r, radius2=0.0, depth=depth, location=loc, rotation=rot)
    return finish(bpy.context.active_object, name, mat, parent, True)

def box_mesh(name, coords, faces, mat, parent, loc=(0, 0, 0), rot=(0, 0, 0)):
    # arbitrary flat-shaded prism from explicit vertices — the raider is
    # nearly ALL these, that's what makes it look angular and mean
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    vs = [bm.verts.new(c) for c in coords]
    for f in faces:
        bm.faces.new([vs[i] for i in f])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    o = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(o)
    o.location, o.rotation_euler = loc, rot
    o.data.materials.append(mat)
    o.parent = parent
    return o

BOX_FACES = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
# pyramid: verts 0-3 = base ring, vert 4 = apex
PYR_FACES = [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4), (3, 2, 1, 0)]

# ---------- ship root ----------
root = bpy.data.objects.new("RaiderRoot", None)
bpy.context.collection.objects.link(root)

# ---------- hull: tapered body prism + dagger nose pyramid ----------
# body: narrow at the front (matches the pyramid base), wide at the tail
BODY_LO = [(-0.55, 1.2, -0.26), (0.55, 1.2, -0.26), (0.95, -2.4, -0.34), (-0.95, -2.4, -0.34)]
BODY_HI = [(x, y, z + abs(z) * 2) for (x, y, z) in BODY_LO]  # mirror bottom ring up top
box_mesh("Body", BODY_LO + BODY_HI, BOX_FACES, MAT_HULL, root)

# nose: 4-sided pyramid whose base is EXACTLY the body's front face — seamless
NOSE = [(-0.55, 1.2, -0.26), (0.55, 1.2, -0.26), (0.55, 1.2, 0.26), (-0.55, 1.2, 0.26),
        (0.0, 3.6, 0.0)]
box_mesh("Nose", NOSE, PYR_FACES, MAT_HULL, root)

# dorsal spine housing on the rear deck (the tail fins mount into this)
SPINE_LO = [(-0.22, -0.7, 0.30), (0.22, -0.7, 0.30), (0.30, -2.35, 0.32), (-0.30, -2.35, 0.32)]
SPINE_HI = [(x, y, z + 0.22) for (x, y, z) in SPINE_LO]
box_mesh("DorsalSpine", SPINE_LO + SPINE_HI, BOX_FACES, MAT_RED2, root)

# ventral intake slab under the nose
INTAKE_LO = [(-0.35, 1.0, -0.44), (0.35, 1.0, -0.44), (0.35, 0.2, -0.44), (-0.35, 0.2, -0.44)]
INTAKE_HI = [(x, y, -0.28) for (x, y, z) in INTAKE_LO]
box_mesh("Intake", INTAKE_LO + INTAKE_HI, BOX_FACES, MAT_DARK, root)

# canopy: low sinister bubble, nearly black with a red cast
sphere("Canopy", (0, 0.55, 0.30), (0.30, 0.55, 0.18), MAT_GLASS, root)

# ---------- wings: FORWARD-swept blades with anhedral (tips droop down) ----------
# player ship sweeps back; the raider sweeps forward — instant silhouette tell
def wing(side):  # side = +1 right, -1 left
    s = side
    lo = [(0.85 * s, -0.6, -0.05),   # root, leading edge (rear of body)
          (2.90 * s,  1.0, -0.35),   # tip, leading edge (way forward)
          (2.90 * s,  0.45, -0.35),  # tip, trailing edge
          (0.85 * s, -2.2, -0.05)]   # root, trailing edge
    hi = [(x, y, z + 0.10) for (x, y, z) in lo]
    return box_mesh(f"Wing{'R' if s > 0 else 'L'}", lo + hi, BOX_FACES, MAT_HULL, root)

wing(+1)
wing(-1)

# red leading-edge strips — painted warpaint along the front of each wing
def edge_strip(side):
    s = side
    lo = [(0.85 * s, -0.45, -0.04), (2.95 * s, 1.12, -0.34),
          (2.95 * s,  0.92, -0.34), (0.85 * s, -0.75, -0.04)]
    hi = [(x, y, z + 0.12) for (x, y, z) in lo]
    box_mesh(f"WingEdge{'R' if s > 0 else 'L'}", lo + hi, BOX_FACES, MAT_RED, root)

edge_strip(+1)
edge_strip(-1)

# ---------- wingtip cannons ----------
for s in (+1, -1):
    tag = 'R' if s > 0 else 'L'
    cylinder(f"Gun{tag}",    (2.55 * s, 1.2, -0.32), (pi / 2, 0, 0), 0.09, 2.0, MAT_DARK, root)
    cone(f"GunTip{tag}",     (2.55 * s, 2.42, -0.32), (-pi / 2, 0, 0), 0.09, 0.45, MAT_RED, root)

# ---------- twin tail fins, canted WAY out — aggressive wide V ----------
FIN_PTS = [(0.45, -0.20), (-0.55, -0.20), (-1.15, 0.85), (-0.75, 0.95)]  # (y, z) outline
for s in (+1, -1):
    coords = [(-0.03, y, z) for (y, z) in FIN_PTS] + [(0.03, y, z) for (y, z) in FIN_PTS]
    box_mesh(f"Fin{'R' if s > 0 else 'L'}", coords, BOX_FACES, MAT_RED2, root,
             loc=(0.24 * s, -1.35, 0.48), rot=(0, radians(35) * s, 0))

# ---------- twin engines with red glow ----------
for s in (+1, -1):
    tag = 'R' if s > 0 else 'L'
    cylinder(f"Engine{tag}",     (0.50 * s, -3.00, 0.0), (pi / 2, 0, 0), 0.30, 1.40, MAT_DARK, root)
    cylinder(f"EngineRing{tag}", (0.50 * s, -3.62, 0.0), (pi / 2, 0, 0), 0.33, 0.12, MAT_RED, root)
    cylinder(f"Thruster{tag}",   (0.50 * s, -3.72, 0.0), (pi / 2, 0, 0), 0.24, 0.08, MAT_GLOW, root)

# ---------- idle float (5 s loop) — twitchier than the player's, feels predatory ----------
scene.render.fps = 24
scene.frame_start, scene.frame_end = 1, 120

def key(obj, path, frame, index):
    obj.keyframe_insert(data_path=path, frame=frame, index=index)

for frame, z in ((1, -0.10), (60, 0.10), (120, -0.10)):
    root.location.z = z
    key(root, "location", frame, 2)
for frame, pitch in ((1, radians(2.0)), (60, radians(-2.0)), (120, radians(2.0))):
    root.rotation_euler.x = pitch
    key(root, "rotation_euler", frame, 0)
for frame, roll in ((1, 0.0), (30, radians(3.0)), (90, radians(-3.0)), (120, 0.0)):
    root.rotation_euler.y = roll
    key(root, "rotation_euler", frame, 1)

def all_fcurves(action):
    # Blender 5.x uses layered ("slotted") actions; older versions expose .fcurves
    if hasattr(action, "fcurves"):
        return list(action.fcurves)
    fcs = []
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                fcs.extend(bag.fcurves)
    return fcs

try:  # make the loop repeat forever
    for fc in all_fcurves(root.animation_data.action):
        fc.modifiers.new(type='CYCLES')
    print("cyclic modifiers applied")
except Exception as e:
    print("cyclic modifier skipped:", e)

# ---------- export the GLB NOW, while the scene is only the ship ----------
# (camera/lights/starfield get added after this, so they never leak into
# the game asset — build_ship.py needed a manual export step, this doesn't)
bpy.ops.export_scene.gltf(filepath=str(OUT / "raider.glb"),
                          export_format='GLB', export_apply=True)
print("wrote", OUT / "raider.glb")

# ---------- starfield world ----------
world = bpy.data.worlds.new("Space")
world.use_nodes = True
nt = world.node_tree
bg = next(n for n in nt.nodes if n.type == 'BACKGROUND')
noise = nt.nodes.new('ShaderNodeTexNoise')
noise.inputs['Scale'].default_value = 600.0
if 'Detail' in noise.inputs:
    noise.inputs['Detail'].default_value = 0.0
ramp = nt.nodes.new('ShaderNodeValToRGB')
ramp.color_ramp.interpolation = 'CONSTANT'
ramp.color_ramp.elements[0].position = 0.0
ramp.color_ramp.elements[0].color = (0.0006, 0.0012, 0.004, 1)
ramp.color_ramp.elements[1].position = 0.80
ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
nt.links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
nt.links.new(ramp.outputs['Color'], bg.inputs['Color'])
bg.inputs['Strength'].default_value = 1.0
scene.world = world

# ---------- camera + lights ----------
aim = bpy.data.objects.new("Aim", None)
aim.location = (0, 0, 0.1)
bpy.context.collection.objects.link(aim)

def track(obj):
    c = obj.constraints.new('TRACK_TO')
    c.target = aim
    c.track_axis = 'TRACK_NEGATIVE_Z'
    c.up_axis = 'UP_Y'

bpy.ops.object.camera_add(location=(8.6, 7.4, 4.0))
cam = bpy.context.active_object
cam.data.lens = 45
track(cam)
scene.camera = cam

bpy.ops.object.light_add(type='SUN', location=(6, 5, 9))
sun = bpy.context.active_object
sun.data.energy = 4.0
sun.data.color = (1.0, 0.95, 0.85)
track(sun)

bpy.ops.object.light_add(type='AREA', location=(-5, -8, 5))
rim = bpy.context.active_object
rim.data.energy = 1500.0
rim.data.size = 6.0
rim.data.color = (1.0, 0.35, 0.3)   # red rim light — sells the villain look
track(rim)

bpy.ops.object.light_add(type='POINT', location=(6, 2, -3))
fill = bpy.context.active_object
fill.data.energy = 300.0
fill.data.color = (0.6, 0.75, 1.0)

# ---------- render settings ----------
scene.render.engine = 'CYCLES'
scene.cycles.samples = 64
scene.cycles.use_denoising = True
scene.render.resolution_x = 1280
scene.render.resolution_y = 720
scene.render.image_settings.file_format = 'PNG'
try:
    scene.view_settings.look = 'AgX - Punchy'
except Exception:
    pass

scene.frame_set(45)

# front 3/4 preview
scene.render.filepath = str(OUT / "preview_front.png")
bpy.ops.render.render(write_still=True)

# rear 3/4 preview (shows the red engine glow)
cam.location = (8.0, -8.8, 3.6)
scene.render.filepath = str(OUT / "preview_rear.png")
bpy.ops.render.render(write_still=True)

# restore camera and save
cam.location = (8.6, 7.4, 4.0)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "raider.blend"))
print("DONE — files in", OUT)
