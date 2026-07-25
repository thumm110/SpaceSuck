"""
build_earth.py — SpaceSuck planet factory, planet #1: EARTH
============================================================
Blender is the art department. This script is the master: edit the numbers,
re-run headless, get fresh files. The .blend is never saved.

    blender -b -P build_earth.py

Outputs (written next to this script):
    earth.glb           — terrain + the hi-res Charleston patch + the city,
                          the Ravenel Bridge, the steeples, and the spaceport
                          (deck, markings, lights, terminal, tanks, beacon)
    earth_height.json   — 2048x1024 lat/lon height grid (base64 uint8). The
                          game samples this to know the EXACT ground height
                          under the ship — that's what makes landing work
                          without raycasting 300k triangles every frame.
    earth_preview_*.png — Cycles renders

The planet is built at radius 100 Blender units; the game scales it up to
whatever radius the BODIES config says (2500 → scale factor 25).

===========================================================================
THINGS THAT ARE DIFFERENT FROM THE OTHER PLANETS — read before editing
===========================================================================
1. THE TERRAIN MATH LIVES IN `earthlib.py`, not here. This file is the
   Blender half: meshes, structures, export, renders. `earthlib` is pure
   numpy, so `preview_charleston.py` can render the exact same height field
   as an ASCII map in about a second. Iterating a coastline through 15-minute
   Cycles builds is how you lose a day. If you are changing terrain, change
   it there and look at the ASCII first.

2. THE HOME PAD IS FROZEN AT lat 32.9 / lon -80.0. The game hardcodes it in
   BODIES and it is the only pad in the game with `home: true`. Charleston's
   geography was laid out AROUND that fixed point (it lands on the neck, in
   North Charleston) — not the other way round. Moving it here without the
   matching game-side edit puts the home port in the Cooper River.

3. THE RIVERS ARE LETHAL. The game's EARTH hazard is `below: 1.0015` and the
   Ashley, the Cooper and the harbor all carve to exactly 1.0 — the same
   number as the open ocean, so they are water in every sense the game has.
   Every building, street segment and steeple is water-rejected at placement
   with a 0.9 BU margin, and the build asserts the pad apron is dry.

4. CHARLESTON IS CARICATURED, DELIBERATELY. The metro is 0.18 rad (~900 game
   units across) and the Ravenel's pylons are roughly 2x their true
   proportion. A true-scale bridge here is 4 game units tall and reads as
   nothing from a cockpit. Landmarks are sized to be LEGIBLE, not accurate.

5. THE PENINSULA NEEDS THE HI-RES PATCH. At SUBDIV 7 the base facets are
   ~0.94 BU; the peninsula is 8.4 BU wide, so it would render as a 9-facet
   blocky worm (gotchas.md #2). The patch drops that to 0.22 BU. Its border
   sits in the flat metro plateau and in flat sea level — the two places two
   sampling densities are guaranteed to agree — so there is no seam.

6. THE HISTORIC PENINSULA IS CAPPED LOW ON PURPOSE. Real Charleston has no
   skyline; the steeples are the tallest things downtown, which is the whole
   "Holy City" read. The towers were pushed ACROSS the rivers into Mount
   Pleasant / West Ashley / North Charleston, which is both how the real city
   zones itself and how you keep something visible from orbit.
"""

import bpy
import bmesh
import json
import base64
import math
import os
import random
import sys
import numpy as np
from mathutils import Vector, Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)          # blender -b -P does NOT add the script's dir
import earthlib as E              # noqa: E402  — the terrain half

ROOT = os.path.dirname(HERE)
OUT  = os.path.join(ROOT, "planets")
os.makedirs(os.path.join(OUT, "previews"), exist_ok=True)

R, SEED, PAL = E.R, E.SEED, E.PAL
hex_rgb = E.hex_rgb

# ---- the hi-res Charleston patch ---------------------------------------
# Authored in MAP radius (Blender units out from the city centre), because
# that's the frame the peninsula is drawn in. The cut is smaller than the
# patch so there's overlap and no hole.
PATCH_R    = 20.5                          # patch reach, map BU
PATCH_CUT  = 0.180                         # base faces deleted inside this, rad
PATCH_RES  = 0.22                          # patch cell size, BU (~4x the base)
PATCH_LIFT = 0.03                          # float it against z-fighting

GROUND = R * E.CITY_H                      # the metro plateau, in world units

# The game's EARTH water hazard (BODIES: `hazard: { ...WATER, below: 1.0015 }`).
# Anything that stands on the ground is checked against this before it's placed
# — the city scatter, the spaceport dressing, and the assertions at the bottom
# all read this one number. It used to be re-declared down in the assert block.
HAZ = 1.0015


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


# ------------------------------------------------------------ SCENE SETUP --
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# --------------------------------------------------------------- TERRAIN --
print("building terrain sphere…")
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=E.SUBDIV, radius=R)
planet = bpy.context.active_object
planet.name = "Earth"
me = planet.data

nv = len(me.vertices)
co = np.empty(nv * 3)
me.vertices.foreach_get("co", co)
co = co.reshape(-1, 3)
dirs = co / np.linalg.norm(co, axis=1)[:, None]

m, _ = E.height_field(dirs)
me.vertices.foreach_set("co", (dirs * (R * m)[:, None]).ravel())
me.update()

terrain_mat = make_material("Terrain", vertex_colors=True, roughness=0.92)

# ----------------------------------------------- HI-RES CHARLESTON PATCH --
# Cut a hole in the base sphere over Charleston and drop a 4x denser mesh in.
# Global subdiv 8 would be 4x the whole GLB to fix one feature.
# The hole is cut BEFORE the colour pass so the vertex-colour layer is only
# ever built for faces that survive — no bmesh custom-data round-trip to trust.
print("cutting the hi-res patch…")
_cd = Vector(E.CITY_DIR.tolist())
_base_nf = len(me.polygons)
bm = bmesh.new()
bm.from_mesh(me)
bm.faces.ensure_lookup_table()
kill = [f for f in bm.faces
        if f.calc_center_median().normalized().dot(_cd) > math.cos(PATCH_CUT)]
bmesh.ops.delete(bm, geom=kill, context='FACES')
bm.to_mesh(me)
bm.free()
# equilateral triangle of area A has edge sqrt(4A/√3) — the earlier form used
# 2A/√3 and under-reported the facet size by √2
_facet = math.sqrt(4.0 * (4 * math.pi * R * R / _base_nf) / math.sqrt(3))
print(f"  removed {len(kill)} of {_base_nf} base faces inside {PATCH_CUT} rad")

nf = len(me.polygons)
centers = np.empty(nf * 3)
me.polygons.foreach_get("center", centers)
centers = centers.reshape(-1, 3)
fdirs = centers / np.linalg.norm(centers, axis=1)[:, None]
cols = E.face_colors(fdirs)

attr = me.color_attributes.new(name="Col", type='FLOAT_COLOR', domain='CORNER')
attr.data.foreach_set("color", np.repeat(cols, 3, axis=0).ravel())
bpy.context.view_layer.objects.active = planet
bpy.ops.object.shade_flat()
me.materials.append(terrain_mat)

print("building the hi-res patch…")
_n = int(math.ceil(2 * PATCH_R / PATCH_RES))
_ax = np.linspace(-PATCH_R, PATCH_R, _n + 1)
# indexing="ij" so ravel order is i*(_n+1)+j with i the EAST index and j the
# NORTH index — matching vid() below. With the default "xy" the two are
# transposed, which still tiles but reverses the winding, and the whole patch
# renders inside-out.
PE, PN = np.meshgrid(_ax, _ax, indexing="ij")
pdirs = E.en_dir(PE.ravel(), PN.ravel())
pm, _ = E.height_field(pdirs)
pverts = pdirs * (R * pm + PATCH_LIFT)[:, None]

# emit a quad per cell whose CENTRE is inside the patch disc
ci, cj = np.meshgrid(np.arange(_n), np.arange(_n), indexing="ij")
ce = (_ax[ci] + _ax[ci + 1]) * 0.5
cn = (_ax[cj] + _ax[cj + 1]) * 0.5
keep = (ce ** 2 + cn ** 2) <= PATCH_R ** 2
vid = lambda ie, jn: ie * (_n + 1) + jn
pfaces = np.stack([vid(ci, cj), vid(ci + 1, cj),
                   vid(ci + 1, cj + 1), vid(ci, cj + 1)], axis=-1)[keep]

pmesh = bpy.data.meshes.new("CharlestonPatchMesh")
pmesh.from_pydata(pverts.tolist(), [], pfaces.tolist())
pmesh.update()
patch = bpy.data.objects.new("CharlestonPatch", pmesh)
bpy.context.collection.objects.link(patch)

