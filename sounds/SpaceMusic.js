/**
 * SpaceMusic — generative, reactive background music for a space game.
 *
 * Pure Web Audio API: no files, no libraries, nothing to bundle. It runs an
 * ambient bed constantly and fades in a tense "danger" layer (driving pulse +
 * dissonant arpeggio + tritone drone) whenever you tell it hostiles are near.
 *
 * Suggested location: src/audio/SpaceMusic.js
 *
 * Usage:
 *   import SpaceMusic from './audio/SpaceMusic.js';
 *
 *   // Share the game's existing AudioContext if there is one (recommended):
 *   //   const music = new SpaceMusic(THREE.AudioContext.getContext());
 *   const music = new SpaceMusic();
 *
 *   await music.start();               // call ONCE, from a user gesture (see note)
 *   music.setDanger(hostilesOnRadar);  // call whenever radar state changes (per-frame is fine)
 *   music.setMasterVolume(0.6);        // 0..1
 *   music.stop();                      // optional: on scene teardown
 *
 * Browser autoplay note: audio can't start until the user interacts with the
 * page. Call start() from the SAME place you already unlock/resume the engine
 * audio (a click or keypress). If nothing unlocks audio yet, add a one-time
 * listener that calls start() on first pointerdown/keydown.
 */
export default class SpaceMusic {
  /* destNode (v116): where the finished score is delivered. Defaults to the
     speakers, which is what the demo page and every earlier caller get. The
     game passes its DUCK bus instead, so a radio transmission can drop the
     score for a second without touching setMasterVolume() — the two would
     fight over the same gain if they shared a node. */
  constructor(existingCtx = null, destNode = null){
    this.ctx = existingCtx || new (window.AudioContext || window.webkitAudioContext)();
    const ctx = this.ctx;

    // ---- master chain: [everything] -> limiter -> masterGain -> speakers
    this.master = ctx.createGain();
    this.master.gain.value = 0.55;
    const limiter = ctx.createDynamicsCompressor();  // safety net so stacked layers never clip
    limiter.threshold.value = -6; limiter.ratio.value = 12;
    limiter.attack.value = 0.003; limiter.release.value = 0.25;
    this.master.connect(limiter).connect(destNode || ctx.destination);

    // ---- a shared reverb "send" gives everything that big-empty-space tail
    this.reverb = ctx.createConvolver();
    this.reverb.buffer = this._makeReverbIR(3.2);
    this.reverbSend = ctx.createGain(); this.reverbSend.gain.value = 0.9;
    this.reverbSend.connect(this.reverb).connect(this.master);

    // ---- two buses. Ambient is always up; danger fades in on setDanger(true).
    this.ambientBus = ctx.createGain(); this.ambientBus.gain.value = 0.0; // raised in start()
    this.dangerBus  = ctx.createGain(); this.dangerBus.gain.value  = 0.0; // raised on danger
    this.ambientBus.connect(this.master); this.ambientBus.connect(this.reverbSend);
    this.dangerBus.connect(this.master);  this.dangerBus.connect(this.reverbSend);

    /* v124: the YARD bus — on-foot music for Charleston Operations. Same
       grammar as the danger layer (always running, crossfaded by a gain), but
       a different world: a break room is small and carpeted where space is
       vast, so this bus is mostly DRY — only a whisper of the shared reverb,
       or the coffee machine sounds like it's in a cathedral. */
    this.yardBus = ctx.createGain(); this.yardBus.gain.value = 0.0;
    this.yardBus.connect(this.master);
    this._yardVerb = ctx.createGain(); this._yardVerb.gain.value = 0.12;
    this.yardBus.connect(this._yardVerb).connect(this.reverbSend);

    // A minor palette (open + a touch wistful). Danger adds a tritone (Eb) for menace.
    // The yard vamp borrows the same family — Am7 / Fmaj7 — so walking out the
    // door back under the score never sounds like a key change.
    this.NOTES = { F2:87.31, A2:110.00, C3:130.81, E3:164.81, G3:196.00,
                   A3:220.00, C4:261.63, D4:293.66, Eb4:311.13, E4:329.63,
                   G4:392.00, A4:440.00, C5:523.25, E5:659.25, A5:880.00 };
    this._started = false;
    this._timers = [];
    this._drones = [];
    this._danger = false;
    this._scene = 'flight';
  }

