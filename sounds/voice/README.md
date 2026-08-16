# Voice lines — the dispatch channel

Drop finished clips in this folder as `<id>.mp3`. The game preloads them on the
first keypress, and any clip that isn't here just doesn't play — the line still
appears on the message channel with its squelch, exactly as it did in v116. So
you can record these one at a time and hear each one land as you go.

## Two rules that matter more than the performance

**1. Give Runway CLEAN speech. Do not add radio effects, static, or EQ.**
The game applies the radio character itself at runtime — telephone band,
saturation, compressor — in `space-flight.html` under `THE VOICE CHAIN`. Baking
it into the files means retuning how the radio sounds costs you forty
regenerations instead of four numbers, and it locks the character to whatever
made these particular files. Four knobs, if you want to push it:

| constant | now | what it does |
|---|---:|---|
| `VOICE_HP` | 320 | low end cut. Higher = tinnier, more handheld |
| `VOICE_LP` | 3200 | top end cut. Lower = more muffled/distant |
| `VOICE_GRIT` | 1.9 | drive. Under ~1.2 is clean, over ~3 is a robot |
| `VOICE_LEVEL` | 1.15 | output trim |

**2. Nobody says your callsign.** A recording can't know it. The written lines
use `{P}` and the *text on screen* still shows it — the spoken version just
leaves it out, which is why the lines below aren't word-for-word the table.

## The six clips

Mono is fine. Anything `decodeAudioData` accepts works; `.mp3` is what the
loader asks for.

| file | who | say this |
|---|---|---|
| `rung1-dispatch.mp3` | **DISPATCH** — company clerk. Bored, reading off a screen, not congratulating you. | "Filing's clear. The wreck's yours. So's anything still on it." |
| `rung2-hauler.mp3` | **HAULER** — a working trucker who's seen the lights come on. Curious, a little wistful. | "That you lighting up the dead one? Ran that lane six years. Thought it was a ghost." |
| `rung3-dutch.mp3` | **DUTCH** — was there when the station went dark. Older, quiet, means it. | "They pulled us off that station in a week. You're already past where we got." |
| `rung4-ark.mp3` | **RAIDERS ARK** — pirates. Amused, needling, not yet threatening. | "Cute paint on them berths. Who exactly is coming?" |
| `rung5-independent.mp3` | **INDEPENDENT** — your first customer, running on fumes. Half asking, half taking the piss. | "Berth three's lit and I'm running on fumes. You open, or you just showing off?" |
| `fee-full.mp3` | **SPACESUCK** — the company, automated. Flat, no feeling, a machine taking your money. | "Berth fee. Twenty-five credits." |

## Deliberately not voiced

- **Rung 6 is silent.** Five rungs of people talking at you, then the name
  lights and nobody says anything. That silence is the ending. Don't record one.
- **The partial and bank-empty berth fees** quote a number that changes with
  your bank ("7 CR OF 25"). A clip can't say a number it doesn't know, and a
  confident wrong figure is worse than a correct silence. Those stay text.
- **The 26 ready-room lines.** They're 4–6 seconds each and the channel ducks
  the room for as long as a clip runs — voicing all of them would mute the
  flight for half a minute a session, in exchange for jokes that already land in
  print. They've also never been heard in play, so a few are expected to change.
  Adding one later is one edit: append an id as a third element in `READY_ROOM`
  and drop the file here.

## Before any of this goes public

⚠️ **Check that your Runway plan actually licenses distributing generated speech
in a released game.** This repo is public and GitHub Pages serves it, so
shipping a clip is publishing it. Worth confirming once. Fine for testing
locally either way.
