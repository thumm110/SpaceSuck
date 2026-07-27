/* hull-plating.js — shared hull material pass + procedural plating shader.
   Loaded by BOTH space-flight.html (the game) and fleet-registry.html (the
   3D fleet viewer), so the two can never drift. Requires three.js first.

   Extracted 2026-07-24. Before this there were FIVE near-copies of the
   material pass across the two files; the registry's copy still had the
   old name-only light test, so hauler lamps read wrong there. */
(function (global) {
"use strict";

/* ---- shared hull material pass (v68) --------------------------------------
   Four .glb load sites each carried a near-copy of this: "*Glow" materials
   glow bright, plain hull gets a faint self-lit floor so it still reads out
   past HELIOS, where the sun's inverse-square falloff would otherwise leave
   the whole ship near-black.

   Hoisted so the weathering shader has ONE place to hook instead of four.
   This is a PURE REFACTOR — each site keeps its exact dialect via opts,
   including the haulers' re-visit bump (see byEmissive). Behaviour verified
   identical across all 303 loaded materials.

     floor       non-glow self-lit intensity (0.15 player, 0.5 everyone else)
     byEmissive  key on the authored emissive VALUE instead of the material
                 NAME — the haulers' dialect, because build_hauler.py names
                 its lights NavRed/MarkerAmber/Headlight/CabWindow, none of
                 which end in "Glow"

   ONE rule classifies every ship, current and future — see LIGHT vs HULL
   below. The old split (name for fighters, emissive-value for haulers) is
   gone, and with it a live bug: keying on the emissive VALUE meant reading
   state this same pass writes, so a material backing 40+ mesh prims got
   re-visited and ratcheted 0.5 -> 1.5 (83 of 90 hauler materials sat at 1.5).
   The rule now reads only NAME and BASE COLOUR, both immutable here, so that
   whole bug class is structurally impossible rather than merely fixed. */

// baseColorFactor at/below this on every channel = a pure-emission material.
// Real lamps export exactly 0; the darkest hull in the fleet (HullCharcoal)
// is 0.0196, so this sits with ~5x margin on both sides.
const PURE_EMISSION_ALBEDO = 0.004;

/* ==================== PROCEDURAL HULL PLATING (v68) ====================
   Blender's add_plating() network — Voronoi panel grooves, rivets, per-plate
   tone, conduit seam glow — re-evaluated per fragment in the game instead of
   baked. glTF can only carry baked image textures, so the whole node graph
   was collapsing to one flat baseColorFactor on export; every ship shipped
   as smooth plastic. See spacesuck/weathering-prototype/ for the workup.

   No bake, no UVs, no rebuild: the pattern is a pure function of SHIP-ROOT
   object space, which is exactly what Blender's tc.object = root fed it. We
   stamp that into a per-vertex attribute once at load (aObjPos), so it costs
   nothing per frame and rides the hull no matter where the ship is.

   IMPORTANT: this AUTHORS a look, it does not port one. Blender's network is
   normal-only, and under this game's rig (one PointLight, dim ambient, no
   tone mapping, plus the fake self-lit emissive floor) a normal-only bump is
   worth ~0.4% of the frame. What actually reads here is modulating ALBEDO
   and totalEmissiveRadiance, which Blender never did. Judge it against
   in-game screenshots, never against the Cycles previews. */
const WEATHER_ON = true;

// Reaches the HULL branch but isn't painted metal — glass, canopies, hull
// lettering. Plating these cracks the glass and shatters the ship's name.
// Regex, not a list, so future ships are covered by naming convention.
const WEATHER_SKIP = /glass|canopy|window|visor|lens|^name/i;

/* Plate density scales with hull size, so this needs no per-ship table.
   The pattern lives in each .glb's own root space, which is ~5-6 Blender units
   for EVERY ship no matter how big it flies — so a fixed scale gives a 52-unit
   freighter the same plate COUNT as a 10-unit fighter, i.e. panels 5x oversized.
   Real hulls hold plate size roughly constant and just use more of them (a
   linear ramp), but a big ship also fills more screen, so linear over-densifies
   and invites aliasing. A fractional exponent splits it: bigger ships get bigger
   plates AND more of them.
     fighter 10 -> 0.97x    raider 10 -> 0.97x    PACKRAT 22 -> 1.27x
     gunship 36 -> 1.51x    hauler  52 -> 1.72x

   0.35 was picked by sweeping SS OVERTIME at 1.0 / 1.47 / 1.73 / 2.17 and
   eyeballing the renders. It is NOT monotonic, which is why it needed a sweep:
   at 1.0 the rivets sit above their LOD fade and the containers read as
   speckled granite, and by 2.17 the plates themselves go fine enough to do the
   same. The clean band where panels read as panels is roughly 1.4-1.8.
   See spacesuck/weathering-prototype/shots/plate_exp*.png. */
const PLATE_REF_LEN = 11;    // fighter baseline the WEATHER numbers were tuned on
const PLATE_EXP = 0.35;
function plateMulFor(shipLen) {
  return (!shipLen || shipLen <= 0) ? 1 : Math.pow(shipLen / PLATE_REF_LEN, PLATE_EXP);
}

/* Fallback lengths by .glb basename, for callers that don't know a ship's world
   length. That's fleet-registry.html, which frames every hull to the same screen
   size — so plate density is the ONLY thing conveying that a freighter is bigger
   than a fighter. Mirrors the `len` values in space-flight.html (and
   ships/fleet.json). A ship missing here just renders at fighter density, which
   is a soft, obvious failure rather than a broken one. */
const SHIP_LEN = {
  "uss-thumm.glb": 10, "uss-boo.glb": 11.5, "uss-char.glb": 11, "uss-samsam.glb": 11.5,
  // all four raiders share PIRATE_SCALE and every stat — see RAIDER_DEFS
  "raider.glb": 10, "raider2.glb": 10, "raider3.glb": 10, "raider4.glb": 10,
  "ss-packrat.glb": 22,
  "ss-timeclock.glb": 30, "ss-shrinkage.glb": 36,
  "ss-overtime.glb": 52, "ss-double-overtime.glb": 65, "canary-freight.glb": 68,
};
function shipLenFor(file) {
  return SHIP_LEN[String(file || "").split("/").pop().split("?")[0]] || 0;
}

// per-material knobs, by name; anything unlisted takes def. This is the
// per-ship tuning surface — a capital ship wants bigger plates than a fighter.
//   edge   plate density (Voronoi scale)      groove  panel-line width
//   riv    rivet density                      ao      how dark the seams go
//   tone   plate-to-plate variation           seam    conduit-glow strength
//   live   seam gate (HIGHER = fewer runs lit; 1.0 = none)
//
// NO normal/bump term, deliberately. These hulls are metallic (0.7-0.9) under a
// single point light, so perturbing the normal at a groove throws a hard
// specular spark; measured, it's binary — bump 0.0 is clean, bump 0.04 already
// speckles the whole hull white, because dFdx() across a near-sub-pixel groove
// is enormous and saturates any clamp. Albedo is what reads under this rig
// anyway (a normal-only pass measured ~0.4% of frame pixels), so the plating
// lives entirely in diffuseColor + totalEmissiveRadiance.
const WEATHER = {
  def:       { edge: 4.0, groove: 0.012, riv: 10.0, ao: 0.52, tone: 0.10, seam: 0.30, live: 0.66 },
  HullRust:  { edge: 4.2, groove: 0.011, riv: 10.0, ao: 0.58, tone: 0.14, seam: 0.30, live: 0.66 },
  HullRust2: { edge: 4.2, groove: 0.011, riv: 10.0, ao: 0.58, tone: 0.14, seam: 0.30, live: 0.66 },
};

/* Stamp ship-root object space into aObjPos on every mesh under a model.
   rel = root.matrixWorld^-1 * mesh.matrixWorld  ==  Blender's tc.object=root.
   Independent of where the ship sits in the world AND of the game's len
   normalization, because both cancel out. */
const _relM = new THREE.Matrix4(), _rootInv = new THREE.Matrix4(), _wv = new THREE.Vector3();
function bakeObjSpace(model) {
  const root = model.children[0] || model;   // every ship .glb has one scene root
  model.updateMatrixWorld(true);
  _rootInv.copy(root.matrixWorld).invert();
  model.traverse(o => {
    if (!o.isMesh || !o.geometry || o.geometry.attributes.aObjPos) return;
    _relM.multiplyMatrices(_rootInv, o.matrixWorld);
    const pos = o.geometry.attributes.position;
    const out = new Float32Array(pos.count * 3);
    for (let i = 0; i < pos.count; i++) {
      _wv.fromBufferAttribute(pos, i).applyMatrix4(_relM);
      out[i * 3] = _wv.x; out[i * 3 + 1] = _wv.y; out[i * 3 + 2] = _wv.z;
    }
    o.geometry.setAttribute("aObjPos", new THREE.BufferAttribute(out, 3));
  });
}

/* Exact bounding box of a loaded model, measured from VERTICES in the model's
   own frame. Drop-in for `new THREE.Box3().setFromObject(model)`, which is what
   every loader used until 2026-07-26.

   WHY: setFromObject takes each mesh's LOCAL axis-aligned box and transforms
   that box by the mesh's world matrix — so a rotated mesh contributes the AABB
   of a rotated AABB, which is always too big. It never mattered while a hull was
   300 small greebles (each box tiny, each error tiny). It started mattering the
   moment mesh_budget.py merged them: one `Merged_Graphite` box spans the entire
   ship, and every ship root carries a small rest tilt from its idle-float
   animation (HaulerRoot 0.80°, the raider 2.00°, TIMECLOCK 0.80°…), so that one
   box gets rotated and inflated.

   Measured cost of the loose version on the joined haulers: capR read 7.769 vs
   a true 7.586 (+2.4%) — a ram capsule fatter than the hull it exists to trace —
   and hscale came out 0.05% small, which drew the ship fractionally short. Both
   silent. Note r128's `setFromObject(obj, true)` "precise" flag does NOT exist;
   its arity is 1 and passing true is ignored, so this has to be done by hand.

   One pass over the vertices at load, same as bakeObjSpace right above. */
const _mbRel = new THREE.Matrix4(), _mbInv = new THREE.Matrix4(), _mbV = new THREE.Vector3();
function modelBox(model, target) {
  const box = (target || new THREE.Box3()).makeEmpty();
  model.updateMatrixWorld(true);
  _mbInv.copy(model.matrixWorld).invert();
  model.traverse(o => {
    if (!o.isMesh || !o.geometry || !o.geometry.attributes.position) return;
    _mbRel.multiplyMatrices(_mbInv, o.matrixWorld);
    const pos = o.geometry.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      box.expandByPoint(_mbV.fromBufferAttribute(pos, i).applyMatrix4(_mbRel));
    }
  });
  return box;
}

/* What this hull sweeps when it turns on the spot (v85.2) — the radius of the
   smallest circle about the model's ORIGIN that contains every vertex in plan,
   and the tallest one off that plane.

   The box above can't answer this. Cornering the box gives hypot(maxX, maxZ),
   which is the circle through the box's CORNER — and no hull actually has a
   vertex there. On USS THUMM that reads 7.27 against a true 6.84, so a menu
   turntable framed off the box parks 6% further back than it needs to, on the
   screen that can least afford it. Same one pass, same frame, exact.

   Callers still want a margin on top: every ship root carries an idle float
   that rocks it a degree or two off rest, and this measures the rest pose. */
function modelSweep(model, target) {
  const out = target || { r: 0, h: 0 };
  out.r = 0; out.h = 0;
  model.updateMatrixWorld(true);
  _mbInv.copy(model.matrixWorld).invert();
  model.traverse(o => {
    if (!o.isMesh || !o.geometry || !o.geometry.attributes.position) return;
    _mbRel.multiplyMatrices(_mbInv, o.matrixWorld);
    const pos = o.geometry.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      _mbV.fromBufferAttribute(pos, i).applyMatrix4(_mbRel);
      const d = _mbV.x * _mbV.x + _mbV.z * _mbV.z;
      if (d > out.r) out.r = d;
      const y = Math.abs(_mbV.y);
      if (y > out.h) out.h = y;
    }
  });
  out.r = Math.sqrt(out.r);
  return out;
}