  /* ----- persistent drone made of detuned oscillators through one filter ----- */
  _drone(freqs, {type='sawtooth', cutoff=520, gain=0.07, bus, detune=6, lfoRate=0.05, lfoDepth=180}={}){
    const ctx=this.ctx;
    const filter=ctx.createBiquadFilter(); filter.type='lowpass'; filter.frequency.value=cutoff;
    const g=ctx.createGain(); g.gain.value=gain;
    filter.connect(g).connect(bus);
    // slow filter sweep = the sound "breathes"
    const lfo=ctx.createOscillator(); const lfoG=ctx.createGain();
    lfo.frequency.value=lfoRate; lfoG.gain.value=lfoDepth;
    lfo.connect(lfoG).connect(filter.frequency); lfo.start();
    const oscs=[];
    freqs.forEach(f=>{
      [-detune, detune].forEach(dt=>{
        const o=ctx.createOscillator(); o.type=type; o.frequency.value=f; o.detune.value=dt;
        o.connect(filter); o.start(); oscs.push(o);
      });
    });
    return {filter,g,lfo,oscs};
  }

  /* ----- a soft "bell" ping for the ambient starfield twinkle ----- */
  _bell(freq){
    const ctx=this.ctx, now=ctx.currentTime;
    const o=ctx.createOscillator(); o.type='sine'; o.frequency.value=freq;
    const g=ctx.createGain(); g.gain.value=0;
    const pan=ctx.createStereoPanner(); pan.pan.value=(Math.random()*1.6)-0.8;
    o.connect(g).connect(pan);
    pan.connect(this.reverbSend);                 // mostly wet = distant, floaty
    const dry=ctx.createGain(); dry.gain.value=0.25; pan.connect(dry).connect(this.ambientBus);
    g.gain.setValueAtTime(0, now);
    g.gain.linearRampToValueAtTime(0.13, now+0.04);
    g.gain.exponentialRampToValueAtTime(0.0001, now+3.6);
    o.start(now); o.stop(now+3.8);
  }

  /* ----- short plucky note for the danger arpeggio ----- */
  _pluck(freq){
    const ctx=this.ctx, now=ctx.currentTime;
    const o=ctx.createOscillator(); o.type='triangle'; o.frequency.value=freq;
    const f=ctx.createBiquadFilter(); f.type='lowpass'; f.frequency.value=1600;
    const g=ctx.createGain(); g.gain.value=0;
    o.connect(f).connect(g).connect(this.dangerBus);
    const wet=ctx.createGain(); wet.gain.value=0.35; g.connect(wet).connect(this.reverbSend);
    g.gain.setValueAtTime(0, now);
    g.gain.linearRampToValueAtTime(0.09, now+0.004);
    g.gain.exponentialRampToValueAtTime(0.0001, now+0.22);
    o.start(now); o.stop(now+0.3);
  }

  /* ----- low driving pulse = "combat heartbeat" ----- */
  _thud(){
    const ctx=this.ctx, now=ctx.currentTime;
    const o=ctx.createOscillator(); o.type='sine';
    o.frequency.setValueAtTime(75, now); o.frequency.exponentialRampToValueAtTime(42, now+0.12);
    const g=ctx.createGain(); g.gain.value=0;
    o.connect(g).connect(this.dangerBus);
    g.gain.setValueAtTime(0, now);
    g.gain.linearRampToValueAtTime(0.28, now+0.005);
    g.gain.exponentialRampToValueAtTime(0.0001, now+0.28);
    o.start(now); o.stop(now+0.32);
  }

  _makeReverbIR(seconds){
    const ctx=this.ctx, rate=ctx.sampleRate, len=Math.floor(rate*seconds);
    const buf=ctx.createBuffer(2, len, rate);
    for(let ch=0; ch<2; ch++){
      const d=buf.getChannelData(ch);
      for(let i=0;i<len;i++){ d[i]=(Math.random()*2-1)*Math.pow(1-i/len, 2.6); }
    }
    return buf;
  }

