# SpaceSuck — Project Context & Onboarding

> **Purpose of this file:** a complete, self-contained rundown of the SpaceSuck
> project so another Claude agent (e.g. a mobile assistant) can answer questions
> about it without needing to re-scan the folder. Written for Tanner — a
> tinkerer and HVAC service tech who knows a little Python — so it's precise but
> doesn't assume deep game-dev or graphics experience.
>
> **Regenerated 2026-07-25 at v72 (120 commits).** The previous copy was
> generated at v51 and had gone badly stale — it still described a flat folder
> layout that a reorg (`19ea07b`) replaced, and "two hand-sculpted planets" when
> there are now five. If this file and the code ever disagree, **the code wins**;
> re-verify before repeating anything here.

---

## 1. What SpaceSuck is

SpaceSuck is a **browser-based space-flight game** that runs from one HTML page.
You fly a small fighter around a miniature solar system, shoot up floating space
junk, vacuum up the scrap it drops with an always-on tractor beam, and bank that
scrap for money at Charleston, SC — a real spaceport on a landable Earth. Money
buys ship upgrades. Pirates, capital warships and freight traffic share the
field, and you can hire a neutral pirate as a wingman.

The name is a pun with two meanings: the tractor beam literally **sucks** in
scrap (that's the core loop), and it's a wink that space is a hostile place.

**It's live:** <https://thumm110.github.io/SpaceSuck/> (GitHub Pages).

**Current shape of the thing (v70–v72, the least settled work):** NPC collision
moved from spheres to hull capsules, the player's hull radius is measured off its
model rather than assumed, the chase camera frames each ship by its silhouette,
the crosshair rides the actual gun line, and engine bloom colour + burner count
are read out of each `.glb` instead of hand-configured. Before that, v57–v69
added capital warships, dispatch contracts, three more landable worlds, surface
hazards, a landing assist, and a fourth freight hull.

---

## 2. Tech stack

| Layer | What it uses |
|---|---|
| **Rendering** | [three.js](https://threejs.org) **r128**, vendored at `lib/three.min.js` |
| **Model loading** | `lib/GLTFLoader.js` — loads the `.glb` models |
| **Hull shading** | `lib/hull-plating.js` — procedural plating/weathering in the fragment shader, shared with the fleet page |
| **Game code** | Plain **JavaScript**, one big classic `<script>` in `space-flight.html` |
| **Audio** | **Web Audio API**, hand-written. Engine hum + effects synthesized live; the score is an ES module, `sounds/SpaceMusic.js` |
| **Persistence** | Browser **localStorage** |
| **3D assets** | **Blender** driven by **Python** (`build/build_*.py`), headless |
| **Launcher** | `play.sh` + Python's `http.server` |
| **Hosting** | GitHub Pages (static, no back end) |

**There is no back end and no build pipeline.** The only compile-like step is
running the Blender scripts to regenerate `.glb` assets, and that's optional —
the committed assets work as-is.

### Languages by weight

- **JavaScript** — the game. `space-flight.html` is **8,001 lines**, mostly JS.
- **Python** — the Blender asset factories in `build/`. The files Tanner reads most.
- **Bash** — `play.sh`.
- **HTML/CSS** — page shell + HUD, inline at the top of `space-flight.html`.

---

## 3. Folder structure

The repo was reorganised out of a flat layout in commit `19ea07b`. Assets live in
folders now, and **the game loads via folder-prefixed paths** — moving a file
without editing its path fails *silently* (you get the procedural fallback, not an
error).

```
SpaceSuck/
├── space-flight.html      ← THE GAME. 8,001 lines. Almost everything is here.
├── fleet-registry.html    ← a browsable ship registry page (also opened in-game)
├── index.html             ← GitHub Pages redirect → space-flight.html
├── play.sh                ← local launcher: starts a server + opens the game
├── README.md              ← the human-facing writeup
├── icon.png               ← desktop-launcher icon
│
├── lib/                   ← three.min.js · GLTFLoader.js · hull-plating.js
│
├── ship/                  ← the four PLAYABLE hulls
│   uss-thumm.glb · uss-boo.glb · uss-char.glb · uss-samsam.glb
│
├── enemies/               ← raider.glb · ss-timeclock.glb · ss-shrinkage.glb
│
├── npc/                   ← ss-overtime.glb · ss-double-overtime.glb
│                            canary-freight.glb · ss-packrat.glb
│
├── planets/               ← ~118 MB: the five Blender worlds + their baked data
│   earth.glb + earth_height.json          (2048×1024 grid)
│   rubicon.glb + rubicon_height.json
│   cinder.glb + cinder_height.json + cinder_hazard.json   (graded magma mask)
│   azure.glb + azure_height.json
│   verdant.glb + verdant_height.json + verdant_trees.json (588 tree colliders)
│   previews/                              ← eyeball renders per world
│
├── build/                 ← the Blender factories (Python)
│   build_earth.py + earthlib.py (the pure-numpy terrain half)
│   build_rubicon.py · build_cinder.py · build_azure.py · build_verdant.py
│   build_icon.py
│
└── sounds/                ← SpaceMusic.js (the live score) + space-music-demo.html
                             (a console to audition it) + space_music.py
```

**Ship and planet *masters* live outside this repo** at
`~/Blender/spacesuck/{ships,planets}/`. The repo holds copies. `build/` now has a
script for every committed planet; the ship build scripts are master-side only.

### The one file that matters most

`space-flight.html`, organised with numbered banner comments. Current offsets:

| Line | Section | What's there |
|---|---|---|
| 656 | `1. CONFIG` | The `BODIES` array — every world as data. **Start here.** |
| 965 | `2. NOISE ENGINE` | Seeded value noise + fBm |
| 1014 | `3. PLANET TEXTURES` | Procedural colour/bump/roughness (fallback path now) |
| 1185 | `4. ATMOSPHERE SHADER` | The glowing halo |
| 1224 | `5. SCENE SETUP` | Scene, camera, lights, stars, galaxies |
| 1502 | `6. THE SHIP (primitives)` | Fallback hull if a `.glb` can't load |
| 1607 | `6b. TERRAIN HEIGHT GRID` | Loads the baked grids; tree colliders |
| 1866 | `7. BODY BUILDER` | Builds each world from config |
| 2071 | `8 / 8b. DUST + WISPS` | Motion cues, atmospheric entry |
| 2104 | `9. ENGINE AUDIO` | Throttle-tracking hum |
| 2196 | `10. SHIP OBJECT + CAMERA RIG` | `SHIPS[]` hangar, four camera views |
| 2410 | `10b. BLASTERS` | Bolts, muzzles, the gun line |
| 2516 | `10c. SPACE JUNK` | The mining targets |
| 3014 | `10d. SCRAP + TRACTOR BEAM` | The "suck" |
| 3222 | `10e. THE BANK` | Payout + persistence |
| 3330 | `10f. THE OUTFITTER` | The upgrade shop |
| 3599 | `10g. PIRATES` | Raider AI, factions, the wingman |
| 3851 | `10f: FREIGHT TRAFFIC` | Four haulers incl. the salvaging PACKRAT |
| 4494 | `10i: GUNSHIPS` | Capital warships (TIMECLOCK escorts, SHRINKAGE) |
| 5874 | `10h. DISPATCH CONTRACTS` | The job board |
| 5978 | `11. INPUT` | Keyboard/mouse/touch |
| 6113 | `11c. GAMEPAD` | Xbox mapping |
| 6148 | `12. GAME LOOP` | `animate()`, HUD, camera rig |

*(Note the numbering is historical, not sorted — `10i` sits before `10h` in the
file. Search the banner text, not the number.)*

---

## 4. Core systems

**Flight model.** Throttle behaves like **cruise control, not a gas pedal**.
Forward/reverse thrust, boost, full stop, roll, pitch, yaw, plus *grip* (v38)
which rotates your travel direction toward the nose so the ship curves instead of
crabbing. Frame-rate independent. You bounce off every solid body.

**Four playable hulls**, picked on the start screen (`SHIPS[]`, ~line 2236). Each
is a real tradeoff, not a tier: **USS THUMM** (quickest turn), **USS BOO**
(quad-engine heavy; rebuilt as a v2 lofted hull 2026-07-25), **USS CHAR** (fastest
thrust, stubbiest tractor), **USS SAMSAM** (toughest hull, worst reach).

**Five landable worlds + a gas giant.** See §6.

**Space junk.** Asteroids, dead satellites, debris, in a bubble that travels with
you and respawns ahead of your heading. Hit detection is a **swept segment** test
because bolts move fast enough to tunnel a point check.

**Hull and hazards.** Damage scales with closing speed × mass. Landing repairs —
but *where* matters: Earth and AZURE drown you in open water, CINDER's magma kills
by intensity, VERDANT's canopy grinds hull off. Hull zero = towed home, not a
game-over.

**Scrap + tractor beam.** Always-on, no beam button; upgrades grow the radius.
Boosting outruns your own beam. Ramming spills cargo.

**Pirates (v40+), factions (v47), wingmen.** Raiders fly nose-first attack passes.
Half spawn neutral; shoot one and it turns. Fly close with guns cold and a neutral
hails you — **[E]** hires it. Wingmen hold formation but **still don't fight**;
that's the oldest open item on the roadmap.

**Capital warships (v57).** SS TIMECLOCK flies escort on the loot piñata; SS
SHRINKAGE is a rarer roaming mini-boss.

**Freight (v50+).** Four hulls: SS OVERTIME (52u), SS DOUBLE OVERTIME (65u,
escorted), SS CANARY (68u, the container run), SS PACKRAT (22u, a collector that
actually salvages the field).

**Dispatch contracts (v56).** A job board at Charleston, accepted with **4/5/6**.

**Ports (v60).** Port rights are declared per *pad*. Charleston is the only pad
with `home: true` — 1:1 payout, the outfitter, the job board, the safe harbor, the
breach-tow destination. RUBICON's **RustHollow** fences your hold at 0.7.

**Collision shapes (v70–v70.1).** Freight and capitals use **hull capsules** sized
from their models, not `len/2` spheres; the player's radius (`shipHullR`) is
measured off its own hull. Fighters keep spheres deliberately — 12-vs-12 is tuned
parity.

**Camera + crosshair (v71–v71.2).** Per-view FOV (cockpit 70 for awareness, chase
64, chase-far 66, cinematic 56); the chase distance scales with each hull's
silhouette; the crosshair is a dot projected onto the real gun line.

**Engine bloom (v72).** Colour and burner seats are **discovered from the model** —
a material named `EngineGlow` and nodes matching
`/^Thruster(?:[LRC]|C[LR]|W[LR]|[EQ]\d+)$/`.

**Audio + reactive music.** Synthesized engine; the score fades a danger layer in
when a *hostile* is on radar. **M** mutes music only.

### Controls

- **Keyboard/mouse:** click to capture the mouse (freelook), W thrust, S reverse,
  X full stop, A/D roll, ←/→ turn, ↑/↓ pitch (inverted), Shift boost, Space fire,
  **E** hire, **G** landing assist / launch / abort, **V** cycle view, **M** music,
  **H** controls panel, **P** or **ESC** pause + settings, **1/2/3** buy upgrade,
  **4/5/6** accept contract.
- **Touch (v78):** a FLOATING flight stick on the left — a visible ring, but the
  base re-anchors under wherever your thumb lands in the left 42% of the glass,
  so you can't miss it. Right thumb gets FIRE / THRUST / REVERSE / STOP; VIEW is
  a small button top-right. Landing assist is a **pop-up**, not a permanent
  button: it appears only when a deck is on offer (or you're parked) and taps
  through to the same `tryAssist()` as **G**.
- **Gamepad:** left stick flight, right stick head-look, RT/LT thrust, A fire,
  B boost (or landing assist when one is offered), LB/RB rudder, Y views, R3
  look-back, D-pad drives the shop and job board.

---

## 5. How to run it

```bash
./play.sh                 # server on :8123 + a clean Chrome window
./play.sh earth           # spawn at a world — ANY body name works
python3 -m http.server 8123   # or by hand
```

### ⚠️ The single biggest gotcha: it MUST be served over http://

`file://` blocks `fetch()`, so every `.glb` and height grid silently fails and you
get placeholder art. If the ship looks like blocky programmer art, **check the URL,
not the model.**

### Hash flags

`#<bodyname>` spawns at any body (`#earth`, `#cinder`, `#verdant`, …).
`#reset` wipes saved progress.

**localStorage keys:** `spacesuck.bank`, `spacesuck.up`, `spacesuck.ship`,
`spacesuck.name`, `spacesuck.job`, `spacesuck.settings`, `spacesuck.save`.

### Rebuilding assets (optional, needs Blender)

```bash
blender -b -P build/build_earth.py     # and build_rubicon / cinder / azure / verdant
blender -b -P build/build_icon.py
```

Philosophy: **Blender is the art department, the Python script is the master.**
Edit numbers, re-run, get fresh files. `.blend` files are disposable.

### Testing

No test suite lives in the repo. A headless Chrome/puppeteer harness exists as the
**`spacesuck-test` skill** (outside the repo) — a syntax gate plus a regression
smoke test that boots the game and asserts on live globals.

---

## 6. The solar system (`BODIES`)

| Name | Style | Radius | Landable | Notes |
|---|---|---|---|---|
| **HELIOS** | star | 3300 | — | System centre |
| **CINDER** | gltf | 900 | ✅ | Scorched. Graded **magma** hazard mask; two outposts; no pads. The only world with `impacts` (rocks reach the ground) and `vents` (The Maw erupts) |
| **AZURE** | gltf | 1425 | ✅ | Archipelago. **Water kills.** Four island pads incl. FOLLY on pylons; one moon |
| **KRONOS** | gas | 1950 | ❌ | Gas giant, rings, 1,000-rock belt. The only procedural planet left |
| **EARTH** | gltf | 2500 | ✅ | **The flagship.** Charleston spaceport (dressed v72), lethal rivers, one moon |
| **VERDANT** | gltf | 675 | ✅ | Smallest. 95% closed canopy; 588 tree colliders; two Angel Oak platforms |
| **RUBICON** | gltf | 3200 | ✅ | The frontier. RustHollow fence; three moons; orbits opposite Earth forever |

`style: "gltf"` = a Blender mesh with a procedural fallback palette.

---

## 7. Conventions & gotchas for an agent

- **Folder-prefixed paths.** Post-reorg, a wrong path fails *silently* into the
  fallback. Check the console for "didn't load".
- **Serve over http://** (§5).
- **Cache-busting.** `play.sh` appends `?v=<timestamp>`; the game rides that onto
  every asset fetch (`ASSET_V`).
- **Baked height grids, not raycasting.** Landing samples a `*_height.json`
  lat/lon grid produced by the same script that makes the planet, so mesh and
  collision can't disagree.
- **Pad lat/lon in BODIES is a hand-copy** of the build script and goes stale if
  platforms move in Blender. Re-emit from `build_<planet>.py`.
- **Scratch-vector reentrancy.** A lethal ram runs `shipBreach → junkRespawn ×N`
  (N = `JUNK_COUNT`), which rewrites shared junk scratch mid-call. Pirate/freight/
  capital code owns its own `pirTmp*` / `haulTmp*` / `gunTmp*` vectors — never
  `junkTmp*`. v75's `pointInTerrain` / `npcTerrainClamp` own `_solidN` / `_npcN`
  for the same reason: they're called from inside those loops, and so do v76/v77's
  `burnUp` / `burnTan` / `burnTmp`, `impTmpA/B` and `_ventN/_ventP/_ventV/_ventJ`.
- **Worlds are solid, and the test order is load-bearing (v75).** Every bolt pool
  kills on terrain via `pointInTerrain`, but ONLY after its own target sweep —
  `else if`, never before. Ordered the other way, a shot that reached the hull is
  eaten by the rock behind it and flying low makes you bulletproof. Review caught
  exactly that in the first cut; `tests/planet-solidity.js` now guards it.
- **Junk is evicted, not just spawn-checked (v75).** `junkPointBlocked(p, mul, pad)`
  is re-run on every live piece each frame, because a parked ship rides its
  planet's `orbitDelta` (~150–215 u/s) while junk sits still in world space — the
  planet drives through the field. Exits go through `junkLeaveField()`, the hook
  the atmosphere burn-up grew from in v76. Moons are a known gap: they're not in
  `liveBodies`, so bolts still pass through them.
- **A junk slot has THREE states since v76**, not two: alive, dead-and-waiting, and
  dead-but-burning (`j.burn > 0`, `alive === false`, still drawn). A burning rock is
  scenery — not shootable, not rammable, worth no scrap — and it owns its own step,
  so it does *not* tick `respawnIn`. `junkActivate()` clears `j.burn`; that one line
  is what stops `junkSpawnFragments` (which picks slots by `!alive`, and a burning
  rock matches) from resurrecting a meteor with a stale `burnBody`.
- **Counted, never tracked.** `burningNow()` and `ambientEmber()`'s live count both
  walk their arrays instead of keeping a tally, because every `++/--` pair here has
  four or five unwind sites and one miss disables the effect silently, forever. The
  first cut of v76 proved the point: a leftover `burningNow++` overwrote the function
  itself with `NaN`.
- **The ember pool's real limit is CONCURRENCY, not emission rate (v77).** It's a
  260-sprite ring buffer shared with weapons FX. Continuous effects (meteor trails,
  volcanic plumes) go through `ambientEmber()` and share a 70-slot live allowance;
  one-shot events (kills, impacts, flares) call `emitEmber` directly. A per-*frame*
  cap looks tight and isn't — 7/frame is 385 sprites a second, which owned the whole
  pool and left a plume eating its own tail.
- **Anything anchored to a planet must ride `orbitDelta` (v77).** Worlds *travel* —
  CINDER does 216 u/s (`orbit.speed 0.006 × orbit.radius 36000`) — and near a world
  the ship is carried with it, so the ground is stationary on screen while anything
  in raw world space is not. Embers carry an optional `e.carry = body` for this;
  set it on any sprite that claims to stand on terrain. Measured without it: THE
  MAW's plume ended 505u downrange having risen 256, lying ~78° off vertical. Its
  *spin* (22.5 u/s at the surface) is deliberately **not** carried — that's the
  downwind lean. The old one-shot FX never showed the bug because they live 0.2s.
- **Worlds where rocks LAND are a config flag.** `cfg.impacts` (CINDER only) is what
  turns a burn-up into a `surfaceImpact()`. `cfg.vents` is baked lat/lon, spun into
  world space each frame by `fromBakedFrame()` — the exact inverse of `toBakedFrame`,
  and it has to stay that way or the volcano slides across the ground as the world
  turns. Vent coordinates are hand-copied from `build_cinder.py` (same staleness rule
  as pads).
- **Touch layout must be MEASURED at phone sizes, never eyeballed.** The pre-v78
  layout looked fine at 1280×800 and put THRUST 314px up a 390px-tall landscape
  phone with REVERSE drawn through the throttle bar. `tests/mobile-controls.js`
  checks every control's rect against the viewport, the other controls, the flight
  readout, the throttle bar and the radar at three sizes. Invariants: held controls
  live in the bottom ~205px on the right, the left `STICK_ZONE` (42%) is the stick's
  alone, and press-once controls (VIEW, the landing pop-up) leave the thumbs' area.
- **The radar is drawn on a canvas, so no element test can catch it.** Its box has
  to be reconstructed from `drawNavHud`'s own numbers (r=52, cx=W/2,
  cy=H−`navRadarUp`, label +14). That omission is exactly how portrait shipped with
  the scope under REVERSE. `navRadarUp` is 92 on desktop and *lifts* on glass when
  the stick zone and the button cluster leave no room — computed off the live button
  rects and cached on resize, never per frame (4 `getBoundingClientRect` calls
  inside the render loop force a layout flush 60×/sec).
- **`#navhud` MUST carry an explicit CSS `width`/`height`.** A `<canvas>` is a
  *replaced* element: with `width: auto` an absolutely-positioned one resolves to its
  **intrinsic** size — the `width`/`height` **attributes** — and the over-constrained
  `right`/`bottom` from `inset: 0` are dropped. `sizeNavHud()` sets those attributes to
  `innerWidth × dpr`, so without the CSS the canvas laid out at **2× the viewport** on
  any retina screen: every label and reticle drew at twice its offset from the top-left
  and the radar fell off the bottom-right corner. Invisible at dpr 1, which is why it
  shipped. The WebGL canvas never had it — three.js writes an explicit `style.width`.
- **`body.docked` is a MODE, not a panel.** Parked at a real port on glass hides the
  flight HUD and raises a two-column sheet. Gated on `canShop || canJobs`, so landing on
  an empty plain keeps the normal HUD. The columns are flex: a hidden panel isn't a flex
  item, so a port with only one of the two gets a single centred column with no JS branch.
- **The docked-panel media query keyed on the wrong AXIS.** It stacked the board below
  the shop under `max-width: 1024px`, but a landscape phone has 844px of width spare and
  only 390 of **height** — stacking is backwards there. Short → side by side, narrow →
  stacked.
- **`layoutAssistPill()` derives the pop-up's `bottom` from `navRadarUp`.** It used to
  carry its own CSS constant and the two drifted the moment the radar started moving.
  One number, one owner.
- **The stick's THROW is read off the elements** (`base − knob` radius), not
  hardcoded, so the short/narrow-screen media query retunes the feel with no second
  constant to fall out of sync. Its response is *curved* (`STICK_CURVE`): a contained
  knob only travels ~43px and a linear map over that can't hold a small correction.
- **`hitR` is not only a hull radius.** The PACKRAT's salvage gap reads it as a
  half-*length*. v70 added `capR`/`capHalf` beside it rather than redefining it.
- **fleet.json sizes are a FORWARD spec**, not live values — the game runs ~0.44–
  0.52× of them, and adopting them is *blocked* by VERDANT's ~18-unit platforms.
- **Version history is the roadmap.** No issue tracker. `git log --oneline` is the
  authoritative to-do trail; every feature is a `vN:` commit with real prose.
- **Parallel agents.** A Blender "shipyard" agent and other Claude sessions ship
  work into this repo concurrently. **`git log` before assuming the tree is yours.**

### Known open items

- **Teach the wingman to fight** — the oldest one. Allies are formation-only.
- **NPC engine bloom is one averaged sprite per ship**, not one per burner; only
  player hulls light every seat.
- **Small-world atmospheres** got deeper in v71 but the visible sky and the *drag*
  shell are still separate numbers (`atmoAlt` vs `radius × 1.2`).
- **`planets/` is ~118 MB of binary in plain git** — no LFS, so every world rebuild
  commits a whole new blob.

---

## Quick-reference cheat sheet

- **What is it?** A no-build browser space-flight game: mine junk, suck up scrap,
  bank it at Charleston, upgrade, fight pirates and capitals, haul between five
  landable worlds. Live at thumm110.github.io/SpaceSuck.
- **Stack?** three.js r128 (vendored) + plain JS, Web Audio, localStorage,
  Blender+Python for assets. No framework, no npm, no back end.
- **Main file?** `space-flight.html`, 8,001 lines, numbered banner comments.
- **Run it?** `./play.sh`. **Must be http://**, not `file://`.
- **Reset?** `#reset`. **Spawn?** `#<any body name>`.
- **State?** v72 / 120 commits. Newest and least settled: v70–v72 (hull capsules,
  camera/crosshair work, model-driven engine bloom, USS BOO v2).
