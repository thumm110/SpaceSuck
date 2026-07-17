# SpaceSuck — Deep Space Flight

A procedural space-flight toy in **one HTML file**. No build step, no image
assets, no dependencies beyond a vendored copy of three.js — every planet
texture, the ship, the starfield, and the engine audio are generated in code
when the page loads.

**🚀 Fly it now: [thumm110.github.io/SpaceSuck](https://thumm110.github.io/SpaceSuck/)**

## Controls

| Input | Action |
|---|---|
| Click | Capture the mouse (freelook steering) — ESC releases |
| Mouse | Pitch / yaw |
| Right-drag | Orbit the ship 360° (showcase) — wheel zooms |
| W | Thrust |
| S | Reverse thrust |
| X | Full stop |
| A / D | Roll left / right |
| ← / → | Turn left / right |
| ↑ / ↓ | Nose down / up (flight-stick style) |
| Shift | Boost |
| Space | Fire blasters |
| V | Cycle view: cockpit → chase → cinematic |

Touch devices get on-screen thrust/brake/reverse buttons, a big red **FIRE**
button, and drag steering. Hold FIRE with your right thumb while your left
drags to steer — the throttle is cruise control, not a gas pedal, so the
right thumb is free once you're up to speed.

**Gamepad** (Xbox layout, plug in and press any button): the left stick is
a real flight stick — left/right **rolls**, up/down pitches, at any speed;
bank and pull to turn, or use LB/RB as the rudder. The right stick is
head-look: glance around at space and planets while the ship flies on —
release and your view springs back to forward. **RT/LT are analog
thrust/reverse** (half a pull is half
thrust), X full stop, B boost, LB/RB nose left/right, **A fires the
blasters** (twin nose cannons, aqua + orange), Y cycles the view.
Docked at the outfitter, the **D-pad** picks an upgrade and **A** buys it.
Atmospheric entry
and touchdowns rumble the controller, as do junk kills close aboard.

## What's inside

- **Procedural planets** — seeded value noise + fractal Brownian motion
  sampled on the sphere, driving color, bump, and roughness maps
  (ocean → beach → plains → mountains → snow, with latitude ice caps)
- **A solar system** — star, rocky/terrestrial/gas planets, two hand-built
  landable worlds, orbiting moons (Earth's one, RUBICON's three), rings, and a
  700-rock asteroid belt in a single draw call
- **Shootable space junk** — asteroids, dead satellites (solar wings, dish,
  a beacon still blinking), and loose debris tangled out of pipes, plates,
  and tanks. The field lives in a bubble that travels with you and respawns
  ahead of your heading, so junk arrives from every direction and you can
  neither outrun it nor strip it bare. Big rocks take a few hits and break
  into chunks; small debris pops on one. Hits use a swept test — bolts move
  ~24 units a frame, so a plain point check would sail straight through the
  small stuff
- **A hull, and a reason to shoot** — ramming costs you and pays nothing.
  Manmade junk shatters on the hull; an asteroid over 26 units is a wall you
  bounce off. Damage scales with closing speed × mass, so the throttle is the
  risk dial: idling through the field is basically free, and a blind run at
  full boost kills you in a few minutes. Nothing one-shots a full hull. Land
  anywhere to patch up. Hull hits zero and you're towed back to Earth — an
  involuntary trip home, not a game-over screen
- **Scrap + a tractor beam** — shot-down junk drops glowing gold scrap, and
  a beam reels in anything nearby; the CARGO counter climbs as it hits your
  intake. Manmade junk is worth more than rock, and rock is worth a little,
  never nothing. Scrap barely drifts, so you collect by flying through the
  wreck you just made — and a boosting ship outruns its own beam, so hoovering
  means easing off the throttle. No button: the beam is always on, and the
  radius is what grows with upgrades at the outfitter. The game's called
  SpaceSuck; this is the first thing that sucks
- **Ramming spills your hold** — clip something and it doesn't just dent the
  hull, it knocks cargo loose: a chunk of your haul bursts off the ship as
  live scrap. Ease off and swing back and you reclaim most of it; blast on and
  it drifts away for good. The richer your hold, the more a hit scatters — so
  every run is a quiet argument between one more pass and flying home to bank
  it. A lethal hit tows you to Earth and the spill stays at the wreck
- **A bank — and Charleston holds the monopoly** — cargo in the hold is at
  risk: rams spill it, a closed tab loses it. Park on the Charleston pad and
  the hold pays out into the **BANK**, a few units a tick — banked scrap is
  the number that only goes up, and it's kept in the browser across sessions
  (open `space-flight.html#reset` to zero it). Any landing still repairs;
  only the spaceport pays. The moment there's loot aboard, a gold **HOME**
  marker on the HUD edge points back to the bank — and if you set down on
  the wrong continent, the landing tag tells you where the money lives.
  Take off mid-payout and the remainder simply stays in the hold
- **An outfitter — the bank buys something** — dock at Charleston and a
  small shop opens under the teller: **tractor beam** range (reach loot
  without easing off), **hull plating** (more margin before a tow), and
  **cargo clamps** (a ram knocks less of the haul loose). Click a row or
  press **1 / 2 / 3**; prices roughly double per tier, so the first taste
  is one good run and the last tier is a career. Upgrades persist alongside
  the bank — `#reset` wipes it all back to a stock ship
- **Flight model** — throttle with reverse, boost, frame-rate-independent
  drag, collision bounces off every body
- **Atmospheric entry** — drop into any world with an atmosphere and the sky
  bleeds in through a mid-altitude **cloud deck** (ember-orange if you come in
  hot), cloud wisps streak past, the camera rumbles — then you punch through
  into clear air near the ground, where the coloured haze thins out so you can
  actually see to land, while the thick air still drags you down. The
  atmosphere reads as a slightly bigger bubble now, too
- **Synthesized audio** — Web Audio engine hum that follows the throttle,
  plus a rumble that rises during atmospheric entry; no sound files
- **Ship + camera rig** — a Blender-designed fighter (`ship.glb`) with an
  authored idle-float animation, cockpit view, and a chase cam with easing
  lag so you see the ship bank through turns. `build_icon.py` renders that
  same model into `icon.png` for the desktop launcher — same deal as the
  planet: `blender -b -P build_icon.py`, fresh icon.
- **EARTH, a landable Blender-built world** — `build_earth.py` generates
  `earth.glb` (low-poly continents, polar ice, cloud banks, and a landing
  pad + beacon at Charleston, SC) plus `earth_height.json`, a baked height
  grid. Gravity pulls inside three radii and the grid says exactly where
  the terrain is: touch down slow and you park (**LANDED** tag), throttle
  up to leave. Open `space-flight.html#earth` to spawn on the doorstep.
  Edit the script, re-run `blender -b -P build_earth.py`, fresh planet.
- **A landing helper that respects the physics** — Earth orbits the sun at
  ~170 u/s and spins, so "stop" in world coordinates used to let the pad
  slide out from under you. Close in, the ship is now carried with the
  planet's full motion (orbit *and* spin) out to two radii, so the whole
  final-approach corridor stands still and a full-stop actually parks you.
  On approach a gold-teal **PAD** reticle marks the live Charleston deck
  with range and a closing-rate arrow, turning green and reading **ALIGNED**
  once you're over the spaceport — the HOME chevron hands off to it as you
  get close
- **RUBICON, a second world on the far rim** — `build_rubicon.py` bakes a
  bigger, redder cousin of Earth (`rubicon.glb` + `rubicon_height.json`): a
  rust-desert super-Earth (3200u to Earth's 2500) of canyons, dune plateaus,
  and dry basins under a thin polar dust cap, wrapped in an orange dust haze
  and trailing **three moons of three sizes** on tilted orbits. It rides the
  orbit diametrically opposite Earth — straight across the sun, at Earth's
  exact orbital speed so the two stay forever opposed — the longest haul in
  the system. Land anywhere on open desert to patch the hull, but there's no
  bank and no city out here: Charleston keeps its monopoly. Open
  `space-flight.html#rubicon` (or `./play.sh rubicon`) to spawn on its
  doorstep. Same deal as Earth — edit the script, re-run
  `blender -b -P build_rubicon.py`, fresh planet.

## Run it locally

```
./play.sh
```

Starts a server on localhost (only if one isn't already up) and opens the game
in its own window — no address bar, no tabs. `./play.sh earth` spawns you on
Earth's doorstep instead. On this machine it's wired to a desktop icon
(`~/Desktop/SpaceSuck.desktop`), so a double-click flies.

By hand, if you'd rather:

```
python3 -m http.server 8123
```

then open <http://localhost:8123/space-flight.html>.

**Serving it over http isn't optional.** Double-clicking `space-flight.html`
still flies, but browsers block `fetch()` on `file://` — so `ship.glb` and
`earth.glb` never load, and the game quietly falls back to the primitive
placeholder ship and a procedural Earth. If the fighter looks like programmer
art, that's why: check the URL, not the model.

## History

Thirty-seven versions across 51 commits, each `vN:` tagged in the log — `git log`
tells the story from "v1: first flight — mouse steer, throttle physics" to a
Blender fighter mining a junk field for scrap, banking it at Charleston, and
spending it on upgrades — across two hand-built worlds you can land on: Earth,
and the red desert of RUBICON on the far rim.