const WEATHER_GLSL = [
// Blender's MapRange with smoothstep clamping
"float mapSS(float v,float a,float b,float lo,float hi){",
"  float f=clamp((v-a)/(b-a),0.0,1.0); f=f*f*(3.0-2.0*f); return lo+f*(hi-lo);",
"}",
// Integer-free hash (Hoskins). Blender uses a lookup3 uint hash we can't run in
// GLSL ES 1.00 — different cell layout, same statistics. The LOOK is the target.
"vec3 wHash(vec3 p){",
"  p=fract(p*vec3(0.1031,0.1030,0.0973));",
"  p+=dot(p,p.yxz+33.33);",
"  return fract((p.xxy+p.yxx)*p.zyx);",
"}",
// Voronoi F1 (Blender: 3D, EUCLIDEAN, randomness 1.0). .x = distance, .yzw = cell colour
"vec4 vF1(vec3 p){",
"  vec3 c=floor(p), lp=p-c; float md=1e9; vec3 col=vec3(0.0);",
"  for(int k=-1;k<=1;k++)for(int j=-1;j<=1;j++)for(int i=-1;i<=1;i++){",
"    vec3 o=vec3(float(i),float(j),float(k));",
"    vec3 h=wHash(c+o); vec3 v=o+h-lp; float d=length(v);",
"    if(d<md){md=d; col=h;}",
"  }",
"  return vec4(md,col);",
"}",
// Voronoi DISTANCE_TO_EDGE, Blender's structure verbatim: pass 1 finds the
// closest feature point (SQUARED distance); pass 2 takes the min distance to the
// perpendicular bisector plane between it and every other point. NOT F2-F1.
// Returns the closest cell's hash in .yzw too, so the per-plate tone rides along
// free instead of costing a second 27-iteration F1 lookup at the same scale.
"vec4 vEdge(vec3 p){",
"  vec3 c=floor(p), lp=p-c, closest=vec3(0.0), ch=vec3(0.0); float md=1e9;",
"  for(int k=-1;k<=1;k++)for(int j=-1;j<=1;j++)for(int i=-1;i<=1;i++){",
"    vec3 o=vec3(float(i),float(j),float(k));",
"    vec3 h=wHash(c+o); vec3 v=o+h-lp; float d=dot(v,v);",
"    if(d<md){md=d; closest=v; ch=h;}",
"  }",
"  md=1e9;",
"  for(int k=-1;k<=1;k++)for(int j=-1;j<=1;j++)for(int i=-1;i<=1;i++){",
"    vec3 o=vec3(float(i),float(j),float(k));",
"    vec3 v=o+wHash(c+o)-lp; vec3 perp=v-closest; float pl=dot(perp,perp);",
"    if(pl>0.0001){ md=min(md, dot((closest+v)*0.5, perp*inversesqrt(pl))); }",
"  }",
"  return vec4(md,ch);",
"}",
// value noise — Blender's TexNoise Fac, used to pick WHICH seams run live
"float wNoise(vec3 p){",
"  vec3 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);",
"  return mix(mix(mix(wHash(i).x,wHash(i+vec3(1,0,0)).x,f.x),",
"                 mix(wHash(i+vec3(0,1,0)).x,wHash(i+vec3(1,1,0)).x,f.x),f.y),",
"             mix(mix(wHash(i+vec3(0,0,1)).x,wHash(i+vec3(1,0,1)).x,f.x),",
"                 mix(wHash(i+vec3(0,1,1)).x,wHash(i+vec3(1,1,1)).x,f.x),f.y),f.z);",
"}",
""].join("\n");

