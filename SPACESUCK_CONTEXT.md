# SpaceSuck — Project Context & Onboarding

> **Purpose of this file:** a complete, self-contained rundown of the SpaceSuck
> project so another Claude agent (e.g. a mobile assistant) can answer questions
> about it without needing to re-scan the folder. Written for Tanner — a
> tinkerer and HVAC service tech who knows a little Python — so it's precise but
> doesn't assume deep game-dev or graphics experience.
>
> Last generated from the repo at **v51** (65 commits). The `README.md` in the
> folder is slightly older (its prose says "v48 / 62 commits"); trust the git
> log and this file for the current count.

---

## 1. What SpaceSuck is

SpaceSuck is a **browser-based space-flight game** — a "procedural space-flight
toy" — that runs entirely in one HTML page. You fly a small fighter around a
miniature solar system, shoot up floating space junk, vacuum up the scrap it
drops with an always-on tractor beam, and bank that scrap for money at a single
spaceport (Charleston, SC, on a landable Earth). Money buys ship upgrades.
Pirates and freight ships share the field, and you can hire a neutral pirate as
a wingman.

The name is a pun with two meanings: the tractor beam literally **sucks** in
scrap (that's the core loop), and it's a wink that space is a hostile place.

The whole thing is deliberately built with **no build step and almost no
external assets**. Every planet texture, the starfield, the engine sound, and
the music are *generated in code when the page loads*. The only pre-made binary
files are a handful of `.glb` 3D models (ships and two hand-sculpted planets)
built in Blender, plus the vendored three.js library.

**Current vision (what it's growing toward):** a small, self-contained
"junker" sandbox — fly, mine junk, dodge/fight pirates, bank scrap, upgrade,
and haul between two hand-built worlds — all scored by generative music that
reacts to danger. The most recent work (v47–v51) added factions (neutral vs.
hostile pirates), a hireable wingman, and freight traffic (NPC cargo haulers
you can raid). The README hints the *next* stage is teaching your wingman to
actually fight.

**It's live on the web:** <https://thumm110.github.io/SpaceSuck/> (GitHub Pages).

---

## 2. Tech stack / engine / languages

| Layer | What it uses |
|---|---|
| **Rendering / game engine** | [three.js](https://threejs.org) **r128**, vendored locally as `three.min.js` (no CDN dependency at runtime, though there's a CDN fallback) |
| **Model loading** | `GLTFLoader.js` (three.js add-on, also vendored) — loads the `.glb` 3D models |
| **Game code** | Plain **JavaScript** (one big classic `<script>`), no framework, no bundler, no npm |
| **Audio** | **Web Audio API**, hand-written — engine hum and sound effects are synthesized live; music is a separate ES module (`sounds/SpaceMusic.js`) |
| **Persistence** | Browser **localStorage** (banked money + purchased upgrades) |
| **3D asset authoring** | **Blender** driven by **Python** scripts (`build_*.py`) — headless, code-generated models |
| **Launcher / tooling** | A **Bash** script (`play.sh`) + Python's built-in `http.server` |
| **Hosting** | **GitHub Pages** (static files, no server-side code) |

Key thing to understand: **there is no back end and no build pipeline.** The
"source" is just files you edit and open in a browser. The only compilation-like
step is running the Blender Python scripts to regenerate the `.glb` models, and
that's optional — the committed `.glb` files already work.

### Languages present, by weight

- **JavaScript** — the whole game (`space-flight.html` is ~4,800 lines, most of it JS).
- **Python** — the Blender asset factories (`build_earth.py`, `build_rubicon.py`, `build_icon.py`, `raider/build_raider.py`). These are the files Tanner will be most comfortable reading.
- **Bash** — `play.sh` launcher.
- **HTML/CSS** — the page shell and HUD styling, inline at the top of `space-flight.html`.

---

## 3. Folder structure (annotated)

Everything lives flat in one folder (`~/Desktop/SpaceSuck` on Tanner's machine),
with one subfolder each for the raider model and for sounds.

```
SpaceSuck/
├── space-flight.html      ← THE GAME. ~4,800 lines. Almost everything is here.
├── index.html             ← 4-line GitHub Pages redirect → space-flight.html
├── play.sh                ← local launcher: starts a server + opens the game
├── README.md              ← the human-facing writeup (rich, slightly stale on version #)
│
├── three.min.js           ← vendored three.js r128 (the 3D engine)
├── GLTFLoader.js          ← vendored three.js model loader
│
│   ── 3D models (Blender output, .glb = binary glTF) ──
├── ussthumm.glb               ← the player's fighter ("USS THUMM"): teal/orange, aqua engines
├── raider.glb             ← enemy/neutral pirate fighter: black dagger, red trim/engines
├── hauler.glb             ← NPC freight ship "SS OVERTIME"
├── hauler_max.glb         ← bigger freight ship "SS DOUBLE OVERTIME" (double loot)
├── earth.glb              ← EARTH, a landable world (built by build_earth.py)
├── rubicon.glb            ← RUBICON, the red desert world (built by build_rubicon.py)
├── icon.png               ← desktop-launcher icon (rendered from ussthumm.glb)
│
│   ── baked terrain data (so landing works without heavy raycasting) ──
├── earth_height.json      ← 512×256 lat/lon height grid for EARTH (base64 uint8)
├── rubicon_height.json    ← same idea for RUBICON
│
│   ── Blender "factory" scripts (Python; edit numbers, re-run, get fresh assets) ──
├── build_earth.py         ← generates earth.glb + earth_height.json + preview PNGs
├── build_rubicon.py       ← generates rubicon.glb + rubicon_height.json + preview PNGs
├── build_icon.py          ← renders icon.png (a hero shot of ussthumm.glb)
│
│   ── preview renders (eyeball the planets without opening Blender) ──
├── earth_preview_*.png    ← city / east / pad / west renders of EARTH
├── rubicon_preview_*.png  ← a / b / close / pole renders of RUBICON
│
├── raider/                ← the enemy ship's source + build
│   ├── build_raider.py    ← Blender script that builds raider.glb
│   ├── raider.blend       ← the Blender project file (unusual — normally not saved)
│   ├── raider.glb         ← the built model (duplicate of the top-level one)
│   ├── build_raider.log   ← build output log
│   └── preview_front.png / preview_rear.png
│
└── sounds/                ← the audio lab
    ├── SpaceMusic.js      ← generative, danger-reactive music (ES module, Web Audio, no files)
    ├── space_music.py     ← offline renderer / sound experiments (Python)
    ├── space-music-demo.html  ← a console to audition the score
    ├── ambient_space.wav  / danger_alert.wav  ← rendered samples (the game itself uses no files)
    └── playstarz_music-space-ambient-435262.mp3  ← a reference/demo track
```

### The one file that matters most: `space-flight.html`

Nearly the entire game is in this single file, organized with big banner
comments. If an agent needs to find something, these numbered sections are the
map (line numbers approximate, from v51):

| Section | What's there |
|---|---|
| `1. CONFIG — YOUR SOLAR SYSTEM` | The `BODIES` array — every planet/star defined as data (radius, orbit, colors, moons, landability). Start here to understand the world. |
| `2. NOISE ENGINE` | Seeded value noise + fractal Brownian motion (fBm) — the math behind procedural planet surfaces. |
| `3. PLANET TEXTURE GENERATORS` | Turns noise into color/bump/roughness maps on the fly. |
| `4. ATMOSPHERE SHADER` | The glowing atmosphere halo around planets. |
| `5. SCENE SETUP` | three.js scene, camera, lights, **twinkling stars**, **distant galaxies**. |
| `6. THE SHIP (primitives)` | Fallback ship welded from basic shapes (used if `ussthumm.glb` can't load). |
| `6b. TERRAIN HEIGHT GRID` | Loads the baked `*_height.json` so the game knows ground height under the ship. |
| `7. BODY BUILDER` | Constructs each planet/star/moon from the config. |
| `8 / 8b. SPACE DUST / ATMOSPHERE WISPS` | Motion cues and atmospheric-entry visuals. |
| `9. ENGINE AUDIO` | Web Audio engine hum that tracks the throttle. |
| `10. SHIP OBJECT + CAMERA RIG` | Real ship (`ussthumm.glb`), cockpit + chase cameras. |
| `10b. BLASTERS` | Twin nose cannons (aqua + orange). |
| `10c. SPACE JUNK` | Shootable asteroids / satellites / debris — the mining targets. |
| `10d. SCRAP + TRACTOR BEAM` | The "suck": scrap drops and the always-on beam that reels it in. |
| `10e. THE BANK` | Charleston payout + localStorage persistence. |
| `10f. THE OUTFITTER` | The upgrade shop (tractor range / hull plating / cargo clamps). |
| `10f. FREIGHT TRAFFIC` (v50) | NPC haulers that work the field and can be raided. |
| `10g. PIRATES` (v40+) | Enemy AI: attack passes, factions (hostile/neutral/ally), the hireable wingman. |
| *(end)* | The game loop (`animate()`), input handling, HUD updates, hash-spawn logic. |

---

## 4. Core gameplay systems / mechanics implemented

**Flight model.** Throttle-based flight with forward/reverse thrust, boost, a
full-stop key, roll, pitch, and yaw. Physics are frame-rate-independent (drag
scales with real time, so it feels the same on fast and slow machines). You
bounce off every solid body. The throttle behaves like **cruise control, not a
gas pedal** — you set a speed and it holds.

**Procedural planets.** Seeded noise + fBm sampled on a sphere drives elevation,
which drives color (ocean → beach → plains → mountains → snow), bump, and
roughness, plus latitude-based ice caps. Each planet has a fixed `seed`, so it
looks the same every load.

**A live solar system.** A star (HELIOS) plus six planets that actually **orbit
the sun** (heliocentric, Kepler-ish — inner planets move faster). Includes a gas
giant with rings and a 1,000-rock belt, orbiting moons, and two hand-built
landable worlds. See the `BODIES` table in §7 below.

**Space junk (the mining targets).** Asteroids, dead satellites (with solar
wings, a dish, a blinking beacon), and loose debris. The field lives in a
**bubble that travels with you** and respawns ahead of your heading — junk
arrives from all directions, and you can neither outrun it nor fully clear it.
Big rocks take several hits and break into chunks; small debris pops in one.
Hit detection uses a **swept (segment) test** because bolts move ~24 units per
frame — a simple point check would tunnel straight through small targets.

**A hull, and a reason to shoot.** Ramming costs hull and pays nothing.
Man-made junk shatters on impact; an asteroid bigger than ~26 units is a solid
wall you bounce off. Damage scales with **closing speed × mass**, so throttle is
the risk dial: idling through the field is nearly free, a full-boost blind run
can kill you in a few minutes. Nothing one-shots a full hull. Land anywhere to
repair. If hull hits zero you're **towed back to Earth** — an involuntary trip
home, not a game-over screen.

**Scrap + tractor beam (the "suck").** Destroyed junk drops glowing gold scrap;
the always-on beam reels in anything within its radius, and the CARGO counter
climbs. Man-made junk is worth more than rock (rock is always worth a little,
never nothing). Scrap barely drifts, so you collect by flying back through the
wreck you made — and boosting outruns your own beam, so hoovering means easing
off. There's **no beam button**; upgrades grow the radius.

**Ramming spills cargo.** Clipping something knocks loose a chunk of your haul
as live scrap. Swing back and you reclaim most of it; boost away and it's gone.
The richer your hold, the more a hit scatters — a constant tension between "one
more pass" and "bank it now." A lethal hit tows you home and the spill stays at
the wreck.

**Pirates — the field shoots back (v40+).** Raiders (`raider.glb`) spawn off the
radar's edge (two if you linger). A falling two-note ping + a red blip warn you;
a red RAIDER chevron on the HUD tracks the nearest. They fly nose-first attack
passes, are turn-rate-limited (you can out-turn and out-run them — running away
always works, it just pays nothing), and break off on a throttled-back "extend"
that's your window. Three hits crack one open for the richest scrap drop in the
game. Earth's sky is a **safe harbor**: within two Earth radii pirates neither
spawn nor hunt.

**Factions + a wingman for hire (v47).** Half the raiders are **neutral**
(amber slow-blink vs. a hostile's fast red strobe) — scavengers minding their
own business. Shoot one and it turns full bandit (piracy still pays, they just
shoot back). Fly close with guns cold and a neutral **hails you by name** (RUST
VULTURE, SCRAPJACK, THE MAGPIE, KESSLER'S GHOST); press **E** to pay 150 from
the bank and hire it as a wingman (vic formation, two max). Current wingmen hold
formation, circle while you're parked, survive tows, and re-join if lost — but
**don't fight yet** (that's flagged as the next stage).

**Freight traffic (v50).** NPC cargo haulers (`hauler.glb` "SS OVERTIME" and the
double-loot `hauler_max.glb` "SS DOUBLE OVERTIME") work the field. Shoot one
down and its whole manifest blows out as scrap — a loot piñata. In v51 the
haulers were scaled up to ~4× the fighter size so they read as trucks.

**The bank + monopoly (v32).** Cargo in your hold is *at risk* (rams spill it, a
lethal hit loses it). Park on the Charleston pad and the hold pays out into the
**BANK** a few units per tick — banked scrap only ever goes up and persists in
the browser across sessions. Only Charleston pays (any landing repairs). A gold
**HOME** marker points back to the bank whenever you have loot aboard.

**The outfitter / upgrade shop (v34).** Docked at Charleston, a shop opens with
three upgrades, bought with **1 / 2 / 3** (or the D-pad on a gamepad):

| Upgrade | Effect | Tiers (values → costs) |
|---|---|---|
| **TRACTOR BEAM** | Beam reach (collect without slowing) | 260/340/430/540/660 → 60/140/320/700 |
| **HULL PLATING** | More margin before a tow | 100/130/165/205/250 → 80/180/400/850 |
| **CARGO CLAMPS** | A ram knocks less loose (lower = better) | 0.35/0.28/0.21/0.14 → 100/240/550 |

Prices roughly double per tier. Upgrades persist alongside the bank.

**Atmospheric entry (v10, v37).** Drop into a world with atmosphere and the sky
bleeds in through a mid-altitude **cloud deck** (ember-orange if you come in
hot), wisps streak past, the camera rumbles — then you punch through into
clearer air near the ground where the haze thins so you can actually land.

**Landing (v13+, v35).** Gravity pulls inside three planet radii; the baked
height grid says exactly where the ground is. Touch down slow to park (LANDED /
PARKED tag), throttle up to leave. Because Earth *orbits and spins*, close in
the ship is carried with the planet's full motion out to two radii so the
landing corridor stands still and "full stop" actually parks you. A gold-teal
**PAD** reticle marks the live Charleston deck with range + closing rate,
turning green / ALIGNED once you're over it.

**Cameras (v5, v18, v44).** Four views cycled with **V** (or gamepad Y):
cockpit → chase → chase-far → cinematic (a GTA-style auto-director). A right-drag
"showcase" orbit swings the camera 360° around the ship; the chase cam eases/lags
so you see the ship bank through turns.

**Audio (v3) + reactive music (v48).** Synthesized engine hum follows the
throttle; an entry rumble rises during atmospheric descent — no sound files. The
score (`sounds/SpaceMusic.js`) is pure Web Audio: an A-minor ambient bed plays
from your first click, and a **danger layer** (tritone drone, 112 BPM heartbeat,
dissonant arpeggio) fades in the moment a *hostile* is on radar, then melts away
when the sky clears. Neutrals and your own wingmen don't trigger it. **M** mutes
music; engine + effects stay up.

**Controls at a glance:**

- **Keyboard/mouse:** click to capture mouse for freelook steering (ESC releases); W thrust, S reverse, X full stop, A/D roll, ←/→ turn, ↑/↓ pitch (flight-stick inverted), Shift boost, Space fire, E hire wingman, V cycle view, M music toggle.
- **Touch:** on-screen thrust/brake/reverse, a big red FIRE button, drag steering.
- **Gamepad (Xbox):** left stick is a real flight stick (roll + pitch at any speed), right stick is head-look (springs back), RT/LT analog thrust/reverse, A fires, B boost, LB/RB nose left/right (rudder), Y cycles views, R3 holds a look-back, D-pad shops at the outfitter. Controller rumbles on entry, touchdown, and close junk kills.

---

## 5. Current state of development

This is an **actively developed personal/hobby project**, versioned as
`vN:` tags in the git commit log. It runs and is playable end-to-end today —
it's live on GitHub Pages.

**Working / shipped:**

- Full flight model, four camera views, keyboard/mouse/touch/gamepad input.
- Live heliocentric solar system with 6 planets, moons, rings, asteroid belt.
- Two hand-built landable worlds (EARTH with Charleston spaceport; RUBICON, red desert).
- Procedural planets, starfield, galaxies, atmosphere, dust, atmospheric entry.
- Shootable space junk with swept-hit detection; hull/damage; repair-on-landing; tow-home on death.
- Scrap + always-on tractor beam; cargo; cargo-spill-on-ram.
- Bank at Charleston with localStorage persistence; the outfitter with 3 upgrade tracks.
- Pirates with attack-pass AI and a HUD threat chevron; safe harbor over Earth.
- Factions (hostile / neutral); hail + hire a neutral as a **wingman** (formation only).
- Freight haulers (two sizes) that can be raided.
- Synthesized engine audio + generative, danger-reactive music.

**In progress / most recent (v47–v51):** factions, the hireable wingman,
freight traffic, and truck-sized haulers. These are the newest and least
"settled" systems.

**Planned / TODO (from the README + code comments):**

- **Teach the wingman to fight.** The README explicitly calls the current v47
  wingman "company, not cavalry … teaching it to fight is the next stage."
- The `raider/build_raider.py` comments note `GunTipL/R` anchor nodes are
  already built into the raider model "if enemies get blasters" — i.e. wiring is
  in place for future combat features.

There is **no formal issue tracker, test suite, or TODO file** in the repo. The
roadmap lives in commit messages and inline comments. The git log is genuinely
the best history — every feature is a `vN:` commit with a descriptive message.

---

## 6. How to run / build / test it locally

### Run it (the easy way)

```bash
./play.sh
```

`play.sh` starts a tiny local web server on `localhost:8123` (only if one isn't
already running) and opens the game in its own clean Chrome window (no address
bar). On Tanner's machine it's wired to a desktop icon
(`~/Desktop/SpaceSuck.desktop`), so a double-click launches it.

You can spawn directly at a world's doorstep by passing its name:

```bash
./play.sh earth      # → space-flight.html#earth
./play.sh rubicon    # → space-flight.html#rubicon
```

### Run it (by hand)

```bash
python3 -m http.server 8123
# then open http://localhost:8123/space-flight.html
```

### ⚠️ The single most important gotcha: it MUST be served over http://

Double-clicking `space-flight.html` opens it as a `file://` page, and browsers
**block `fetch()` on `file://`**. That means the `.glb` models (`ussthumm.glb`,
`earth.glb`, `rubicon.glb`, etc.) and the `*_height.json` grids never load, and
the game silently falls back to a primitive placeholder ship and a procedural
Earth. If the fighter looks like blocky programmer art, **the cause is almost
always that it's running from `file://` instead of a server** — check the URL,
not the model. `play.sh` exists specifically to prevent this.

### Dev / test shortcuts (URL hash flags)

The game reads `location.hash` for developer shortcuts:

| Open URL with… | Effect |
|---|---|
| `#earth` | Spawn on Earth's doorstep |
| `#rubicon` | Spawn on RUBICON's doorstep |
| *(any body name, lowercased)* | Spawn at that body |
| `#reset` | **Wipe saved progress** — zeroes the bank *and* all upgrades in localStorage back to a stock ship |

localStorage keys used: `spacesuck.bank` (banked scrap) and `spacesuck.up`
(upgrade levels, a JSON array).

### Rebuilding the 3D assets (optional — needs Blender)

The `.glb` models are already committed and work as-is. To change a ship or
planet you edit the numbers in the relevant Python script and re-run it
headless:

```bash
blender -b -P build_earth.py      # regenerates earth.glb + earth_height.json + previews
blender -b -P build_rubicon.py    # regenerates rubicon.glb + rubicon_height.json + previews
blender -b -P build_icon.py       # re-renders icon.png (a hero shot of ussthumm.glb)
blender --background --python raider/build_raider.py   # regenerates raider.glb
```

The philosophy (stated in every script's header): **Blender is the art
department, the Python script is the master.** Edit the code, re-run, get fresh
files — the `.blend` files are treated as disposable and generally not saved.
(The raider is the exception: `raider/raider.blend` *is* checked in.)

### "Testing"

There is **no automated test suite.** Testing is manual: run it in a browser and
fly. The Blender scripts emit `*_preview_*.png` renders so you can eyeball
model/planet changes without opening Blender, and `sounds/space-music-demo.html`
is a console to audition the music.

---

## 7. The solar system, as data (`BODIES` config)

Every world is defined declaratively in the `BODIES` array near the top of
`space-flight.html`. This is the fastest way to answer "what's in the system?":

| Name | Type / style | Radius (u) | Notes |
|---|---|---|---|
| **HELIOS** | star | 3300 | The sun at the system center; everything orbits it. |
| **CINDER** | rocky planet | 900 | Small, hot, orange-red haze. Fastest orbit (~17 min lap). |
| **AZURE** | terrestrial | 1425 | Ocean world with clouds + one moon. |
| **KRONOS** | gas giant | 1950 | Rings + a 1,000-rock asteroid belt. Slowest (~52 min lap). |
| **EARTH** | gltf (landable) | 2500 | **The flagship.** Blender-built (`earth.glb`), has the Charleston spaceport/bank, one Luna-scaled moon, gravity, baked height grid. |
| **VERDANT** | terrestrial | 675 | Small green cloud world. |
| **RUBICON** | gltf (landable) | 3200 | **The frontier.** Bigger, redder super-Earth (`rubicon.glb`), rust canyons + dust haze, **three moons**, landable anywhere but **no bank/city**. Orbits dead opposite Earth, forever (same orbital speed) — the longest haul in the system. |

`style: "gltf"` means the planet is a Blender model with a JS procedural
fallback palette (used if the `.glb` fails to load). `style: "rocky" /
"terrestrial" / "gas"` are fully procedural. Each has a fixed `seed` for
repeatability, and an `orbit: {radius, speed, angle, y}` that's advanced every
frame in the game loop.

---

## 8. Notable design decisions, conventions & gotchas for an agent

- **One-file game.** Almost everything is in `space-flight.html`. When looking
  for code, use the numbered banner comments (§3) as a map. `index.html` is just
  a redirect for GitHub Pages.

- **No dependencies, no build step, no back end.** three.js and GLTFLoader are
  vendored locally. There's no npm, webpack, package.json, or server code. "The
  build" only exists for regenerating Blender assets, and even that's optional.

- **Everything is generated in code.** Planet textures, stars, galaxies, engine
  sound, and music are all procedural at load time. The only binary assets are
  the `.glb` models and a couple of reference/demo audio files (the *game* uses
  no audio files — those `.wav`/`.mp3` in `sounds/` are experiments/references).

- **Serve over http:// or the models don't load** (see §6). This is the number
  one source of "why does the ship look wrong" confusion.

- **Cache-busting.** `play.sh` appends `?v=<timestamp>` to the launch URL, and
  the game rides that same query onto every asset fetch (`ASSET_V =
  location.search`). This forces fresh models after a rebuild. On GitHub Pages
  (no query) it behaves normally. The game only reads the `#hash` for spawn
  location, so the `?v=` query is harmless to gameplay.

- **Progress lives in localStorage, not files.** Bank + upgrades persist in the
  browser (`spacesuck.bank`, `spacesuck.up`). To reset, open the game with
  `#reset`. There's no cloud save and no account.

- **Ship naming / friend-vs-foe by design.** The player ship ("USS THUMM") is
  curvy teal/orange with aqua engines; the raider is deliberately its opposite —
  a flat-black forward-swept dagger with blood-red trim and red engines — so you
  can read friend from foe by silhouette and color alone. Faction lights: hostile
  = fast red strobe, neutral = amber slow-blink, ally/wingman flies your wing.

- **The player ship's Blender source is NOT in this repo.** `ussthumm.glb` is
  committed, but its build script lives outside the folder at
  `~/Blender/spaceship/build_ship.py` (referenced in `build_icon.py`). So you can
  regenerate the planets, icon, and raider from this folder, but *not* the player
  ship. The other build scripts follow that same `build_ship.py` pattern.

- **Baked height grids instead of live raycasting.** Landing works by sampling a
  pre-computed `*_height.json` lat/lon grid rather than raycasting the planet's
  ~80k triangles every frame — a deliberate performance choice. The grid is
  produced by the same Blender script that makes the planet, so the model and its
  height data always match.

- **Physics/tuning constants are inline.** Damage = closing speed × mass, the
  ~26u asteroid "wall" threshold, ~24u/frame bolt speed (hence swept hit tests),
  the two-radii "carry with the planet" landing zone, and the two-radii Earth
  safe-harbor are all magic numbers documented in nearby comments. If asked to
  rebalance, search the relevant section comment.

- **Version history is the roadmap.** No issue tracker or TODO file — the git log
  (`git log --oneline`) is the authoritative history and to-do trail. Each
  feature is a `vN:` commit. Repo is at **v51 / 65 commits**; the README prose
  lags slightly (says v48).

- **Scratch-variable reuse hazard (for anyone editing pirate/junk code).**
  Comments in the PIRATES section warn that a lethal ram runs
  `shipBreach → junkRespawn ×44`, which rewrites shared junk scratch vectors
  mid-call — so pirate code uses its own scratch objects, never the `junkTmp*` /
  `scrapTmp*` ones. Worth knowing before touching that area.

---

## Quick-reference cheat sheet

- **What is it?** A one-file, no-build, browser space-flight game: mine junk, suck up scrap, bank it at Charleston, upgrade, dodge/fight pirates, haul between Earth and RUBICON. Live at thumm110.github.io/SpaceSuck.
- **Stack?** three.js r128 (vendored) + plain JS, Web Audio for sound/music, localStorage for saves, Blender+Python for the 3D models, Bash+`python3 -m http.server` to run it. No framework, no npm, no back end.
- **Main file?** `space-flight.html` (~4,800 lines, organized by numbered banner comments).
- **Run it?** `./play.sh` (or `python3 -m http.server 8123` then open `space-flight.html`). **Must be over http://**, not `file://`.
- **Reset progress?** Open with `#reset`. **Spawn at a world?** `#earth` / `#rubicon`.
- **State?** Playable & live; newest work (v47–v51) = factions, hireable wingman, freight traffic. Next planned: make the wingman fight.
- **Gotchas?** file:// breaks model loading; no tests (fly to test); player-ship Blender source lives outside this folder; roadmap is the git log.
```
