"""
earthlib.py — the bpy-free half of build_earth.py
=================================================
Everything here is pure numpy: the config, the noise, `height_field()` (the
single source of truth for ground height) and the color pass. NO Blender.

Why it's a separate file: EARTH's terrain now has a *shape* worth iterating on
(the Charleston peninsula), and a full Blender build is 12-15 minutes. Splitting
the math out means `preview_charleston.py` can render an ASCII map of the exact
same height field in about a second. Same function, same numbers, no drift —
that's the whole point. If you change terrain, change it HERE.

    build_earth.py       — imports this, builds meshes, exports, renders
    preview_charleston.py — imports this, prints an ASCII map (fast loop)
"""

import math
import numpy as np

# ---------------------------------------------------------------- CONFIG --
R          = 100.0      # base (sea-level) radius in Blender units
SUBDIV     = 7          # icosphere subdivisions: 7 → 20·4⁶ = 81,920 triangles
                        #   (~1.9 BU facets), NOT the 327,680 an older comment
                        #   here claimed — that figure is subdiv 8.
                        #   At Earth's 2500u game radius that's ~24u facets —
                        #   chunky-stylized up close; flattened zones (city,
                        #   pad) stay smooth. Local hi-res patches are the
                        #   upgrade path, NOT subdiv 8 (4× the 12MB GLB).
SEED       = 71

# landing pad — Charleston, SC. lat north+, lon east+ (west is negative)
# ** DO NOT MOVE ** the game hardcodes this pad in BODIES:
#     pads: [{ lat: 32.9, lon: -80.0, ang: 0.026, top: 1.0175, home: true }]
# It is the ONLY pad in the game with home:true. Moving it here without the
# matching game-side edit puts the home port in the middle of the Cooper River.
PAD_LAT, PAD_LON = 32.9, -80.0
PAD_H      = 1.012      # pad plateau height (surface multiplier)
PAD_ANG    = 0.035      # pad flatten radius, radians of arc
PAD_BLEND  = 1.7        # apron falloff, ×PAD_ANG. WAS 2.6 — tightened so the
                        # apron ramp can't reach the rivers and lift them out
                        # of the water hazard. Reach is now 5.95 BU; the pad
                        # sits ~6.6 BU from each bank on the neck.

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
    (57, -102, 0.34, 1.00), (41, -98, 0.32, 0.92), (65, -152, 0.20, 0.80),
    (23, -102, 0.17, 0.75),
    # THE SOUTHEAST. Widened 0.17 → 0.30 and pulled down to sit under
    # Charleston. The metro plateau sits at 1.010, which is ABOVE sea level, so
    # a city on thin continent doesn't sit on the coast — it MANUFACTURES a
    # circular island with a sand-beach halo, and from orbit that read as a
    # grey disc swallowing North America. The landmass has to be genuinely
    # there; the plateau only flattens it.
    (31, -80, 0.30, 1.00),
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
    "dry":     0xb0a05c, "boreal":  0x2f5136,   # subtropical steppe + boreal forest
    "snow":    0xf2f7fa, "ice":     0xe8f2f7,
    "pad":     0x3a4148, "beacon":  0xffb066, "cloud": 0xffffff,
    "asphalt": 0x24282e,
    "towerA":  0x6b7280, "towerB": 0x4b5563, "towerC": 0x94a3b8,
    "towerLit": 0x3a3f4a, "window": 0xffcf8a,
    "unit":    0x9aa0a8, "beaconRed": 0xff3b30,   # rooftop mech units + warning lights
    "street":  0x5a6270, "streetGlow": 0xffc27a,  # concrete road grid + warm streetlight glow
    # --- Charleston (new) ---
    "marsh":   0x7d8a4e,   # spartina flats along the riverbanks — Lowcountry gold-green
    "river":   0x2b6a86,   # the Ashley + Cooper: shallower/siltier than open ocean
    # The peninsula's GROUND — warm dark, not pastel. First pass used the
    # stucco colour here as well as on the buildings; under a sunlit render the
    # whole district clipped to one white blob and every row house vanished
    # into it. The ground is the dark value; the BUILDINGS carry the pastel.
    "historic": 0x6e6355,
    "steeple": 0xf4efe6,   # steeple white
    "steepleGlow": 0xfff4d8,  # floodlit at night — the Holy City read
    "bridge":  0xdfe4ea,   # Ravenel deck + pylon concrete
    "cable":   0xb9c3cf,   # stay cables
}

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

