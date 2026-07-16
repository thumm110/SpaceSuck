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
Atmospheric entry
and touchdowns rumble the controller, as do junk kills close aboard.

## What's inside

- **Procedural planets** — seeded value noise + fractal Brownian motion
  sampled on the sphere, driving color, bump, and roughness maps
  (ocean → beach → plains → mountains → snow, with latitude ice caps)
- **A solar system** — star, rocky/terrestrial/gas planets, an orbiting moon,
  rings, and a 700-rock asteroid belt in a single draw call
- **Shootable space junk** — asteroids, dead satellites (solar wings, dish,
  a beacon still blinking), and loose debris tangled out of pipes, plates,
  and tanks. The field lives in a bubble that travels with you and respawns
  ahead of your heading, so junk arrives from every direction and you can
  neither outrun it nor strip it bare. Big rocks take a few hits and break
  into chunks; small debris pops on one. Ram it and it shatters on your hull
  and costs you speed. Hits use a swept test — bolts move ~24 units a frame,
  so a plain point check would sail straight through the small stuff
- **Flight model** — throttle with reverse, boost, frame-rate-independent
  drag, collision bounces off every body
- **Atmospheric entry** — dive below a quarter-radius of any world with an
  atmosphere: the sky bleeds in (ember-orange if you come in hot), cloud
  wisps streak past, the camera rumbles, and the air drags you
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

Twenty-six versions across 37 commits, each `vN:` tagged in the log — `git log`
tells the story from "v1: first flight — mouse steer, throttle physics" to a
Blender fighter shooting up a junk field over a hand-built Earth.