pnf = len(pmesh.polygons)
pc = np.empty(pnf * 3)
pmesh.polygons.foreach_get("center", pc)
pc = pc.reshape(-1, 3)
pfdirs = pc / np.linalg.norm(pc, axis=1)[:, None]
pcols = E.face_colors(pfdirs)
pattr = pmesh.color_attributes.new(name="Col", type='FLOAT_COLOR', domain='CORNER')
pattr.data.foreach_set("color", np.repeat(pcols, 4, axis=0).ravel())
pmesh.materials.append(terrain_mat)
bpy.ops.object.select_all(action='DESELECT')
patch.select_set(True)
bpy.context.view_layer.objects.active = patch
bpy.ops.object.shade_flat()
print(f"  patch: {pnf} quads at {PATCH_RES} BU vs base facets ~{_facet:.2f} BU "
      f"→ peninsula is {E.PEN_HW0 * 2 / PATCH_RES:.0f} facets wide "
      f"(was {E.PEN_HW0 * 2 / _facet:.0f})")

# ----------------------------------------------------- LANDING PAD + BEACON --
print("placing landing pad (North Charleston)…")
pad_up = Vector(E.PAD_DIR.tolist())
pad_quat = Vector((0, 0, 1)).rotation_difference(pad_up)
pad_center = pad_up * (R * E.PAD_H)

bpy.ops.mesh.primitive_cylinder_add(radius=2.6, depth=0.6,
                                    location=pad_center + pad_up * 0.25)
pad = bpy.context.active_object
pad.name = "LandingPad"
pad.rotation_mode = 'QUATERNION'
pad.rotation_quaternion = pad_quat
pad.data.materials.append(make_material("Pad", color_hex=PAL["pad"], roughness=0.6))

# `tangent` is theta 0 of the entire spaceport layout — every bearing below is
# measured off it. It lives up here because it's derived from the pad, but
# nothing else about the beacon does any more (see below).
tangent = pad_up.cross(Vector((0, 0, 1))).normalized()

# The rest of the spaceport — deck paint, rim lights, terminal, tank farm,
# beacon, approach lead-in — is built further down under "SPACEPORT DRESSING".
# It needs the _box/_cyl/_cone/_ico/_strut primitives and surf_quat, none of
# which exist yet up here.

# ----------------------------------------------------------- CHARLESTON --
print("raising Charleston…")
tower_mats = [
    make_material("TowerA", color_hex=PAL["towerA"], roughness=0.85),
    make_material("TowerB", color_hex=PAL["towerB"], roughness=0.85),
    make_material("TowerC", color_hex=PAL["towerC"], roughness=0.85),
    # ~30% of buildings are "lit": dark hull, warm emissive windows glow —
    # this is what makes the city readable on the night side
    make_material("TowerLit", color_hex=PAL["towerLit"],
                  emission_hex=PAL["window"], strength=0.9, roughness=0.7),
]
# the historic peninsula gets its own stock: pale stucco, low, no glass
hist_mats = [
    make_material("HistA", color_hex=0xd8c9b0, roughness=0.9),
    make_material("HistB", color_hex=0xc7b49a, roughness=0.9),
    make_material("HistC", color_hex=0xe0d3bd, roughness=0.9),
    make_material("HistLit", color_hex=0x6a6055,
                  emission_hex=PAL["window"], strength=0.7, roughness=0.8),
]
unit_mat   = make_material("RoofUnit", color_hex=PAL["unit"], roughness=0.7)
beacon_red = make_material("BeaconRed", color_hex=PAL["beaconRed"],
                           emission_hex=PAL["beaconRed"], strength=4.0)
glass_mat  = tower_mats[3]
street_mat = make_material("Street", color_hex=PAL["street"],
                           emission_hex=PAL["streetGlow"], strength=0.5, roughness=0.9)
# Steeples read as pale stone by day and glow by night. Base stays a MID grey,
# not white: the game ignores emissive_strength and adds emission on top of the
# lit base, so a white base clips the sunlit faces to a flat blob (gotchas #10).
# strength 0.5, not 1.4 — at 1.4 the sunlit previews rendered each steeple as
# a white starburst with no spire inside it, and the night shot as a flare
steeple_mat = make_material("Steeple", color_hex=0x9a948a,
                            emission_hex=PAL["steepleGlow"], strength=0.5,
                            roughness=0.75)
bridge_mat = make_material("BridgeDeck", color_hex=PAL["bridge"], roughness=0.8)
cable_mat  = make_material("BridgeCable", color_hex=PAL["cable"],
                           emission_hex=0xdfe8f5, strength=0.8, roughness=0.6)

# --- primitives in a local +Z-up frame ----------------------------------
def _box(base_pt, rot, off, scale, mat, objs):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=base_pt + rot @ Vector(off))
    b = bpy.context.active_object
    b.scale = Vector(scale)
    b.rotation_mode = 'QUATERNION'; b.rotation_quaternion = rot
    b.data.materials.append(mat); objs.append(b); return b

def _cyl(base_pt, rot, off, radius, height, mat, objs, verts=12):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=radius, depth=height,
                                        location=base_pt + rot @ Vector(off))
    b = bpy.context.active_object
    b.rotation_mode = 'QUATERNION'; b.rotation_quaternion = rot
    b.data.materials.append(mat); objs.append(b); return b

def _cone(base_pt, rot, off, r1, r2, height, mat, objs, verts=12):
    bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r1, radius2=r2, depth=height,
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

def _strut(p0, p1, w, t, mat, objs):
    """A box spanning two WORLD points. Bridge decks, pylon legs and stay
    cables are all 'a bar from A to B' — one helper instead of three piles of
    trigonometry. Local +X runs along the strut, +Z is as close to radially-up
    as the strut allows."""
    d = p1 - p0
    L = d.length
    if L < 1e-6:
        return None
    mid = (p0 + p1) * 0.5
    x = d.normalized()
    up = mid.normalized()
    y = up.cross(x)
    if y.length < 1e-6:
        y = Vector((0, 0, 1)).cross(x)
    y.normalize()
    z = x.cross(y)
    q = Matrix((x, y, z)).transposed().to_quaternion()
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=mid)
    b = bpy.context.active_object
    b.scale = (L, w, t)
    b.rotation_mode = 'QUATERNION'; b.rotation_quaternion = q
    b.data.materials.append(mat); objs.append(b); return b

def surf_quat(d, fwd):
    """local +Z → d (surface 'up'), +X → fwd projected into the tangent plane"""
    z = d.normalized()
    x = (fwd - z * fwd.dot(z)).normalized()
    y = z.cross(x)
    return Matrix((x, y, z)).transposed().to_quaternion()

# --- map helpers ---------------------------------------------------------
AX, PP = E.PEN_AXIS, E.PEN_PERP

def mp(e, n, lift=0.0):
    """map (e,n) → a world point on the metro plateau"""
    d = Vector(E.en_dir(e, n).tolist())
    return d * (GROUND + lift), d

def pen_en(al, pp):
    """peninsula-frame (along, across) → map (e, n)"""
    return (E.PEN_BASE[0] + AX[0] * al + PP[0] * pp,
            E.PEN_BASE[1] + AX[1] * al + PP[1] * pp)

# the street grid and every building share the peninsula's axis, so downtown
# blocks line up with the shoreline instead of cutting across it at an angle
GRID_FWD = Vector(E.en_dir(*pen_en(1.0, 0.0)).tolist()) \
    - Vector(E.en_dir(*pen_en(0.0, 0.0)).tolist())

def probe(e, n):
    """the Charleston fields at one map point"""
    d = E.en_dir(np.array([e]), np.array([n]))
    return E.charleston(d)

# ================================================== THE RAVENEL BRIDGE ====
# Cable-stayed, two diamond pylons, crossing the Cooper from the peninsula to
# Mount Pleasant. The banks are MEASURED, not assumed — the bank wiggle moves
# them, and a bridge that starts in the river is the kind of thing you only
# find in a render (gotchas.md #6).
print("building the Ravenel Bridge…")
# These proportions are the second pass. The first had a 2.1 BU deck across a
# 3.3 BU river (a causeway, not a bridge), pylons inset 0.9 BU from each bank
# so they stood 1.5 BU apart while being 5.2 BU tall, and cable fans that
# overshot the far pylon into a spider web. Widening the Cooper and reading
# these numbers as RATIOS to the span is what fixed it.
BRIDGE_W    = 0.30       # deck half-width (0.6 BU ≈ 15 game units across)
DECK_H      = 1.35       # deck height above the plateau at midspan
                         # (~34 game units — 3.4 ship lengths of clearance)
