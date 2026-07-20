#!/usr/bin/env python3
"""
space_music.py — render two seamless-looping space tracks to WAV.

  ambient_space.wav  : calm A-minor pad + starfield twinkles  (~30 s loop)
  danger_alert.wav   : tense combat bed, driving pulse + arp   (~17 s loop)

No external audio libs. Just numpy for the math and the stdlib `wave`
module to write the file. Everything is a plain function you can tweak:
change the NOTES, the harmonic count, the tempo, the loop length.

DSP in three ideas:
  1. A "saw" is just a stack of sine harmonics (1/k amplitude). Summing a
     few of them by hand keeps it band-limited (no digital fizz).
  2. Two oscillators detuned a few cents apart slowly drift in and out of
     phase -> that gentle "breathing" movement pads are loved for.
  3. To make ANY audio loop seamlessly, render a hair extra and crossfade
     the end back into the beginning, so the wrap-around is inaudible.
"""

import wave
import numpy as np

SR = 44100  # samples per second (CD quality)


# ----------------------------------------------------------------------
# building blocks
# ----------------------------------------------------------------------
def saw(freq, t, harmonics=12, detune_cents=0.0):
    """Band-limited sawtooth = sum of sine harmonics with 1/k amplitude."""
    f = freq * (2.0 ** (detune_cents / 1200.0))   # cents -> frequency ratio
    out = np.zeros_like(t)
    for k in range(1, harmonics + 1):
        out += np.sin(2 * np.pi * f * k * t) / k
    return out / np.log(harmonics + 1)             # rough level normalize


def one_pole_lowpass(x, cutoff_hz):
    """Cheap warm low-pass. Rolls off the buzzy top of the saws."""
    dt = 1.0 / SR
    rc = 1.0 / (2 * np.pi * cutoff_hz)
    a = dt / (rc + dt)
    y = np.empty_like(x)
    y[0] = x[0] * a
    for i in range(1, len(x)):                     # simple IIR, one sample at a time
        y[i] = y[i - 1] + a * (x[i] - y[i - 1])
    return y


def adsr(n, attack, decay, sustain, release, sustain_len):
    """Amplitude envelope in samples. Returns an array of length ~n."""
    a = int(attack * SR); d = int(decay * SR)
    s = int(sustain_len * SR); r = int(release * SR)
    env = np.concatenate([
        np.linspace(0, 1, a, endpoint=False),
        np.linspace(1, sustain, d, endpoint=False),
        np.full(s, sustain),
        np.linspace(sustain, 0, r),
    ])
    if len(env) < n:
        env = np.pad(env, (0, n - len(env)))
    return env[:n]


def bell(freq, dur=3.5):
    """Soft sine 'ping' with a long exponential tail — the twinkles."""
    t = np.linspace(0, dur, int(dur * SR), endpoint=False)
    tone = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * freq * 2 * t)
    env = np.exp(-t * 1.6)
    return tone * env


def pluck(freq, dur=0.22):
    """Short filtered blip for the danger arpeggio."""
    t = np.linspace(0, dur, int(dur * SR), endpoint=False)
    tone = np.sign(np.sin(2 * np.pi * freq * t))          # square-ish, gritty
    env = np.exp(-t * 22)
    return one_pole_lowpass(tone * env, 1800)


def thud(dur=0.30):
    """Low pitch-drop pulse — the 'combat heartbeat'."""
    t = np.linspace(0, dur, int(dur * SR), endpoint=False)
    freq = 75 * np.exp(-t * 9) + 40                       # 75 Hz swooping to ~40
    tone = np.sin(2 * np.pi * np.cumsum(freq) / SR)
    env = np.exp(-t * 11)
    return tone * env


def stereo(mono, pan=0.0):
    """pan in [-1,1]. Returns (n,2) equal-power stereo."""
    l = np.cos((pan + 1) * np.pi / 4)
    r = np.sin((pan + 1) * np.pi / 4)
    return np.column_stack([mono * l, mono * r])


def add_at(canvas, clip, start):
    """Mix a clip into a stereo canvas at sample offset `start`, trimming any
    part that runs past the end (and skipping clips that start past the end)."""
    if start >= len(canvas):
        return
    end = min(start + len(clip), len(canvas))
    canvas[start:end] += clip[:end - start]


def make_seamless(sig, xfade_sec=1.2):
    """Return a seamless loop from `sig`, which was rendered a bit longer than
    the target loop. The samples just PAST the loop point are the natural
    continuation of the sound, so we crossfade those over the head. The wrap
    then plays as one continuous line and the seam disappears."""
    x = int(xfade_sec * SR)
    D = len(sig) - x                       # loop-body length
    fade = np.linspace(0, 1, x)[:, None]
    overhang = sig[D:D + x]                 # continuation past the loop point
    loop = sig[:D].copy()
    loop[:x] = overhang * (1 - fade) + loop[:x] * fade
    return loop