/* ONE function object shared by every hull material, paired with a constant
   customProgramCacheKey, so the whole fleet compiles ONE program. Per-material
   variation rides in uniforms. (three.js keeps materialProperties.uniforms
   per-material even when the compiled program is shared.) */
function weatherHook(shader) {
  const p = this.userData.weather || WEATHER.def;
  const seam = this.userData.seamGlow;
  // groove is measured in Voronoi-cell units, so it rides the cell scale and
  // must NOT be multiplied — only the two densities scale with hull size
  const mul = this.userData.plateMul || 1;
  shader.uniforms.uWeatherA = { value: new THREE.Vector3(p.edge * mul, p.groove, p.riv * mul) };
  shader.uniforms.uWeatherB = { value: new THREE.Vector4(p.ao, p.tone, p.seam, p.live) };
  // the conduit colour add_plating() authored on the BSDF, rescued in
  // dressHullMats before we overwrote the runaway emissive. No seam colour
  // (haulers, raider) => black => the seam term vanishes.
  shader.uniforms.uSeamCol = {
    value: seam != null ? new THREE.Color(seam) : new THREE.Color(0, 0, 0),
  };
  // Live handle for tuning. onBeforeCompile only re-runs when the program
  // isn't already cached for this material, so needsUpdate does NOT pick up
  // changed userData.weather — poke these .value objects instead:
  //   m.userData.uniforms.uWeatherB.value.z = 0   // kill the seam glow, live
  this.userData.uniforms = shader.uniforms;

  shader.vertexShader =
    "attribute vec3 aObjPos;\nvarying vec3 vObjPos;\n" +
    shader.vertexShader.replace(
      "#include <begin_vertex>",
      "#include <begin_vertex>\n\tvObjPos = aObjPos;"
    );

  shader.fragmentShader =
    "varying vec3 vObjPos;\nuniform vec3 uWeatherA;\nuniform vec4 uWeatherB;\n" +
    "uniform vec3 uSeamCol;\n" + WEATHER_GLSL +
    shader.fragmentShader
      .replace("#include <color_fragment>", "#include <color_fragment>\n" + [
        "\tvec3 wP = vObjPos;",
        // fade the high-frequency terms out as the pattern footprint approaches
        // cell size — without this, grooves and rivets crawl and sparkle at range
        // Each frequency band needs its OWN fade, computed at its own scale.
        // Rivets are ~4x finer than plates, so they go sub-pixel ~4x sooner —
        // share the plate fade and dFdx() on a sub-pixel rivet blows the normal
        // out into a field of white specular sparkle.
        "\tfloat wFoot = length(fwidth(wP));",
        "\tfloat wLod  = clamp(1.0 - wFoot * uWeatherA.x * 3.0, 0.0, 1.0);",
        "\tfloat wLodR = clamp(1.0 - wFoot * uWeatherA.z * 3.0, 0.0, 1.0);",
        "\tvec4 wE = vEdge(wP * uWeatherA.x);",
        "\tfloat wEd = wE.x;",
        "\tfloat wGroove = mapSS(wEd, 0.0, uWeatherA.y, 1.0, 0.0) * wLod;",
        "\tvec4 wF = vF1(wP * uWeatherA.z);",
        "\tfloat wDot  = mapSS(wF.x, 0.08, 0.15, 1.0, 0.0);",
        "\tfloat wBin  = mapSS(wEd, 0.02, 0.05, 0.0, 1.0);",
        "\tfloat wBout = mapSS(wEd, 0.07, 0.11, 1.0, 0.0);",
        "\tfloat wRiv  = wDot * wBin * wBout * wLodR;",
        // per-plate tone: the island Blender built but had to leave disconnected,
        // because routing it into Base Color whitewashed the glTF export
        "\tfloat wTone = 1.0 + (wE.y - 0.5) * 2.0 * uWeatherB.y;",
        // seam AO + rivet catch — the albedo term that actually sells plating
        // under this game's one-light rig. Blender's network was normal-only.
        "\tfloat wShade = wTone * (1.0 - wGroove * uWeatherB.x) * (1.0 + wRiv * 0.06);",
        "\tdiffuseColor.rgb *= wShade;",
        // conduit seam glow: a THIN edge mask (tighter than the groove), gated by
        // a noise pick of which runs are live. add_plating()'s glow_seams branch.
        // uWeatherB.w is the gate — raise it to light fewer runs. Ungated, every
        // panel line lights up and the ship reads as a neon net, not a hull.
        "\tfloat wSeam = mapSS(wEd, 0.0, uWeatherA.y * 0.45, 1.0, 0.0)",
        "\t            * mapSS(wNoise(wP * 2.5), uWeatherB.w, uWeatherB.w + 0.05, 0.0, 1.0)",
        "\t            * uWeatherB.z * wLod;",
      ].join("\n"))
      // the game fakes lighting with emissive = colour * floor; leave that flat
      // and it washes the seams straight back out. Weather it too, then add the
      // conduit glow on top.
      .replace("#include <emissivemap_fragment>", "#include <emissivemap_fragment>\n" +
        "\ttotalEmissiveRadiance = totalEmissiveRadiance * wShade + uSeamCol * wSeam;");
}