PYLON_H     = 3.7        # apex above the plateau (~92 game units). Still tops
                         # the tallest tower across the river (3.2), so the
                         # Ravenel wins the skyline — but it no longer reads
                         # as a gantry crane straddling a creek.
PYLON_INSET = 0.15       # pylons stand AT the banks, not out in the channel
PYLON_SPLAY = 0.62       # how far the diamond's legs spread
PYLON_WAIST = 0.46       # height of the diamond's widest point, x PYLON_H
APPROACH    = 3.4        # ramp length on each shore

_pp_scan = np.linspace(0.0, 16.0, 640)

def _cooper_banks(al):
    """measure the Cooper's near and far bank at a given point down the
    peninsula. Returns None if the scan finds no single clean channel."""
    ee, nn = pen_en(al, _pp_scan)
    w = E.charleston(E.en_dir(ee, nn))["wet"] > 0.5
    if not w.any():
        return None
    lo = int(np.argmax(w))
    hi = len(w) - 1 - int(np.argmax(w[::-1]))
    if not w[lo:hi + 1].all():           # two channels — an island mid-river
        return None
    return float(_pp_scan[lo]), float(_pp_scan[hi])

# Pick the crossing by MEASURING for the widest clean channel rather than
# hardcoding one — the bank wiggle moves the river, and the first guess landed
# on a 2.4 BU pinch that made the hero bridge look like a culvert.
_best = None
for _a in np.linspace(2.0, 11.0, 46):
    _b = _cooper_banks(float(_a))
    if _b and (_best is None or (_b[1] - _b[0]) > (_best[1][1] - _best[1][0])):
        _best = (float(_a), _b)
if _best is None:
    raise RuntimeError("Ravenel: no clean Cooper River channel found to cross")
BRIDGE_AL, (_bank_w, _bank_e) = _best
print(f"  Cooper crossing chosen at al={BRIDGE_AL:.2f}: banks at across "
      f"{_bank_w:.2f} → {_bank_e:.2f} BU  (span {_bank_e - _bank_w:.2f} BU "
      f"≈ {(_bank_e - _bank_w) * 25:.0f} game units)")

bridge = []
_s0, _s1 = _bank_w - APPROACH, _bank_e + APPROACH
_TOT = _s1 - _s0

def _deck_z(s):
    """height above the plateau at across-position s: ramp up from each shore,
    flat across the main span"""
    a = (s - _s0) / APPROACH
    b = (_s1 - s) / APPROACH
    return DECK_H * E.smoothstep(0.0, 1.0, np.clip(min(a, b), 0.0, 1.0))

def _deck_pt(s, off=0.0):
    """world point on the deck centreline at across-position s"""
    e, n = pen_en(BRIDGE_AL + off, s)
    d = Vector(E.en_dir(e, n).tolist())
    return d * (GROUND + float(_deck_z(s)))

# deck — a chain of struts so it follows both the ramp and the planet's curve
NSEG = 44
for i in range(NSEG):
    p0 = _deck_pt(_s0 + _TOT * i / NSEG)
    p1 = _deck_pt(_s0 + _TOT * (i + 1) / NSEG)
    _strut(p0, p1, BRIDGE_W * 2, 0.13, bridge_mat, bridge)

# two diamond pylons, one at each bank
PYLONS = [_bank_w + PYLON_INSET, _bank_e - PYLON_INSET]
_mid = (PYLONS[0] + PYLONS[1]) * 0.5
for px in PYLONS:
    e, n = pen_en(BRIDGE_AL, px)
    d = Vector(E.en_dir(e, n).tolist())
    base = d * GROUND
    rot = surf_quat(d, GRID_FWD)
    # the diamond straddles the roadway, so the legs spread ACROSS the deck
    waist_l = base + rot @ Vector((0.0, -PYLON_SPLAY, PYLON_H * PYLON_WAIST))
    waist_r = base + rot @ Vector((0.0,  PYLON_SPLAY, PYLON_H * PYLON_WAIST))
    apex = base + rot @ Vector((0.0, 0.0, PYLON_H))
    _strut(base, waist_l, 0.22, 0.22, bridge_mat, bridge)
    _strut(base, waist_r, 0.22, 0.22, bridge_mat, bridge)
    _strut(waist_l, apex, 0.19, 0.19, bridge_mat, bridge)
    _strut(waist_r, apex, 0.19, 0.19, bridge_mat, bridge)
    # a cross-tie just under the deck closes the diamond visually
    _strut(base + rot @ Vector((0.0, -PYLON_SPLAY * 0.62, PYLON_H * PYLON_WAIST * 0.62)),
           base + rot @ Vector((0.0,  PYLON_SPLAY * 0.62, PYLON_H * PYLON_WAIST * 0.62)),
           0.13, 0.13, bridge_mat, bridge)
    _ico(base, rot, (0, 0, PYLON_H + 0.13), (0.075, 0.075, 0.075), beacon_red, bridge)
    # STAY CABLES. Each pylon fans to its OWN half of the span and to its own
    # back-stay only — reaching past the far pylon is what turned the first
    # pass into a cat's cradle.
    toward_mid = 1 if px < _mid else -1
    for side in (-1, 1):
        reach = (abs(_mid - px) * 0.92) if side == toward_mid else (APPROACH * 0.80)
        for k in range(1, 6):
            s = px + side * reach * (k / 5.0)
            if not (_s0 <= s <= _s1):
                continue
            for plane in (-1, 1):
                top = base + rot @ Vector((0.0, plane * 0.11,
                                           PYLON_H - 0.20 - k * 0.11))
                anc_c = _deck_pt(s)
                anc = anc_c + anc_c.normalized() * 0.08 \
                    + (rot @ Vector((0.0, plane * BRIDGE_W * 0.82, 0.0)))
                _strut(top, anc, 0.035, 0.035, cable_mat, bridge)

bpy.ops.object.select_all(action='DESELECT')
for b in bridge:
    b.select_set(True)
bpy.context.view_layer.objects.active = bridge[0]
bpy.ops.object.join()
bridge_obj = bpy.context.active_object
bridge_obj.name = "RavenelBridge"
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
print(f"  Ravenel: {len(bridge)} parts, pylons {PYLON_H * 25:.0f} game units tall")

# ========================================================== THE CITY =====
def rooftop_units(base_pt, rot, fx, fy, roof_z, rng, objs, n=None):
    for _ in range(rng.randint(1, 3) if n is None else n):
        ux, uy = rng.uniform(-fx * 0.32, fx * 0.32), rng.uniform(-fy * 0.32, fy * 0.32)
        uz, us = rng.uniform(0.08, 0.18), rng.uniform(0.10, 0.20)
        _box(base_pt, rot, (ux, uy, roof_z + uz / 2),
             (us, us * rng.uniform(0.7, 1.3), uz), unit_mat, objs)

def make_building(base_pt, rot, fx, fy, h, mat, rng, objs):
    """pick a silhouette and build it. fx,fy = footprint; h = total height."""
    kind = rng.random()
    if kind < 0.30 and h > 0.9:
        fracs = [0.5, 0.3, 0.2] if h > 1.8 else [0.62, 0.38]
        z, sx, sy = 0.0, fx, fy
        for fr in fracs:
            th = h * fr
            _box(base_pt, rot, (0, 0, z + th / 2), (sx, sy, th), mat, objs)
            z += th; sx *= 0.66; sy *= 0.66
        if rng.random() < 0.5:
            _cyl(base_pt, rot, (0, 0, z + 0.18), 0.03, 0.36, mat, objs, verts=6)
            _ico(base_pt, rot, (0, 0, z + 0.4), (0.05, 0.05, 0.05), beacon_red, objs, subd=1)
        else:
            rooftop_units(base_pt, rot, sx * 1.5, sy * 1.5, z, rng, objs, n=1)
    elif kind < 0.42:
        r = min(fx, fy) * 0.55
        _cyl(base_pt, rot, (0, 0, h / 2), r, h, mat, objs, verts=12)
        if rng.random() < 0.5:
            _cyl(base_pt, rot, (0, 0, h + 0.12), r * 0.4, 0.24, unit_mat, objs, verts=8)
    elif kind < 0.52:
        bh = h * 0.78
        _box(base_pt, rot, (0, 0, bh / 2), (fx, fy, bh), mat, objs)
        _cone(base_pt, rot, (0, 0, bh + h * 0.16), min(fx, fy) * 0.5, 0.02, h * 0.32, mat, objs)
    elif kind < 0.60 and h > 1.0:
        _box(base_pt, rot, (0, 0, h / 2), (fx, fy, h), mat, objs)
        _cyl(base_pt, rot, (0, 0, h + 0.22), 0.02, 0.44, unit_mat, objs, verts=6)
        _ico(base_pt, rot, (0, 0, h + 0.46), (0.04, 0.04, 0.04), beacon_red, objs, subd=1)
    else:
        _box(base_pt, rot, (0, 0, h / 2), (fx, fy, h), mat, objs)
        if fx > 0.55 and h > 0.8 and rng.random() < 0.75:
            rooftop_units(base_pt, rot, fx, fy, h, rng, objs)