def snoise(p, octaves, seed):
    """fbm remapped to roughly [-1, 1]. USE THIS when the amplitude is meant to
    mean something — plain fbm clusters around 0.5 with a spread of only ±0.12,
    so `(fbm-0.5)*A` actually swings about A/8. (gotchas.md #1)"""
    return np.clip((fbm(p, octaves, seed) - 0.5) * 4.0, -1.0, 1.0)

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

# =========================================================== CHARLESTON ====
# Charleston is modelled on the real city: a wedge of land between two rivers,
# pinching to a point at the Battery, with a harbor opening southeast.
#
# THE LAYOUT IS AUTHORED IN A FLAT MAP PLANE, not in lat/lon. `map_en()`
# projects a sphere direction into (east, north) Blender units centred on the
# city; `en_dir()` is its exact inverse. Everything below — rivers, harbor,
# bridge, steeples, street grid — is placed in that (e, n) plane, which is what
# lets the geography read like a map instead of a spreadsheet of coordinates.
#
# SCALE IS DELIBERATELY CARICATURED. The metro is 0.18 rad ≈ 900 game units
# across; real Charleston would be a speck. Landmarks are sized to be *legible
# from a cockpit*, not to scale against each other — the Ravenel's pylons are
# roughly 2× their true proportion because a true-scale bridge is 4 game units
# tall and reads as nothing.

CITY_LAT, CITY_LON = 25.98, -76.45   # solved so the fixed home pad lands on
                                     # the neck — see PAD_MAP assertion below
CITY_ANG   = 0.18       # metro radius in radians of arc (was 0.10 as a disc
                        # city; the peninsula + both rivers + the harbor need
                        # the room, and the hi-res patch rides inside it)
CITY_H     = 1.010      # metro plateau height (surface multiplier)
SEA        = 1.000      # rivers + harbor carve to EXACTLY this. The game's
                        # hazard is `below: 1.0015`, so every carved waterway
                        # is lethal water — same rule as the open ocean.

CITY_DIR = ll_dir(CITY_LAT, CITY_LON)
_clo     = math.radians(CITY_LON)
EAST_T   = np.array([-math.sin(_clo), math.cos(_clo), 0.0])   # unit east
NORTH_T  = np.cross(CITY_DIR, EAST_T)                         # up × east = north

def map_en(dirs):
    """(N,3) unit dirs → (e, n) map coords in Blender units + a validity mask.

    Gnomonic (tangent-plane) projection, so it is the EXACT inverse of
    en_dir(). That matters: a tower placed at (e, n) reads back the same (e, n)
    here, which is the only reason the water-rejection test can be trusted.
    An orthographic projection would disagree by ~1.3% at the metro rim — a
    fifth of a river width, i.e. buildings standing in the Cooper."""
    k    = dirs @ CITY_DIR
    safe = k > 0.5                     # far side of the planet → meaningless
    kk   = np.where(safe, k, 1.0)      # and would divide toward infinity
    return R * (dirs @ EAST_T) / kk, R * (dirs @ NORTH_T) / kk, safe

def en_dir(e, n):
    """(e, n) map BU → unit direction. Exact inverse of map_en(). Scalars or
    arrays."""
    e = np.asarray(e, dtype=float)
    n = np.asarray(n, dtype=float)
    v = CITY_DIR * R + EAST_T * e[..., None] + NORTH_T * n[..., None]
    return v / np.linalg.norm(v, axis=-1, keepdims=True)

