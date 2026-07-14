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
| W | Thrust |
| S | Brake to a stop, keep holding to reverse |
| A / D | Turn left / right |
| Q / E | Roll |
| Shift | Boost |
| V | Cockpit / chase view |

Touch devices get on-screen thrust/brake/reverse buttons and drag steering.

## What's inside

- **Procedural planets** — seeded value noise + fractal Brownian motion
  sampled on the sphere, driving color, bump, and roughness maps
  (ocean → beach → plains → mountains → snow, with latitude ice caps)
- **A solar system** — star, rocky/terrestrial/gas planets, an orbiting moon,
  rings, and a 400-rock asteroid belt in a single draw call
- **Flight model** — throttle with reverse, boost, frame-rate-independent
  drag, collision bounces off every body
- **Synthesized audio** — Web Audio engine hum that follows the throttle;
  no sound files
- **Ship + camera rig** — cockpit view and a chase cam with easing lag so
  you see the ship bank through turns

## Run it locally

Clone and open `space-flight.html` in a browser. That's it.

## History

Built in six versions, each one a commit — `git log` tells the story from
"camera with a throttle" to "ship with a flight model".
