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
  constructor(existingCtx = null){
    this.ctx = existingCtx || new (window.AudioContext || window.webkitAudioContext)();
    const ctx = this.ctx;

    // ---- master chain: [everything] -> limiter -> masterGain -> speakers
    this.master = ctx.createGain();
    this.master.gain.value = 0.55;
    const limiter = ctx.createDynamicsCompressor();  // safety net so stacked layers never clip
    limiter.threshold.value = -6; limiter.ratio.value = 12;
    limiter.attack.value = 0.003; limiter.release.value = 0.25;
    this.master.connect(limiter).connect(ctx.destination);

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

    // A minor palette (open + a touch wistful). Danger adds a tritone (Eb) for menace.
    this.NOTES = { A2:110.00, C3:130.81, E3:164.81, A3:220.00, C4:261.63,
                   Eb4:311.13, E4:329.63, A4:440.00, C5:523.25, E5:659.25, A5:880.00 };
    this._started = false;
    this._timers = [];
    this._drones = [];
    this._danger = false;
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
  }

  /* THE reactive call. Ramp danger in/out, duck the ambient a little under threat.
     Safe to call every frame — redundant calls with the same value are ignored. */
  setDanger(on, fade=2.2){
    if(on===this._danger) return;
    this._danger=on;
    const t=this.ctx.currentTime, end=t+fade;
    this.dangerBus.gain.cancelScheduledValues(t);
    this.dangerBus.gain.setValueAtTime(this.dangerBus.gain.value, t);
    this.dangerBus.gain.linearRampToValueAtTime(on?1.0:0.0, end);
    this.ambientBus.gain.cancelScheduledValues(t);
    this.ambientBus.gain.setValueAtTime(this.ambientBus.gain.value, t);
    this.ambientBus.gain.linearRampToValueAtTime(on?0.55:1.0, end);
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
  get ambientLevel(){ return this.ambientBus.gain.value; }
  get dangerLevel(){ return this.dangerBus.gain.value; }
}