# --- the peninsula frame -------------------------------------------------
# Real Charleston runs roughly SSE, tapering to the Battery. `al` is distance
# down that axis from the base of the peninsula, `pp` is distance across it
# (positive = the Cooper / Mount Pleasant side, east).
PEN_HEADING  = 160.0                 # degrees clockwise from north
_ph          = math.radians(PEN_HEADING)
PEN_AXIS     = np.array([math.sin(_ph),  math.cos(_ph)])   # down-peninsula
PEN_PERP     = np.array([-PEN_AXIS[1], PEN_AXIS[0]])       # +east, the Cooper
PEN_BASE     = np.array([-3.0, 5.5])  # where the neck becomes the peninsula
PEN_LEN      = 22.0                   # base → the Battery, BU
PEN_HW0      = 4.2                    # half-width at the base
PEN_HW1      = 0.35                   # half-width at the tip (a point)
NECK_LEN     = 14.0                   # how far the neck runs NW before the
                                      # rivers give out into creeks
NECK_FLARE   = 0.35                   # how fast the neck widens going NW
RIVER_W      = 3.0                    # the ASHLEY's width (≈75 game units —
                                      # seven ship-widths, properly flyable)
COOPER_MULT  = 1.55                   # the Cooper is the wide one (see below)
HARBOR_FLARE = 0.28                   # how fast the bay opens past the Battery
BANK         = 0.45                   # bank softness, BU
MARSH_W      = 1.2                    # spartina flats inland of the waterline
# These seven numbers are a BALANCE, not independent knobs. First pass had the
# peninsula at 15x2.8 with a 0.55 harbor flare, and the bay came out 44 BU wide
# — the hero feature was a gulf, with Charleston a thread down one side. The
# peninsula has to be the biggest thing on the map or none of it reads.
CARVE_ANG    = 0.42                   # hard window on the whole carve, radians.
                                      # Without this the harbor wedge keeps
                                      # widening and gouges half the Atlantic
                                      # seaboard.