  async start(){
    if(this._started) return;
    this._started=true;
    if(this.ctx.state==='suspended') await this.ctx.resume();
    const N=this.NOTES, ctx=this.ctx, now=ctx.currentTime;

    // fade the ambient bed up gently on boot
    this.ambientBus.gain.setValueAtTime(0, now);
    this.ambientBus.gain.linearRampToValueAtTime(1.0, now+3);

    // --- AMBIENT (always playing) ---
    this._drones.push(this._drone([N.A2, N.A3, N.E3, N.C4, N.A4],
      {type:'sawtooth', cutoff:520, gain:0.055, bus:this.ambientBus, lfoRate:0.045, lfoDepth:200}));
    this._drones.push(this._drone([N.A2],
      {type:'triangle', cutoff:300, gain:0.10, bus:this.ambientBus, detune:0, lfoRate:0.03, lfoDepth:60})); // sub

    // twinkle scheduler
    const pent=[N.A4,N.C5,N.E5,N.A5,N.E4];
    const twinkle=()=>{
      this._bell(pent[(Math.random()*pent.length)|0]);
      this._timers.push(setTimeout(twinkle, 2600+Math.random()*4200));
    };
    this._timers.push(setTimeout(twinkle, 1200));

    // --- DANGER (always playing, but muted until setDanger(true)) ---
    this._drones.push(this._drone([N.A2, N.Eb4],  // root + tritone = unease
      {type:'sawtooth', cutoff:330, gain:0.07, bus:this.dangerBus, lfoRate:0.9, lfoDepth:120}));
    this._drones.push(this._drone([N.A5],         // tense high shimmer
      {type:'sawtooth', cutoff:2200, gain:0.02, bus:this.dangerBus, detune:12, lfoRate:5.5, lfoDepth:400}));

    // driving pulse + arpeggio (they only *sound* when dangerBus is up)
    const BPM=112, beat=60/BPM;
    const arp=[N.A3, N.C4, N.Eb4, N.E4]; let step=0;
    const pulse=()=>{
      this._thud();
      this._pluck(arp[step%arp.length]); step++;
      this._pluck(arp[step%arp.length]); step++; // eighth-note feel
      this._timers.push(setTimeout(pulse, beat*1000));
    };
    this._timers.push(setTimeout(pulse, 300));

    // --- YARD (v124: always playing, muted until setScene('yard')) ---
    // Break-room lo-fi: a warm two-chord vamp, a lazy swung beat, sparse keys
    // and vinyl hiss. Everything at low gain — it's a radio on a shelf, not a
    // score. Chords alternate Am7 / Fmaj7 every eight slow beats.
    const yBeat = 60/72;                                  // ~72 BPM, lazy
    // vinyl bed: looped noise, dark-filtered, barely there
    const vlen = Math.floor(ctx.sampleRate * 2);
    const vbuf = ctx.createBuffer(1, vlen, ctx.sampleRate);
    const vd = vbuf.getChannelData(0);
    for (let i = 0; i < vlen; i++) vd[i] = (Math.random()*2-1) * (Math.random() < 0.0004 ? 0.9 : 0.05);
    const vsrc = ctx.createBufferSource(); vsrc.buffer = vbuf; vsrc.loop = true;
    const vfil = ctx.createBiquadFilter(); vfil.type='lowpass'; vfil.frequency.value=2400;
    const vg = ctx.createGain(); vg.gain.value = 0.05;
    vsrc.connect(vfil).connect(vg).connect(this.yardBus); vsrc.start();
    this._drones.push({filter:vfil, g:vg, lfo:{stop(){}}, oscs:[vsrc]});   // stop() reaches it
    // the vamp
    const CHORDS = [[N.A2,N.C3,N.E3,N.G3],[N.F2,N.A2,N.C3,N.E3]];
    let bar = 0;
    const vamp = () => {
      this._pad(CHORDS[bar % 2], yBeat*8);
      bar++;
      this._timers.push(setTimeout(vamp, yBeat*8*1000));
    };
    this._timers.push(setTimeout(vamp, 200));
    // the beat: kick on 1 and the swung 3-and, brushy snare on 2 and 4
    let yStep = 0;
    const groove = () => {
      const s = yStep % 4;
      if (s === 0) this._softKick();
      if (s === 2) this._timers.push(setTimeout(()=>this._softKick(), yBeat*660)); // swung
      if (s === 1 || s === 3) this._brush();
      yStep++;
      this._timers.push(setTimeout(groove, yBeat*1000));
    };
    this._timers.push(setTimeout(groove, 600));
    // sparse keys: minor-pentatonic noodling with rests
    const keys=[N.A3,N.C4,N.D4,N.E4,N.G4,N.A4];
    const noodle=()=>{
      if (Math.random() < 0.7) this._key(keys[(Math.random()*keys.length)|0]);
      this._timers.push(setTimeout(noodle, (1.5+Math.random()*3)*1000));
    };
    this._timers.push(setTimeout(noodle, 2000));
  }