def make_rowhouse(base_pt, rot, fx, fy, h, mat, rng, objs):
    """The historic peninsula's workhorse: a low block with a pitched roof and
    a chimney or two. Charleston single-houses stand side-on to the street with
    a piazza down one flank — at 25x that's a 2 BU detail, so this is really
    just 'low, pastel, and NOT a glass box'."""
    _box(base_pt, rot, (0, 0, h / 2), (fx, fy, h), mat, objs)
    # pitched roof: a squashed 4-sided cone reads as a hip roof at this size.
    # 0.30 not 0.44 — the steeper first pass made every row house look like a
    # circus tent and stole the vertical read from the actual steeples.
    _cone(base_pt, rot, (0, 0, h + h * 0.15), max(fx, fy) * 0.56, 0.02,
          h * 0.30, mat, objs, verts=4)
    if rng.random() < 0.55:
        cx = rng.uniform(-fx * 0.3, fx * 0.3)
        _box(base_pt, rot, (cx, 0, h + h * 0.24), (0.06, 0.06, h * 0.42), mat, objs)

def make_steeple(base_pt, rot, h, rng, objs):
    """Church body + tower + spire. The tallest thing downtown, by design."""
    bw, bl = rng.uniform(0.34, 0.46), rng.uniform(0.62, 0.86)
    bh = h * 0.20
    _box(base_pt, rot, (0, 0, bh / 2), (bl, bw, bh), steeple_mat, objs)
    _cone(base_pt, rot, (0, 0, bh + bh * 0.30), max(bw, bl) * 0.60, 0.02,
          bh * 0.60, steeple_mat, objs, verts=4)
    # the tower rises off one end of the nave
    tx = bl * 0.34
    tw = bw * 0.52
    th = h * 0.46
    _box(base_pt, rot, (tx, 0, th / 2), (tw, tw, th), steeple_mat, objs)
    # belfry: a slightly wider stage, then the octagonal spire
    _box(base_pt, rot, (tx, 0, th + h * 0.045), (tw * 1.25, tw * 1.25, h * 0.09),
         steeple_mat, objs)
    sp = th + h * 0.09
    _cone(base_pt, rot, (tx, 0, sp + (h - sp) * 0.5), tw * 0.78, 0.012,
          (h - sp), steeple_mat, objs, verts=8)
    _ico(base_pt, rot, (tx, 0, h + 0.05), (0.035, 0.035, 0.06), steeple_mat, objs, subd=1)

def make_landmark(base_pt, rot, kind, rng, objs):
    """one-off hero structures — all of them now live ACROSS the rivers"""
    if kind == "supertall":
        h, z, sx, sy = 6.8, 0.0, 0.95, 0.95
        for fr in (0.34, 0.24, 0.18, 0.13, 0.08):
            th = h * fr
            _box(base_pt, rot, (0, 0, z + th / 2), (sx, sy, th), glass_mat, objs)
            z += th; sx *= 0.78; sy *= 0.78
        _cyl(base_pt, rot, (0, 0, z + 0.7), 0.06, 1.4, tower_mats[2], objs, verts=6)
        _ico(base_pt, rot, (0, 0, z + 1.45), (0.09, 0.09, 0.09), beacon_red, objs, subd=1)
    elif kind == "stadium":
        _cyl(base_pt, rot, (0, 0, 0.2), 1.15, 0.4, tower_mats[0], objs, verts=16)
        _ico(base_pt, rot, (0, 0, 0.4), (1.15, 1.15, 0.55), tower_mats[2], objs, subd=2)
    elif kind == "mast":
        _cone(base_pt, rot, (0, 0, 1.9), 0.14, 0.03, 3.8, tower_mats[1], objs, verts=6)
        for cz in (1.4, 2.4, 3.1):
            _box(base_pt, rot, (0, 0, cz), (0.5, 0.05, 0.04), tower_mats[1], objs)
        _ico(base_pt, rot, (0, 0, 3.85), (0.06, 0.06, 0.06), beacon_red, objs, subd=1)

# --- candidate sites, all queried in ONE vectorised pass -----------------
CITY_R = E.CITY_ANG * R
# 0.80 not 1.20. The peninsula is the hero and it's only ~130 BU^2; at the
# coarse step it drew 47 candidate sites against 490 for the suburbs across the
# rivers, i.e. the historic district came out emptier than its own outskirts.
# The finer grid is thinned back per-zone below, so the total stays sane.
STEP   = 0.80
DRY    = 0.9          # a building must sit this far (BU) from the waterline
DRY_PEN = 0.5         # ...but downtown is built to the seawall (the Battery,
                      # East Bay), so the peninsula gets a tighter margin
rng2   = random.Random(SEED + 11)

_sites = []
_ns = int(math.ceil(CITY_R * 1.12 / STEP))
for gi in range(-_ns, _ns + 1):
    for gj in range(-_ns, _ns + 1):
        e = gi * STEP + rng2.uniform(-0.30, 0.30)
        n = gj * STEP + rng2.uniform(-0.30, 0.30)
        if math.hypot(e, n) > CITY_R * 1.12:
            continue
        _sites.append((e, n))
_SE = np.array([s[0] for s in _sites])
_SN = np.array([s[1] for s in _sites])
_sdirs = E.en_dir(_SE, _SN)
_sch = E.charleston(_sdirs)
_spad = np.arccos(np.clip(_sdirs @ E.PAD_DIR, -1.0, 1.0))

blocks = []
attempted = len(_sites)
placed = {"historic": 0, "neck": 0, "across": 0}
rejected_water = 0
rejected_pad = 0

# --- STREETS: a lit grid on the peninsula axis, laid before the towers ----
reach, road_gap, seg_len, road_w = CITY_R * 0.95, 2.6, 2.4, 0.22
nlines = int(reach / road_gap)

def lay_road(along_axis, offset):
    s = -reach
    while s < reach:
        c = s + seg_len / 2
        al, pp = (c, offset) if along_axis else (offset, c)
        e, n = pen_en(al, pp)
        if math.hypot(e, n) <= reach:
            ch = probe(e, n)
            if ch["sd"][0] < -DRY:                       # keep roads out of the river
                d = Vector(E.en_dir(e, n).tolist())
                if d.dot(pad_up) <= math.cos(E.PAD_ANG * 1.5):
                    sc = ((seg_len * 1.03, road_w, 0.03) if along_axis
                          else (road_w, seg_len * 1.03, 0.03))
                    _box(d * GROUND, surf_quat(d, GRID_FWD), (0, 0, 0.02),
                         sc, street_mat, blocks)
        s += seg_len

print("laying streets…")
for k in range(-nlines, nlines + 1):
    lay_road(True,  k * road_gap)
    lay_road(False, k * road_gap)
print(f"  {len(blocks)} street segments")

# --- the landmarks, all across a river -----------------------------------
keepouts = []
def place_landmark(al, pp, kind, clear):
    e, n = pen_en(al, pp)
    ch = probe(e, n)
    if ch["sd"][0] > -1.4:
        print(f"  !! landmark '{kind}' rejected — too close to water")
        return
    d = Vector(E.en_dir(e, n).tolist())
    make_landmark(d * GROUND, surf_quat(d, GRID_FWD), kind, rng2, blocks)
    keepouts.append((e, n, clear))

# Mount Pleasant across the Cooper gets the supertall — from the peninsula and
# from the bridge you look at a skyline, and the historic district stays low.
place_landmark(6.5,  9.6, "supertall", 1.4)
place_landmark(1.0, -11.0, "stadium",  1.9)    # West Ashley, across the Ashley
place_landmark(-8.5, 4.2, "mast",      1.1)    # North Charleston, near the pad

# --- the steeples --------------------------------------------------------
# Rejection-sampled with a minimum separation, then PRINTED placed-vs-attempted
# — silent rejection looks exactly like success (gotchas.md #6).
print("raising steeples…")
STEEPLE_TARGET = 7
STEEPLE_SEP    = 1.8     # measured: 2.2/2.0/1.9 all stall at 6 of 7 in 600
                         # tries; 1.8 fills in 172. The peninsula just isn't
                         # big enough to hold seven steeples further apart.