def charleston(dirs):
    """The map, evaluated on sphere directions. Returns a dict of full-length
    arrays. `wet` is 0 (dry) → 1 (open water) and is used by BOTH the height
    carve and the color pass, so what looks like water IS water."""
    e, n, safe = map_en(dirs)
    de, dn = e - PEN_BASE[0], n - PEN_BASE[1]
    al = de * PEN_AXIS[0] + dn * PEN_AXIS[1]     # along-peninsula
    pp = de * PEN_PERP[0] + dn * PEN_PERP[1]     # across (+ = east / Cooper)
    ap = np.abs(pp)

    # land half-width: fat at the base, a point at the Battery, flaring back
    # out to the northwest into the neck toward North Charleston
    t  = np.clip(al / PEN_LEN, 0.0, 1.0)
    hw = PEN_HW1 + (PEN_HW0 - PEN_HW1) * (1.0 - t) ** 0.8
    hw = hw + np.maximum(-al, 0.0) * NECK_FLARE

    # wiggle both banks so the peninsula isn't a drafting-triangle wedge.
    # ~4.5 BU wavelength → three or four broad lobes down its length, which is
    # what real tidal geography does. Higher frequency turns it into a
    # snowflake (gotchas.md #2); snoise (not fbm) so the amplitude is real.
    zc  = np.full_like(e, 3.7)
    hw  = hw + snoise(np.stack([e * 0.22, n * 0.22, zc], -1), 3, SEED + 51) * 0.80
    hw  = np.maximum(hw, 0.15)

    # the rivers narrow upstream into creeks instead of running at full width
    # forever off the top of the map
    rw = RIVER_W * (1.0 - 0.45 * np.clip(-al / NECK_LEN, 0.0, 1.0))
    # The COOPER (east, pp>0) is the wide one — true of the real river, and the
    # reason the Ravenel has something worth spanning. A symmetric pair gave
    # the bridge a 3.3 BU crossing, which put its two pylons 1.5 BU apart and
    # 5.2 BU tall: a gantry crane, not a bridge.
    rw = rw * np.where(pp > 0.0, COOPER_MULT, 1.0)
    outer = hw + rw + snoise(np.stack([e * 0.20 + 9.1, n * 0.20, zc - 6.0], -1),
                             3, SEED + 52) * 0.45

    # Work in SIGNED DISTANCE to the waterline (+ = wet, − = dry, in BU) rather
    # than a wetness blob. One field then gives us three things that can never
    # disagree: the height carve, the water color, and the marsh band inland of
    # the bank.
    #
    #   ASHLEY (pp<0) + COOPER (pp>0): the band between the peninsula bank and
    #   the far bank — so sd is "how far inside the river am I".
    sd_r = np.minimum(ap - hw, outer - ap)
    #   THE HARBOR: past the Battery the two rivers merge and open southeast.
    # average the two river widths so the harbor joins both banks continuously
    hb   = (PEN_HW1 + RIVER_W * (1.0 + COOPER_MULT) * 0.5) \
        + np.maximum(al - PEN_LEN, 0.0) * HARBOR_FLARE
    sd_h = hb - ap
    # switch at the Battery. The two formulas agree there by construction
    # (hb at al=PEN_LEN == PEN_HW1 + RIVER_W == outer at t=1, modulo wiggle),
    # so the join is continuous and the tip ends in open water.
    sd = np.where(al > PEN_LEN - BANK * 0.5, sd_h, sd_r)
    # upstream the rivers give out into creeks and then nothing
    sd = sd - (1.0 - smoothstep(-NECK_LEN - 3.0, -NECK_LEN, al)) * 6.0

    wet = smoothstep(0.0, BANK, sd)

    # window the whole carve, then kill it on the planet's far side
    ang  = np.arccos(np.clip(dirs @ CITY_DIR, -1.0, 1.0))
    win  = (1.0 - smoothstep(CARVE_ANG * 0.86, CARVE_ANG, ang)) * safe
    wet *= win

    # the historic peninsula: dry land between the two rivers, south of the
    # neck. This is what stays LOW — no towers; steeples are the tall points.
    on_pen = ((ap < hw) & (al > -1.0) & (al < PEN_LEN) & safe).astype(float)

    # spartina flats: LAND within MARSH_W of the waterline. The most Lowcountry
    # thing visible from altitude, and it costs one smoothstep.
    marsh = (1.0 - wet) * smoothstep(-MARSH_W, -0.05, sd) * win
    # ...but NOT along the downtown peninsula: that side is seawall and built
    # right to the water (the Battery, East Bay). Without this the marsh band
    # eats 2.4 BU off each flank and the historic district is a thread.
    marsh *= 1.0 - 0.92 * on_pen * smoothstep(-1.0, 3.0, al)

    return {"e": e, "n": n, "safe": safe, "al": al, "pp": pp, "sd": sd,
            "hw": hw, "outer": outer, "wet": wet, "marsh": marsh,
            "on_pen": on_pen, "ang": ang}

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

    # ORDER MATTERS HERE (gotchas.md #8) and it is not the obvious one:
    #   1. metro plateau   — flatten the whole Charleston footprint
    #   2. carve the water — grooves LAST so nothing above refills them
    #   3. the pad         — a settlement pan always wins
    # Carving before the plateau would just have the plateau fill the rivers
    # back in; flattening the pad before the carve would let the river cut
    # through the home port.

    ch = charleston(dirs)

    # 1. the metro plateau
    t = 1.0 - smoothstep(CITY_ANG, CITY_ANG * 1.9, ch["ang"])
    m = m * (1.0 - t) + CITY_H * t

    # 2. the Ashley, the Cooper, and the harbor. Lerping toward SEA can only
    #    ever LOWER the surface (SEA is the floor), so this is safe to run over
    #    open ocean — out there it's a no-op and the harbor mouth joins the
    #    Atlantic with no seam.
    m = m * (1.0 - ch["wet"]) + SEA * ch["wet"]

    # 3. the landing pad plateau
    ang_pad = np.arccos(np.clip(dirs @ PAD_DIR, -1.0, 1.0))
    t = 1.0 - smoothstep(PAD_ANG, PAD_ANG * PAD_BLEND, ang_pad)
    m = m * (1.0 - t) + PAD_H * t

    return m, {"mask": mask, "land": land, "elev": m - 1.0, "ice": ice, "z": z,
               "ch": ch, "pad_ang": ang_pad}

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
    n_forest = fbm(dirs * 4.5 + 11.1, 4, SEED + 21)    # forest patchiness

    # start as ocean: shallow teal near the coast, navy in the deeps
    depth = smoothstep(0.50, 0.28, mask)
    col = lerp_col(hex_rgb(PAL["shallow"]), hex_rgb(PAL["deep"]), depth)

    is_land = elev > 0.0065

    beach = is_land & (elev < 0.011) & (mask < 0.58)
    col[beach] = hex_rgb(PAL["sand"])

    # local texture: patchy grass↔forest, as before
    green_t = smoothstep(0.35, 0.75, n_forest)
    greens = lerp_col(hex_rgb(PAL["grass"]), hex_rgb(PAL["forest"]), green_t)
    # latitude biomes: a dry steppe band across the subtropics (rises then
    # falls again by ~temperate), then dark boreal forest toward the poles —
    # before the elevation rock/snow below takes over
    az = np.abs(z)
    greens = tint(greens, hex_rgb(PAL["dry"]),
                  smoothstep(0.24, 0.36, az) * (1.0 - smoothstep(0.46, 0.58, az)))
    greens = tint(greens, hex_rgb(PAL["boreal"]), smoothstep(0.60, 0.78, az))
    plains = is_land & ~beach
    col[plains] = greens[plains]

    rocky = is_land & (elev > 0.031)
    col[rocky] = hex_rgb(PAL["rock"])

    snow = (is_land & (elev > 0.052)) | (is_land & (np.abs(z) > 0.88))
    col[snow] = hex_rgb(PAL["snow"])

    icy = ice > 0.25
    col[icy] = hex_rgb(PAL["ice"])

    # ------------------------------------------------------- CHARLESTON --
    # Painted from the SAME fields the height carve used, so the waterline you
    # see is the waterline you drown in. Order: ground first, then marsh, then
    # water on top.
    ch = aux["ch"]
    # Fade the built-up color from downtown out to the rim rather than cutting
    # it at the plateau edge — a hard-edged asphalt disc reads as a coaster
    # dropped on the continent when you see it from orbit. The PLATEAU still
    # runs to CITY_ANG (landing needs it flat); only the paint tapers.
    metro = 1.0 - smoothstep(CITY_ANG * 0.55, CITY_ANG * 1.15, ch["ang"])

    # dry ground inside the metro: pale stucco on the historic peninsula, dark
    # asphalt in the modern districts across the rivers. That contrast is what
    # makes the peninsula read as its own place from orbit.
    ground = lerp_col(hex_rgb(PAL["asphalt"]), hex_rgb(PAL["historic"]),
                      ch["on_pen"])
    # the peninsula is always the historic district, however far it reaches
    # past the fading metro paint — it's a place, not a radius
    built = np.maximum(metro, ch["on_pen"])
    g = (built * (1.0 - ch["wet"]))[:, None]
    col = col * (1.0 - g) + ground * g

    # spartina flats along every bank — not clipped to the metro, so the marsh
    # keeps running down the harbor and out past the city edge
    col = tint(col, hex_rgb(PAL["marsh"]), ch["marsh"] * 0.85)

    # the Ashley, the Cooper and the harbor. Siltier than open ocean.
    col = tint(col, hex_rgb(PAL["river"]), ch["wet"])

    # pad plateau gets its own concrete color
    col[aux["pad_ang"] < PAD_ANG * 1.4] = hex_rgb(PAL["pad"]) * 1.6

    # Per-face brightness jitter — the thing that makes low-poly look rich.
    # Keyed to DIRECTION, not face index (gotchas.md #4). Index-keyed jitter
    # gives the hi-res Charleston patch a visibly different grain from the base
    # sphere, which outlines it as a faint disc in the middle of the Atlantic.
    col *= (1.0 + snoise(dirs * 150.0 + 31.0, 1, SEED + 5)[:, None] * 0.05)
    col = np.clip(col, 0.0, 1.0)

    return np.concatenate([col, np.ones((len(dirs), 1))], axis=1)