def normalize(sig, peak=0.89):
    m = np.max(np.abs(sig))
    return sig * (peak / m) if m > 0 else sig


def write_wav(path, sig):
    data = (np.clip(sig, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "w") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(data.tobytes())
    print(f"wrote {path}  ({len(sig)/SR:.1f}s, {data.nbytes/1e6:.1f} MB)")


# A-minor palette (Hz). Danger borrows Eb for the tritone tension.
N = dict(A2=110.00, C3=130.81, E3=164.81, A3=220.00, C4=261.63,
         Eb4=311.13, E4=329.63, A4=440.00, C5=523.25, E5=659.25, A5=880.00)


# ----------------------------------------------------------------------
# track 1 — ambient bed
# ----------------------------------------------------------------------
def render_ambient(loop_sec=30.0, xfade=1.5):
    total = loop_sec + xfade
    t = np.linspace(0, total, int(total * SR), endpoint=False)

    # drone: root/fifth/octave + a soft C for the minor color, each a
    # detuned pair so it slowly beats and breathes.
    pad = np.zeros_like(t)
    for f, lvl in [(N['A2'], 1.0), (N['E3'], 0.7), (N['A3'], 0.6), (N['C4'], 0.4)]:
        pad += lvl * (saw(f, t, detune_cents=-6) + saw(f, t, detune_cents=+6))
    pad = one_pole_lowpass(pad, 620)
    # very slow tremolo so the whole bed swells
    pad *= 0.85 + 0.15 * np.sin(2 * np.pi * 0.05 * t)
    mix = stereo(pad * 0.16)

    # starfield twinkles — start after the crossfade region, finish before the tail
    pent = ['A4', 'C5', 'E5', 'A5', 'E4']
    rng = np.random.default_rng(7)
    tpos = xfade + 0.5
    while tpos < loop_sec - 4.0:
        note = pent[rng.integers(len(pent))]
        b = bell(N[note]) * 0.22
        add_at(mix, stereo(b, pan=rng.uniform(-0.7, 0.7)), int(tpos * SR))
        tpos += rng.uniform(2.6, 5.2)

    return normalize(make_seamless(mix, xfade), 0.82)


# ----------------------------------------------------------------------
# track 2 — danger bed
# ----------------------------------------------------------------------
def render_danger(bpm=112, n_beats=32, xfade=0.4):
    beat = round((60.0 / bpm) * SR)              # beat length in whole samples
    D = n_beats * beat                           # exact => rhythm tiles perfectly
    x = int(xfade * SR)
    t = np.arange(D + x) / SR
    loop_sec = D / SR

    # dark drone: root + tritone, heavily filtered, faster wobble = dread
    drone = (saw(N['A2'], t, detune_cents=-5) + saw(N['A2'], t, detune_cents=5)
             + 0.8 * (saw(N['Eb4'], t, detune_cents=-5) + saw(N['Eb4'], t, detune_cents=5)))
    drone = one_pole_lowpass(drone, 360)
    drone *= 0.8 + 0.2 * np.sin(2 * np.pi * 0.9 * t)
    # faint high shimmer for unease
    shimmer = (saw(N['A5'], t, detune_cents=-12) + saw(N['A5'], t, detune_cents=12))
    shimmer = one_pole_lowpass(shimmer, 2400) * (0.5 + 0.5 * np.sin(2 * np.pi * 5.5 * t))
    mix = stereo(drone * 0.14 + shimmer * 0.015)

    # Driving pulse on every beat + arpeggio on the eighths. We lay hits a few
    # beats PAST the loop end too, so the overhang carries a matching downbeat
    # and the seam crossfade keeps beat 1 punchy instead of fading it in.
    arp = ['A3', 'C4', 'Eb4', 'E4']
    for i in range(n_beats + x // beat + 2):
        add_at(mix, stereo(thud() * 0.55), i * beat)                    # downbeat pulse
        for j, off in enumerate((0, beat // 2)):                        # two eighths / beat
            note = arp[(i * 2 + j) % len(arp)]
            p = pluck(N[note]) * 0.18
            add_at(mix, stereo(p, pan=0.25 if j else -0.25), i * beat + off)

    return normalize(make_seamless(mix, xfade), 0.9)


if __name__ == "__main__":
    write_wav("ambient_space.wav", render_ambient())
    write_wav("danger_alert.wav", render_danger())
    print("done — both files loop seamlessly, drop them straight into the game.")