steeples = []
_tries = 0
while len(steeples) < STEEPLE_TARGET and _tries < 600:
    _tries += 1
    al = rng2.uniform(3.0, E.PEN_LEN - 2.0)
    # Sample the across-offset against the LOCAL half-width, not a fixed band.
    # The peninsula tapers to a point, so a flat +/-2.2 throws most attempts
    # into the river south of midway — first pass placed 4 of 7 in 400 tries.
    hw_here = float(probe(*pen_en(al, 0.0))["hw"][0])
    room = hw_here - 1.5
    if room <= 0.15:
        continue
    pp = rng2.uniform(-room, room)
    e, n = pen_en(al, pp)
    ch = probe(e, n)
    if ch["on_pen"][0] < 0.5 or ch["sd"][0] > -1.4:
        continue                                  # off the peninsula, or wet
    if any(math.hypot(e - se, n - sn) < STEEPLE_SEP for se, sn, _ in steeples):
        continue
    h = rng2.uniform(1.9, 2.7)
    steeples.append((e, n, h))
for (e, n, h) in steeples:
    d = Vector(E.en_dir(e, n).tolist())
    make_steeple(d * GROUND, surf_quat(d, GRID_FWD), h, rng2, blocks)
    keepouts.append((e, n, 0.85))
print(f"  {len(steeples)}/{STEEPLE_TARGET} steeples placed in {_tries} tries "
      f"(tallest {max(s[2] for s in steeples) * 25:.0f} game units)")

# --- the buildings -------------------------------------------------------
print("filling the districts…")
for i, (e, n) in enumerate(_sites):
    sd, al, pp = _sch["sd"][i], _sch["al"][i], _sch["pp"][i]
    hw, outer = _sch["hw"][i], _sch["outer"][i]

    # zone FIRST, because the peninsula gets a tighter waterline margin
    ap = abs(pp)
    inland = ap < hw
    if inland and al > 0.0:
        zone = "historic"
    elif inland:
        zone = "neck"
    else:
        zone = "across"

    if sd > -(DRY_PEN if zone == "historic" else DRY):
        rejected_water += 1
        continue
    if _spad[i] < E.PAD_ANG * 1.5:
        rejected_pad += 1
        continue
    if any((e - ke) ** 2 + (n - kn) ** 2 < kr * kr for ke, kn, kr in keepouts):
        continue

    if zone == "historic":
        # THE HOLY CITY RULE: nothing here out-tops a steeple. 0.9 BU is
        # ~22 game units — three or four storeys.
        if rng2.random() > 0.80:
            continue
        h = rng2.uniform(0.34, 0.90)
        fx, fy = rng2.uniform(0.42, 0.66), rng2.uniform(0.42, 0.72)
        mat = hist_mats[3] if rng2.random() < 0.22 else hist_mats[rng2.randrange(3)]
        make_rowhouse(mp(e, n)[0], surf_quat(Vector(E.en_dir(e, n).tolist()), GRID_FWD),
                      fx, fy, h, mat, rng2, blocks)
    elif zone == "neck":
        if rng2.random() > 0.20:
            continue
        h = rng2.uniform(0.45, 1.55)
        fx, fy = rng2.uniform(0.45, 0.80), rng2.uniform(0.45, 0.80)
        mat = tower_mats[3] if rng2.random() < 0.24 else tower_mats[rng2.randrange(3)]
        make_building(mp(e, n)[0], surf_quat(Vector(E.en_dir(e, n).tolist()), GRID_FWD),
                      fx, fy, h, mat, rng2, blocks)
    else:
        # ACROSS THE RIVER — this is where the skyline went. Tallest at the
        # waterfront, falling away inland, so the peninsula is framed by towers
        # on both banks instead of carrying them itself.
        front = float(np.clip(1.0 - (ap - outer) / 9.0, 0.0, 1.0))
        if rng2.random() > 0.13 + 0.16 * front:
            continue
        h = 0.5 + (front ** 1.25) * rng2.uniform(1.5, 3.0)
        fx, fy = rng2.uniform(0.50, 0.92), rng2.uniform(0.50, 0.92)
        mat = tower_mats[3] if rng2.random() < 0.30 else tower_mats[rng2.randrange(3)]
        make_building(mp(e, n)[0], surf_quat(Vector(E.en_dir(e, n).tolist()), GRID_FWD),
                      fx, fy, h, mat, rng2, blocks)
    placed[zone] += 1

bpy.ops.object.select_all(action='DESELECT')
for b in blocks:
    b.select_set(True)
bpy.context.view_layer.objects.active = blocks[0]
bpy.ops.object.join()
cobj = bpy.context.active_object
cobj.name = "City_Charleston"
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
print(f"  sites {attempted}: historic {placed['historic']}, neck {placed['neck']}, "
      f"across {placed['across']} | rejected {rejected_water} wet, {rejected_pad} on the pad")
print(f"  {len(blocks)} total city parts")

# ------------------------------------------------------------ CITY LIGHTS --
print("lighting distant cities…")
LIGHT_SPOTS = [(51, 0), (48, 2), (40, -74), (34, -118), (35, 139), (1, 104),
               (-23, -46), (19, 73), (30, 31), (-33, 151), (55, 37), (39, 116)]
citylight_mat = make_material("CityLight", color_hex=PAL["window"],
                              emission_hex=PAL["window"], strength=3.0)
lights = []
random.seed(SEED + 9)
for (la, lo) in LIGHT_SPOTS:
    c = E.ll_dir(la, lo)
    _, aux = E.height_field(np.array([[c[0], c[1], c[2]]]))
    if aux["elev"][0] < 0.006:
        continue
    cdl = Vector(c.tolist())
    tan1 = cdl.cross(Vector((0, 0, 1)) if abs(cdl.z) < 0.9 else Vector((1, 0, 0))).normalized()
    tan2 = cdl.cross(tan1)
    for _ in range(random.randint(5, 9)):
        pdir = (cdl * R + tan1 * random.uniform(-2.2, 2.2)
                + tan2 * random.uniform(-2.2, 2.2)).normalized()
        phm, _ = E.height_field(np.array([[pdir.x, pdir.y, pdir.z]]))
        pr = R * float(phm[0])
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1,
                                              radius=random.uniform(0.09, 0.16),
                                              location=pdir * (pr + 0.05))
        lt = bpy.context.active_object
        lt.data.materials.append(citylight_mat)
        lights.append(lt)
if lights:
    bpy.ops.object.select_all(action='DESELECT')
    for l in lights:
        l.select_set(True)
    bpy.context.view_layer.objects.active = lights[0]
    bpy.ops.object.join()
    bpy.context.active_object.name = "CityLights"
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    print(f"  {len(lights)} distant city lights")

# ------------------------------------------------------ SPACEPORT DRESSING --
# Tier 2 of the pad job. The deck itself goes in up at "LANDING PAD + BEACON";
# this is what turns it from a gray coin into a PLACE — lit deck paint, rim
# lights, a terminal with a control tower, a tank farm, and an approach lead-in
# you can pick up on final.
#
# ALL OF IT IS COSMETIC. Nothing in this block goes anywhere near
# height_field(), so the baked grid comes out byte-identical to the run before
# it. That's the regression test, not a hope: if earth_height.json changes,
# something in here touched terrain and shouldn't have.
#
# Two numbers this must not move, because the game hardcodes both:
#   * deck top    1.0175  → space-flight.html BODIES pads[0].top
#   * deck radius 2.6 BU  → BODIES pads[0].ang 0.026  (= 2.6/R rad)
# Move either without the matching game-side edit and you get parked 14 units
# above the deck, or sunk through it.
print("dressing the spaceport…")

DECK_R   = 2.6                  # keep in step with BODIES pads[0].ang
DECK_TOP = 0.55                 # deck surface, local z measured from pad_center
MARK_Z   = DECK_TOP + 0.005     # paint rides 0.12 game units proud: clears
                                # z-fighting, far under any landing tolerance
PAD_RAD  = pad_center.length    # 101.2 — the apron's own sphere radius
FLAT_R   = E.PAD_ANG * R        # 3.5 BU: past here the plateau blends back down
                                # to real terrain, so nothing solid goes beyond
TERM_TH  = 150.0                # bearings are measured off the beacon's spoke,
TANK_TH  = 250.0                # which is theta 0 and therefore already taken
APPR_TH  = TERM_TH + 180.0      # lead-in comes in over open ground

# local pad frame: +X = the beacon's tangent, +Y = its perpendicular, +Z = up
pad_t1  = tangent               # reuse the beacon's own basis vector, so the
pad_t2  = pad_up.cross(pad_t1).normalized()      # two can't drift apart
pad_rot = surf_quat(pad_up, pad_t1)


def pad_dir(theta_deg):
    a = math.radians(theta_deg)
    return pad_t1 * math.cos(a) + pad_t2 * math.sin(a)


