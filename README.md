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
| V | Cycle view: cockpit → chase → cinematic |

Touch devices get on-screen thrust/brake/reverse buttons and drag steering.

**Gamepad** (Xbox layout, plug in and press any button): the left stick is
the whole flight control — parked it turns the nose like a turret, at speed
left/right becomes **roll** and you bank-and-pull to turn like an aircraft
(it blends smoothly between the two as you accelerate). The right stick is
head-look: glance around at space and planets while the ship flies on —
release and your view springs back to forward. **RT/LT are analog
thrust/reverse** (half a pull is half
thrust), X full stop, B boost, LB/RB nose left/right, Y cycles the view.
Atmospheric entry
and touchdowns rumble the controller. Button A is reserved for future
weapons.

## What's inside

- **Procedural planets** — seeded value noise + fractal Brownian motion
  sampled on the sphere, driving color, bump, and roughness maps
  (ocean → beach → plains → mountains → snow, with latitude ice caps)
- **A solar system** — star, rocky/terrestrial/gas planets, an orbiting moon,
  rings, and a 700-rock asteroid belt in a single draw call
- **Flight model** — throttle with reverse, boost, frame-rate-independent
  drag, collision bounces off every body
- **Atmospheric entry** — dive below a quarter-radius of any world with an
  atmosphere: the sky bleeds in (ember-orange if you come in hot), cloud
  wisps streak past, the camera rumbles, and the air drags you
- **Synthesized audio** — Web Audio engine hum that follows the throttle,
  plus a rumble that rises during atmospheric entry; no sound files
- **Ship + camera rig** — a Blender-designed fighter (`ship.glb`) with an
  authored idle-float animation, cockpit view, and a chase cam with easing
  lag so you see the ship bank through turns
- **EARTH, a landable Blender-built world** — `build_earth.py` generates
  `earth.glb` (low-poly continents, polar ice, cloud banks, and a landing
  pad + beacon at Charleston, SC) plus `earth_height.json`, a baked height
  grid. Gravity pulls inside three radii and the grid says exactly where
  the terrain is: touch down slow and you park (**LANDED** tag), throttle
  up to leave. Open `space-flight.html#earth` to spawn on the doorstep.
  Edit the script, re-run `blender -b -P build_earth.py`, fresh planet.

## Run it locally

```
python3 -m http.server 8123
```

then open <http://localhost:8123/space-flight.html>. (A bare double-click
still flies, but browsers block `fetch()` on `file://`, so the Blender
ship and Earth fall back to their procedural placeholders.)

## History

Built in six versions, each one a commit — `git log` tells the story from
"camera with a throttle" to "ship with a flight model".