/* attach to one hull material. Idempotent, and guards on the HOOK not a
   userData flag: Material.copy() deep-clones userData but does NOT copy
   onBeforeCompile, so a flag would make a clone look weathered while having
   silently lost the shader. */
function weatherHullMat(m, plateMul) {
  if (!WEATHER_ON || !m || m.onBeforeCompile === weatherHook) return;
  if (WEATHER_SKIP.test(m.name)) return;
  m.userData.weather = WEATHER[m.name] || WEATHER.def;
  m.userData.plateMul = plateMul || 1;
  m.onBeforeCompile = weatherHook;          // same fn object => one program
  m.customProgramCacheKey = () => "weatherV1";
  m.extensions = Object.assign({}, m.extensions, { derivatives: true });
  m.needsUpdate = true;
}
/* ==================== end hull plating ==================== */

function dressHullMats(model, opts) {
  const floor = opts.floor;
  const seen = new Set();               // one material backs 40+ prims
  // opts.shipLen = the ship's world length, so plate density tracks hull size.
  // opts.shipFile is the fallback for callers that only know the .glb path.
  const plateMul = plateMulFor(opts.shipLen || shipLenFor(opts.shipFile));
  // stamp ship-root object space once, before any material work
  if (opts.weather && WEATHER_ON) bakeObjSpace(model);
  model.traverse(o => {
    if (!o.isMesh || !o.material) return;
    const m = o.material;
    if (seen.has(m) || !m.emissive) return;   // unlit material — skip, don't throw
    seen.add(m);

    /* LIGHT if the Blender script either named it *Glow, or authored it as
       pure emission (black albedo + a real emissive colour). Both conventions
       are live in the fleet: fighters/capitals use the *Glow suffix, while
       build_hauler.py names its lamps NavRed/NavGreen/MarkerAmber/Headlight.
       Both halves are load-bearing — CanopyGlow is named *Glow but its albedo
       isn't quite black, and the haulers' lamps are black but aren't named. */
    const lit = m.name.endsWith("Glow") ||
      (m.emissive.getHex() !== 0 &&
       m.color.r <= PURE_EMISSION_ALBEDO &&
       m.color.g <= PURE_EMISSION_ALBEDO &&
       m.color.b <= PURE_EMISSION_ALBEDO);

    if (lit) {
      // pure-emission Blender materials export a BLACK base color with the
      // real color in emissiveFactor — keep the loader's emissive, only
      // falling back to base color if emissive came through empty
      if (m.emissive.getHex() === 0) m.emissive.copy(m.color);
      m.emissiveIntensity = 1.5;
    } else {
      /* HULL. add_plating() authors a conduit-glow COLOUR on the BSDF but
         gates its STRENGTH with a procedural mask that cannot survive glTF,
         so char/samsam/thumm hulls arrive carrying a full-strength green /
         orange / cyan emissive that would otherwise light the entire ship.
         Stash it — the weathering shader reads it back as that ship's seam
         colour, straight from the .glb, no per-ship table needed — then
         replace it with the faint self-lit floor. */
      if (m.emissive.getHex() !== 0) m.userData.seamGlow = m.emissive.getHex();
      m.emissive.copy(m.color);
      m.emissiveIntensity = floor;
      if (opts.weather) weatherHullMat(m, plateMul);   // plating rides the hull branch only
    }
  });
}

// exported to window so both pages' inline scripts can reach them
global.dressHullMats = dressHullMats;
global.weatherHullMat = weatherHullMat;
global.weatherHook = weatherHook;
global.bakeObjSpace = bakeObjSpace;
global.modelBox = modelBox;
global.modelSweep = modelSweep;
global.WEATHER = WEATHER;
global.WEATHER_SKIP = WEATHER_SKIP;
global.WEATHER_ON = WEATHER_ON;
})(window);