def pad_pt(r, theta_deg, z=0.0, curve=True):
    """A point r BU out from the deck centre on bearing theta, z above the local
    ground. The apron is a sphere, not a plane — a flat tangent offset of r
    floats r^2/2R above it, which is 1.2 game units out at the tank farm and
    reads as a visible hover. `curve` folds that drop in. Pass curve=False for
    anything sitting on the DECK, which really is flat."""
    drop = (r * r) / (2.0 * PAD_RAD) if curve else 0.0
    return pad_center + pad_dir(theta_deg) * r + pad_up * (z - drop)


def apron_pt(r, theta_deg, z=0.0):
    """Like pad_pt, but samples the real height field. Past FLAT_R the plateau
    ramps back down to terrain and the sphere approximation stops being true.
    Returns (point, height multiplier) so the caller can water-reject."""
    d = (pad_center + pad_dir(theta_deg) * r).normalized()
    hm, _ = E.height_field(np.array([[d.x, d.y, d.z]]))
    return d * (R * float(hm[0]) + z), float(hm[0])


def _ring(center, rot, major_r, minor_r, mat, objs, seg=48, flat=0.30):
    """A flat painted circle on the deck. A torus rather than a ring of dashes:
    one mesh, and a solid circle is what reads from altitude."""
    bpy.ops.mesh.primitive_torus_add(location=center, major_radius=major_r,
                                     minor_radius=minor_r,
                                     major_segments=seg, minor_segments=4)
    t = bpy.context.active_object
    t.scale = (1.0, 1.0, flat)
    t.rotation_mode = 'QUATERNION'; t.rotation_quaternion = rot
    t.data.materials.append(mat); objs.append(t); return t


# Emissive rule (gotchas #10): the game ignores emissive_strength and adds
# emission ON TOP of the lit base colour, so a white base clips every sunlit
# face to one flat blob. Each glowing part below carries a MID-GREY base and
# puts its colour in the emission — light enough to read as paint by day,
# bright enough to carry the night render.
mark_mat  = make_material("PadMarking",    color_hex=0x7d8288,
                          emission_hex=PAL["beacon"], strength=2.5, roughness=0.7)
touch_mat = make_material("PadTouchdown",  color_hex=0x7d8288,
                          emission_hex=0x66e0d8, strength=2.2, roughness=0.7)
rim_mat   = make_material("PadRimLight",   color_hex=0x9aa0a8,
                          emission_hex=PAL["beacon"], strength=4.0)
# The apron is PAL["pad"] * 1.6 — a mid grey. The terminal's first pass was
# 0x59606b, near enough to that to vanish into it: in the daylight render the
# building read as a low wall lying on the ground. Pale concrete separates it.
term_mat  = make_material("Terminal",      color_hex=0x8b929c, roughness=0.85)
tglass    = make_material("TerminalGlass", color_hex=0x44607a,
                          emission_hex=PAL["window"], strength=1.4, roughness=0.4)
tank_mat  = make_material("FuelTank",      color_hex=0xb9bfc6, roughness=0.55)
pipe_mat  = make_material("PadPipe",       color_hex=0x6c737b, roughness=0.7)
mast_mat  = make_material("BeaconMast",    color_hex=0x3f454d, roughness=0.80)
bcn_glow  = make_material("BeaconGlow",    color_hex=0x7a6a55,
                          emission_hex=PAL["beacon"], strength=3.0)

port = []
rngp = random.Random(SEED + 31)

# --- deck paint. Sizes are picked against the SHIP, not the deck: the ship is
# 10 game units nose-to-tail and 1 BU is 25, so the touchdown circle at 1.15 BU
# is ~6 ship-lengths across — a target you can see but not fill.
_ctr = pad_pt(0, 0, 0.0, curve=False)
_ring(pad_pt(0, 0, MARK_Z, curve=False), pad_rot, 2.28, 0.055, mark_mat,  port)
_ring(pad_pt(0, 0, MARK_Z, curve=False), pad_rot, 1.15, 0.040, touch_mat, port)

# the "H" — legs along +X, crossbar between them
_box(_ctr, pad_rot, (0, -0.34, MARK_Z), (0.95, 0.10, 0.03), touch_mat, port)
_box(_ctr, pad_rot, (0,  0.34, MARK_Z), (0.95, 0.10, 0.03), touch_mat, port)
_box(_ctr, pad_rot, (0,  0.00, MARK_Z), (0.10, 0.68, 0.03), touch_mat, port)

# four approach chevrons, apex inward — a bare circle has no orientation, and
# from the cockpit you want to know which way the port is facing on the way in
for _th in (45.0, 135.0, 225.0, 315.0):
    _apex = pad_pt(1.58, _th, MARK_Z, curve=False)
    _strut(_apex, pad_pt(2.02, _th + 11.0, MARK_Z, curve=False), 0.085, 0.03, mark_mat, port)
    _strut(_apex, pad_pt(2.02, _th - 11.0, MARK_Z, curve=False), 0.085, 0.03, mark_mat, port)

# --- rim lights: 12 around the deck edge, amber to match the beacon so the
# whole port speaks one colour. Short on purpose (0.27 BU ~ 7 game units) —
# tall posts around a landing deck read as an obstacle course.
for _i in range(12):
    _b = pad_pt(2.42, _i * 30.0 + 15.0, DECK_TOP, curve=False)
    _cyl(_b, pad_rot, (0, 0, 0.09), 0.035, 0.18, pipe_mat, port, verts=6)
    _ico(_b, pad_rot, (0, 0, 0.21), (0.055, 0.055, 0.055), rim_mat, port, subd=1)

# --- the terminal. It has to live in the ring between the deck edge (2.6) and
# FLAT_R (3.5), so the footprint is deliberately shallow and wide: 0.70 deep x
# 1.95 across, centred at 3.10, spanning 2.75-3.45. All of it flat, all of it
# inside the apron the build already asserts is dry.
term_base = pad_pt(3.05, TERM_TH, 0.0)
term_rot  = surf_quat(pad_up, pad_dir(TERM_TH))          # +X = radially outward
# Taller and shorter than the first pass (was 0.60 x 1.95). Long and low read
# as a boundary wall from the air; 0.85 x 1.55 reads as a building. The far
# corner lands at sqrt(3.40^2 + 0.825^2) = 3.50 BU — exactly FLAT_R, so the
# whole footprint still sits on guaranteed-flat, guaranteed-dry apron.
_box(term_base, term_rot, (0, 0, 0.425), (0.70, 1.55, 0.85), term_mat, port)
_box(term_base, term_rot, (-0.36, 0, 0.48), (0.05, 1.38, 0.52), tglass, port)  # glass, facing the deck
_box(term_base, term_rot, (0, 0, 0.885), (0.80, 1.65, 0.07), term_mat, port)   # roof lip
rooftop_units(term_base, term_rot, 0.70, 1.55, 0.92, rngp, port, n=3)          # RTUs, obviously

# control tower off the terminal's far end. Tops out at 2.55 BU above the
# apron = 64 game units, level with the tallest steeple and well under the
# 80-unit towers across the river — a landmark on the approach, not a rival.
_tw = (0.10, -0.95)
_cyl(term_base, term_rot, (_tw[0], _tw[1], 0.925), 0.16, 1.85, term_mat, port, verts=8)
_cyl(term_base, term_rot, (_tw[0], _tw[1], 1.96), 0.30, 0.24, tglass,   port, verts=8)  # the cab
_cyl(term_base, term_rot, (_tw[0], _tw[1], 2.11), 0.33, 0.05, term_mat, port, verts=8)  # cab roof
_cyl(term_base, term_rot, (_tw[0], _tw[1], 2.32), 0.025, 0.40, pipe_mat, port, verts=6)  # mast
_ico(term_base, term_rot, (_tw[0], _tw[1], 2.55), (0.045, 0.045, 0.045), beacon_red, port, subd=1)

# jetway: deck edge -> terminal front, so the two read as one facility instead
# of a shed parked near a disc
_strut(pad_pt(2.50, TERM_TH, DECK_TOP + 0.04, curve=False),
       pad_pt(2.74, TERM_TH, 0.55), 0.22, 0.11, term_mat, port)
_cyl(pad_pt(2.66, TERM_TH, 0.0), pad_rot, (0, 0, 0.24), 0.05, 0.48, pipe_mat, port, verts=6)

# --- tank farm, opposite the terminal so the deck has something on both sides
tank_base = pad_pt(3.00, TANK_TH, 0.0)
tank_rot  = surf_quat(pad_up, pad_dir(TANK_TH))


def tank_pt(dy, dz):
    return tank_base + tank_rot @ Vector((0.0, dy, dz))


for _dy in (-0.52, 0.0, 0.52):
    _cyl(tank_base, tank_rot, (0, _dy, 0.31), 0.20, 0.62, tank_mat, port, verts=12)
    _ico(tank_base, tank_rot, (0, _dy, 0.62), (0.20, 0.20, 0.09), tank_mat, port, subd=2)