  /* ----- yard voices (v124): all deliver into yardBus ----- */
  _pad(freqs, dur){                       // slow warm chord, triangle cluster
    const ctx=this.ctx, now=ctx.currentTime;
    const f=ctx.createBiquadFilter(); f.type='lowpass'; f.frequency.value=900;
    const g=ctx.createGain(); g.gain.value=0;
    f.connect(g).connect(this.yardBus);
    const oscs=[];
    freqs.forEach(fr=>{ [-4,4].forEach(dt=>{
      const o=ctx.createOscillator(); o.type='triangle'; o.frequency.value=fr; o.detune.value=dt;
      o.connect(f); o.start(now); o.stop(now+dur+1.2); oscs.push(o);
    });});
    g.gain.setValueAtTime(0, now);
    g.gain.linearRampToValueAtTime(0.055, now+1.4);
    g.gain.setValueAtTime(0.055, now+dur-1.2);
    g.gain.linearRampToValueAtTime(0.0001, now+dur+1.0);
  }
  _softKick(){                            // rounder, quieter cousin of _thud
    const ctx=this.ctx, now=ctx.currentTime;
    const o=ctx.createOscillator(); o.type='sine';
    o.frequency.setValueAtTime(58, now); o.frequency.exponentialRampToValueAtTime(40, now+0.09);
    const g=ctx.createGain(); g.gain.value=0;
    o.connect(g).connect(this.yardBus);
    g.gain.setValueAtTime(0, now);
    g.gain.linearRampToValueAtTime(0.12, now+0.004);
    g.gain.exponentialRampToValueAtTime(0.0001, now+0.20);
    o.start(now); o.stop(now+0.24);
  }
  _brush(){                               // filtered-noise brush, not a crack
    const ctx=this.ctx, now=ctx.currentTime;
    const len=Math.floor(ctx.sampleRate*0.09);
    const buf=ctx.createBuffer(1, len, ctx.sampleRate);
    const d=buf.getChannelData(0);
    for(let i=0;i<len;i++) d[i]=(Math.random()*2-1)*(1-i/len);
    const s=ctx.createBufferSource(); s.buffer=buf;
    const f=ctx.createBiquadFilter(); f.type='bandpass'; f.frequency.value=2600; f.Q.value=0.8;
    const g=ctx.createGain(); g.gain.value=0.05;
    s.connect(f).connect(g).connect(this.yardBus);
    s.start(now);
  }
  _key(freq){                             // soft e-piano-ish pluck, longer tail
    const ctx=this.ctx, now=ctx.currentTime;
    const o=ctx.createOscillator(); o.type='triangle'; o.frequency.value=freq;
    const f=ctx.createBiquadFilter(); f.type='lowpass'; f.frequency.value=1150;
    const g=ctx.createGain(); g.gain.value=0;
    o.connect(f).connect(g).connect(this.yardBus);
    g.gain.setValueAtTime(0, now);
    g.gain.linearRampToValueAtTime(0.07, now+0.008);
    g.gain.exponentialRampToValueAtTime(0.0001, now+0.9);
    o.start(now); o.stop(now+1.0);
  }

  /* THE reactive call. Ramp danger in/out, duck the ambient a little under threat.
     Safe to call every frame — redundant calls with the same value are ignored. */
  setDanger(on, fade=2.2){
    if(on===this._danger) return;
    this._danger=on;
    /* v124: in the yard there are no raiders and no score — record the state
       for the walk back out, but never ramp the flight buses under the
       break-room radio. setScene('flight') re-applies whatever is true. */
    if(this._scene!=='flight') return;
    const t=this.ctx.currentTime, end=t+fade;
    this.dangerBus.gain.cancelScheduledValues(t);
    this.dangerBus.gain.setValueAtTime(this.dangerBus.gain.value, t);
    this.dangerBus.gain.linearRampToValueAtTime(on?1.0:0.0, end);
    this.ambientBus.gain.cancelScheduledValues(t);
    this.ambientBus.gain.setValueAtTime(this.ambientBus.gain.value, t);
    this.ambientBus.gain.linearRampToValueAtTime(on?0.55:1.0, end);
  }

  /* v124: which WORLD the score plays for. 'flight' is the space bed (plus
     danger, when set); 'yard' is the on-foot break-room radio. One master,
     one duck chain — a radio transmission still drops whichever is up. */
  setScene(scene, fade=1.6){
    if(scene===this._scene) return;
    this._scene=scene;
    const t=this.ctx.currentTime, end=t+fade;
    const ramp=(node,v)=>{
      node.gain.cancelScheduledValues(t);
      node.gain.setValueAtTime(node.gain.value, t);
      node.gain.linearRampToValueAtTime(v, end);
    };
    if(scene==='yard'){
      ramp(this.yardBus, 1.0); ramp(this.ambientBus, 0.0); ramp(this.dangerBus, 0.0);
    } else {
      ramp(this.yardBus, 0.0);
      ramp(this.ambientBus, this._danger?0.55:1.0);
      ramp(this.dangerBus, this._danger?1.0:0.0);
    }
  }

  setMasterVolume(v){ this.master.gain.setTargetAtTime(v, this.ctx.currentTime, 0.05); }

  /* Optional: halt schedulers and drones (e.g. leaving the game scene). */
  stop(){
    this._timers.forEach(clearTimeout); this._timers = [];
    this._drones.forEach(d => {
      d.oscs.forEach(o => { try { o.stop(); } catch(e){} });
      try { d.lfo.stop(); } catch(e){}
    });
    this._drones = [];
    this._started = false;
  }

  get danger(){ return this._danger; }
  get scene(){ return this._scene; }
  get ambientLevel(){ return this.ambientBus.gain.value; }
  get dangerLevel(){ return this.dangerBus.gain.value; }
  get yardLevel(){ return this.yardBus.gain.value; }
}
