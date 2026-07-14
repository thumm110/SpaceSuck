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
| V | Cockpit / chase view |

Touch devices get on-screen thrust/brake/reverse buttons and drag steering.

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

## Run it locally

Clone and open `space-flight.html` in a browser. That's it.

## History

Built in six versions, each one a commit — `git log` tells the story from
"camera with a throttle" to "ship with a flight model".