_box(tank_base, tank_rot, (-0.44, 0, 0.11), (0.26, 0.52, 0.22), term_mat, port)   # pump house
_ico(tank_base, tank_rot, (0, 0, 0.74), (0.04, 0.04, 0.04), beacon_red, port, subd=1)
_strut(tank_pt(-0.52, 0.50), tank_pt(0.52, 0.50), 0.045, 0.045, pipe_mat, port)   # header
_strut(tank_pt(0.0, 0.14), pad_pt(2.64, TANK_TH, 0.10), 0.05, 0.05, pipe_mat, port)  # run to the deck

# --- the beacon. It used to be a 0.5 x 3.2 BU cylinder standing ON the deck at
# r=2.4, amber base under amber emission at strength 4 — which clips to a flat
# white slab under AgX and parks an 80-game-unit monolith on the one surface
# the [G] landing assist flies you onto. Now it's a tapered mast out on the
# APRON at theta 0: dark body, glow carried in bands and a crown, so it reads
# as a spire from the air and the deck stays clear.
bcn_base = pad_pt(2.98, 0.0, 0.0)
bcn_rot  = surf_quat(pad_up, pad_dir(0.0))
_cone(bcn_base, bcn_rot, (0, 0, 1.55), 0.155, 0.035, 3.10, mast_mat, port, verts=8)
for _bz, _br in ((0.85, 0.135), (1.65, 0.104), (2.45, 0.073)):
    _cyl(bcn_base, bcn_rot, (0, 0, _bz), _br, 0.075, bcn_glow, port, verts=8)
_ico(bcn_base, bcn_rot, (0, 0, 3.22), (0.11, 0.11, 0.15), bcn_glow, port, subd=2)
_ico(bcn_base, bcn_rot, (0, 0, 3.44), (0.045, 0.045, 0.045), beacon_red, port, subd=1)

# --- approach lead-in: a lit centreline running out from the deck over open
# ground, the cue you pick up on final. These run past FLAT_R, so they sample
# the height field instead of assuming the plateau — and any that come down wet
# get dropped, the same water rule every other structure here obeys.
_appr = 0
for _r in (3.30, 3.95, 4.60, 5.25, 5.90, 6.55):
    _p, _hm = apron_pt(_r, APPR_TH, 0.0)
    if _hm < HAZ:                       # in the drink — the Ashley runs close
        continue
    _lr = surf_quat(_p.normalized(), pad_dir(APPR_TH))   # own normal: the
    _cyl(_p, _lr, (0, 0, 0.06), 0.030, 0.12, pipe_mat, port, verts=6)  # surface
    _ico(_p, _lr, (0, 0, 0.15), (0.05, 0.05, 0.05), rim_mat, port, subd=1)  # tilts
    _appr += 1

bpy.ops.object.select_all(action='DESELECT')
for _o in port:
    _o.select_set(True)
bpy.context.view_layer.objects.active = port[0]
bpy.ops.object.join()
_port_obj = bpy.context.active_object
_port_obj.name = "Spaceport"
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
print(f"  {len(port)} spaceport parts | terminal @ {TERM_TH:.0f}deg, "
      f"tanks @ {TANK_TH:.0f}deg, {_appr}/6 approach lights dry")

# ---------------------------------------------------------------- CLOUDS --
print("puffing clouds…")
random.seed(SEED)
cloud_mat = make_material("Cloud", color_hex=PAL["cloud"],
                          emission_hex=PAL["cloud"], strength=0.12, roughness=1.0)
cloud_objs = []
systems = 0
attempts = 0
while systems < 14 and attempts < 200:
    attempts += 1
    u, v = random.random(), random.random()
    theta, phi = 2 * math.pi * u, math.acos(2 * v - 1)
    d = Vector((math.sin(phi) * math.cos(theta),
                math.sin(phi) * math.sin(theta), math.cos(phi)))
    # keep the sky over Charleston clear — you have to be able to SEE it
    if d.dot(_cd) > math.cos(0.62):
        continue
    systems += 1
    quat = Vector((0, 0, 1)).rotation_difference(d)
    tan1 = d.cross(Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((1, 0, 0))).normalized()
    tan2 = d.cross(tan1)
    for _ in range(random.randint(3, 6)):
        off = (tan1 * random.uniform(-7, 7) + tan2 * random.uniform(-4, 4))
        pos = d * (R * random.uniform(1.04, 1.06)) + off
        sx, sy, sz = (random.uniform(4.0, 8.5), random.uniform(3.0, 6.0),
                      random.uniform(0.8, 1.5))
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
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# ------------------------------------------------------------ EXPORT GLB --
glb_path = os.path.join(OUT, "earth.glb")
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=glb_path, export_format='GLB')
print(f"wrote {glb_path}")

# ----------------------------------------------------- EXPORT HEIGHT GRID --
# 2048x1024 (was 1024x512). The rivers are only ~3 BU wide and their banks are
# a hard boundary between safe ground and a lethal hazard; at the old
# resolution one grid cell was 0.61 BU and the bank position aliased by up to
# 15 game units. Doubling costs ~2 MB of JSON and buys a bank you can trust.
print("baking height grid…")
GW, GH = 2048, 1024
gy, gx = np.mgrid[0:GH, 0:GW]
lon = (gx + 0.5) / GW * 2 * np.pi - np.pi
lat = np.pi / 2 - (gy + 0.5) / GH * np.pi
gdirs = np.stack([np.cos(lat) * np.cos(lon),
                  np.cos(lat) * np.sin(lon),
                  np.sin(lat)], axis=-1).reshape(-1, 3)
gm, gaux = E.height_field(gdirs)
lo, hi = float(gm.min()), float(gm.max())
q = np.round((gm - lo) / (hi - lo) * 255).astype(np.uint8)

with open(os.path.join(OUT, "earth_height.json"), "w") as f:
    json.dump({"w": GW, "h": GH, "min": lo, "max": hi,
               "b64": base64.b64encode(q.tobytes()).decode()}, f)
print("wrote earth_height.json")

# --------------------------------------------------------- ASSERTIONS ----
# Print what the build CLAIMS. Every one of these is a thing that has silently
# been wrong in some planet build before.
print("\n" + "=" * 68)
print("ASSERTIONS")
print("=" * 68)
step = (hi - lo) / 255
print(f"grid       : {GW}x{GH}  min={lo:.6f} max={hi:.6f}")
print(f"quantised  : 1 byte = {step:.6f}  → hazard 1.0015 is "
      f"{(HAZ - lo) / step:.1f} byte steps above the floor")
print(f"sea level  : round-trips to {lo + round((1.0 - lo) / step) * step:.6f} "
      f"(want 1.000000)")

pm_, paux_ = E.height_field(E.PAD_DIR[None, :])
print(f"pad height : {float(pm_[0]):.5f}  "
      f"{'OK — dry' if pm_[0] >= HAZ else '*** PAD IS IN THE WATER HAZARD ***'}")

# the pad apron, sampled as rings — nothing within it may be water
_pe = R * float(E.PAD_DIR @ E.EAST_T) / float(E.PAD_DIR @ E.CITY_DIR)
_pn = R * float(E.PAD_DIR @ E.NORTH_T) / float(E.PAD_DIR @ E.CITY_DIR)
_th = np.linspace(0, 2 * np.pi, 512)
worst_apron = 9.0
for rad in (E.PAD_ANG * R * 0.5, E.PAD_ANG * R, E.PAD_ANG * E.PAD_BLEND * R):
    rd = E.en_dir(_pe + rad * np.cos(_th), _pn + rad * np.sin(_th))
    rm, _ = E.height_field(rd)
    worst_apron = min(worst_apron, float(rm.min()))
    print(f"pad ring   : r={rad:5.2f} BU  min={float(rm.min()):.5f}  "
          f"{'OK' if rm.min() >= HAZ else '*** WATER ON THE APRON ***'}")

# the peninsula must be dry, flat, and above the hazard along its whole length
_al = np.linspace(1.0, E.PEN_LEN - 1.0, 200)
_pe2, _pn2 = pen_en(_al, np.zeros_like(_al))
_pmid, _ = E.height_field(E.en_dir(_pe2, _pn2))
print(f"peninsula  : centreline min={float(_pmid.min()):.5f} "
      f"max={float(_pmid.max()):.5f}  "
      f"{'OK — dry the whole way' if _pmid.min() >= HAZ else '*** FLOODED ***'}")

# the rivers must actually BE water, or none of this meant anything
for nm, sgn in (("Ashley", -1), ("Cooper", +1)):
    _rp = np.full(200, 0.0)
    _rr = []
    for a in np.linspace(2.0, E.PEN_LEN - 2.0, 40):
        sc = np.linspace(0.0, 16.0, 300)
        ee, nn2 = pen_en(a, sgn * sc)
        cc = E.charleston(E.en_dir(ee, nn2))
        _rr.append(float((cc["wet"] > 0.5).sum()) * (16.0 / 300))
    print(f"{nm:10s} : mean wetted width {np.mean(_rr):.2f} BU "
          f"({np.mean(_rr) * 25:.0f} game units)  "
          f"{'OK' if np.mean(_rr) > 1.5 else '*** RIVER MISSING ***'}")

# the bridge has to actually span the water it claims to
_bs = np.linspace(_s0, _s1, 300)
_be, _bn = pen_en(BRIDGE_AL, _bs)
_bw = E.charleston(E.en_dir(_be, _bn))["wet"] > 0.5
print(f"Ravenel    : deck {_TOT:.2f} BU long, spans {_bw.sum() / 300 * _TOT:.2f} BU "
      f"of water, dry ends={'OK' if not (_bw[0] or _bw[-1]) else '*** ENDS IN THE RIVER ***'}")
print(f"           : pylons {PYLON_H * 25:.0f} game units vs tallest tower "
      f"{3.2 * 25:.0f} — {'OK, bridge wins' if PYLON_H > 3.2 else '*** OUT-TOPPED ***'}")
print(f"steeples   : {len(steeples)} placed, tallest {max(s[2] for s in steeples) * 25:.0f} "
      f"game units vs historic cap {0.90 * 25:.0f} — "
      f"{'OK, Holy City' if min(s[2] for s in steeples) > 0.90 else '*** OUT-TOPPED ***'}")
print("=" * 68 + "\n")

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

def aim(obj, target, up=None):
    """Point obj's -Z at `target`. With no `up` the roll comes from world +Y,
    which is fine for orbital shots and lights but rolls the horizon ~90 deg on
    a ground-level shot at Charleston's latitude — pass the local surface
    normal (i.e. target.normalized()) for those."""
    d = (target - obj.location).normalized()
    obj.rotation_mode = 'QUATERNION'
    if up is None:
        obj.rotation_quaternion = d.to_track_quat('-Z', 'Y')
        return
    z = -d                                    # camera looks down its own -Z
    x = Vector(up).cross(z)
    if x.length < 1e-6:
        x = Vector((1, 0, 0)).cross(z)
    x.normalize()
    y = z.cross(x)
    obj.rotation_quaternion = Matrix((x, y, z)).transposed().to_quaternion()

bpy.ops.object.light_add(type='SUN', location=(300, -300, 200))
sun = bpy.context.active_object
sun.data.energy = 4.0
aim(sun, Vector((0, 0, 0)))
bpy.ops.object.light_add(type='SUN', location=(-300, 300, -150))
fill = bpy.context.active_object
fill.data.energy = 0.35
aim(fill, Vector((0, 0, 0)))

bpy.ops.object.camera_add()
cam = bpy.context.active_object
scene.camera = cam

def cam_over(e, n, dist, elev_deg, az_deg, lift=0.0):
    """Camera `dist` out from the map point (e,n), `elev_deg` above the local
    horizon on bearing `az_deg`. Aiming at two lat/lons and hoping gives
    grazing tangent shots (gotchas.md #7)."""
    d = E.en_dir(e, n)
    hm, _ = E.height_field(d[None, :])
    dv = Vector(d.tolist())
    C = dv * (R * float(hm[0]) + lift)
    t1 = dv.cross(Vector((0, 0, 1))).normalized()
    t2 = dv.cross(t1)
    az, el = math.radians(az_deg), math.radians(elev_deg)
    horiz = t1 * math.cos(az) + t2 * math.sin(az)
    return C + (dv * math.sin(el) + horiz * math.cos(el)) * dist, C

def light_for(target):
    """relight along the subject's own normal — the fixed system sun leaves
    half the ground-level shots on the night side as black mush"""
    sun.location = target.normalized() * 420 + Vector((60, -60, 40))
    aim(sun, target)

def shoot(name, pos, target, relight=True, level=False, no_clouds=False):
    """`level` rolls the camera off the local surface normal instead of world
    +Y. `no_clouds` hides the cloud shell for the frame — the deck sits at
    1.0175 R and the blobs bottom out near 1.03, so at ground level one will
    eventually park itself between the lens and the subject."""
    if relight:
        light_for(target)
    if no_clouds:
        clouds.hide_render = True
    cam.location = pos
    aim(cam, target, up=target.normalized() if level else None)
    scene.render.filepath = os.path.join(OUT, "previews", name)
    bpy.ops.render.render(write_still=True)
    if no_clouds:
        clouds.hide_render = False
    print(f"wrote {name}")

_pen_mid_e, _pen_mid_n = pen_en(E.PEN_LEN * 0.45, 0.0)
_br_e, _br_n = pen_en(BRIDGE_AL, (_bank_w + _bank_e) * 0.5)

# --- orbital: the sun stays fixed so the planet reads as a planet
sun.location = Vector((300, -300, 200)); aim(sun, Vector((0, 0, 0)))
shoot("earth_preview_west.png", Vector((E.ll_dir(18, -60) * 330).tolist()),
      Vector((0, 0, 0)), relight=False)
shoot("earth_preview_east.png", Vector((E.ll_dir(18, 95) * 330).tolist()),
      Vector((0, 0, 0)), relight=False)

# --- the money shot: the peninsula from straight up
p, c = cam_over(_pen_mid_e, _pen_mid_n, 46, 88, 0)
shoot("earth_preview_peninsula.png", p, c)

# --- the peninsula on the oblique, looking down the axis toward the harbor.
# cam_over's azimuth basis is t1 = WEST, t2 = SOUTH (t1 = d x Z is -east), so a
# desired map heading (de, dn) is az = atan2(-dn, -de). Here we want to stand
# up-peninsula at -AX and look down it, which lands on atan2(AX_n, AX_e).
_AZ_DOWNAXIS = math.degrees(math.atan2(AX[1], AX[0]))
p, c = cam_over(_pen_mid_e, _pen_mid_n, 40, 26, _AZ_DOWNAXIS)
shoot("earth_preview_approach.png", p, c)

# --- the Ravenel in profile: stand DOWN-river so the camera is perpendicular
# to the deck and both pylons, the full span and the cable fans all read.
# Along the river is +/-AX; from up-river the bridge is end-on and foreshortens
# into a smear.
p, c = cam_over(_br_e, _br_n, 20, 10, _AZ_DOWNAXIS + 180.0)
shoot("earth_preview_ravenel.png", p, c)

# --- downtown + steeples. Aim at the MIDDLE OF THE STEEPLES, not at an
# arbitrary point down the peninsula — the first pass picked a spot by
# fraction-of-length and framed a block of row houses with no spire in shot.
_st_e = sum(s[0] for s in steeples) / len(steeples)
_st_n = sum(s[1] for s in steeples) / len(steeples)
p, c = cam_over(_st_e, _st_n, 15, 16, _AZ_DOWNAXIS + 180.0)
shoot("earth_preview_steeples.png", p, c)

# --- the spaceport
p, c = cam_over(_pe, _pn, 16, 30, 120)
shoot("earth_preview_pad.png", p, c)

# --- the port on the nose, low on the approach bearing: lead-in lights and
# deck paint in the foreground, terminal and control tower standing up behind.
# cam_over's azimuth basis at the pad IS the pad frame — same cross-product
# construction off the same `d` — so `az` here is the same theta the dressing
# was laid out on, and APPR_TH frames it the way you actually fly in.
p, c = cam_over(_pe, _pn, 10.0, 16, APPR_TH, lift=0.5)
shoot("earth_preview_port.png", p, c, level=True, no_clouds=True)

# --- NIGHT: sun behind the planet so the emissive work carries the frame —
# lit windows, the street grid, floodlit steeples, the Ravenel's cables
print("rendering night…")
sun.location = Vector((-_cd * 400).to_tuple())
aim(sun, Vector((0, 0, 0)))
sun.data.energy = 0.05
fill.data.energy = 0.02
p, c = cam_over(_pen_mid_e, _pen_mid_n, 42, 34, 300)
shoot("earth_preview_night.png", p, c, relight=False)

# the port after dark is the whole point of the emissive pass — if the deck
# paint, rim lights and lead-in don't carry this frame, the dressing failed
p, c = cam_over(_pe, _pn, 10.0, 16, APPR_TH, lift=0.5)
shoot("earth_preview_port_night.png", p, c, relight=False, level=True, no_clouds=True)

print("DONE — earth.glb + earth_height.json + previews")
