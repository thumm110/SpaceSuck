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

## The 26 ready-room lines

**All 26 now carry ids and are waiting for files.** His call, 17 Aug, after the
first real walk: *"The ready room lines are fine I just want them spoken."*

⚠️ **This section used to say don't** — that voicing them would "mute the flight
for half a minute a session," because the channel ducks for as long as a clip
runs. **That reason is dead.** It was written when v115 played these on *launch*
from Charleston as a stand-in, while you were actually flying. They play in the
ready room now, where the flight world is stopped and there is nothing to duck.
The objection went out with the stand-in.

⚠️ **EVERY ONE OF THESE IS A TWO-HANDER.** The `|` in the table below is a
**speaker change**, not a line break. You are overhearing a room, not receiving
an announcement — two voices per clip, or one performer doing both sides. Half
the jokes are a setup and a flat reply from someone else, and they die if one
voice reads them straight through.

Same two rules as above: **clean speech, no radio effects** (the game applies
those), and **nobody says your callsign**.

| file | say this |
|---|---|
| `ready-rubicon.mp3` | "—and nobody runs Rubicon at night." / "Nobody runs it in the daytime either." |
| `ready-verdant.mp3` | "Verdant's safe. Verdant's real safe." / "Just remember whose sky you're safe in." |
| `ready-rusthollow.mp3` | "RustHollow pays triple. Don't ask for what." / "Don't ask who's asking." |
| `ready-alloy.mp3` | "Kid ran a full load of alloy to Charleston." / "Full load. Charleston pays flat, dumbass." |
| `ready-belt.mp3` | "Belt's got ore all right." / "Also got four hundred rocks coming back." |
| `ready-cinder.mp3` | "Cinder ain't a landing. Cinder's a dare." *(one voice — the only single in the set)* |
| `ready-shrinkage.mp3` | "You ever seen Shrinkage up close?" / "No. You'd know." |
| `ready-scrap.mp3` | "Half that scrap was somebody's ship once." / "Ain't a ghost story. It's just inventory." |
| `ready-fc.mp3` | "They didn't close Fleet Command." / "They just stopped going." |
| `ready-math.mp3` | "Twenty-five to leave. I did the math once, eleven years in, and then I quit doing math." |
| `ready-air.mp3` | "Twenty-five a launch. I breathe their air and they charge me for the fucking door." |
| `ready-boats.mp3` | "They got a boat called Taxman and one called Shrinkage." / "That's a cry for help." |
| `ready-lanyard.mp3` | "Asked for a raise. Got a lanyard." *(one voice)* |
| `ready-ziptie.mp3` | "This hull's held together with zip ties and they're asking why it reads eighty percent." |
| `ready-safety.mp3` | "Safety says wear the harness." / "Safety ain't never been in a fucking airlock." |
| `ready-visor.mp3` | "They docked me for a cracked visor." / "I cracked it on their shit door frame." |
| `ready-smarter.mp3` | "Guy in dispatch said work smarter." / "Guy in dispatch never moved a crate." |
| `ready-microwave.mp3` | "Microwave's busted. Third time this month." / "Somebody keeps putting metal in it." |
| `ready-boots.mp3` | "Whoever's leaving boots in my locker — I know whose they are and I ain't saying." |
| `ready-bestshift.mp3` | "He clocked in, sat down, clocked out." / "Eight hours. Best shift he ever ran." |
| `ready-coffee.mp3` | "Don't drink the coffee." / "I'm not explaining it. Just don't." |
| `ready-cousin.mp3` | "My cousin bought his own truck." / "Still parks here. Still pays the twenty-five." |
| `ready-companyhull.mp3` | "That one's still flying the company hull." / "We've all been there. Most of us still are." |
| `ready-new.mp3` | "—yeah, that's him. New." / "Give it a week." |
| `ready-pearl.mp3` | "Pearl's been on that desk since before I was." / "Ask her about it. She won't tell you." |
| `ready-dutchdesk.mp3` | "Dutch worked the derelict, you know." / "He don't bring it up and you don't either." |

⚠️ **The last two in the "seeds" group print your callsign and the spoken take
drops it** — `ready-companyhull` and `ready-new` say "that one" and "him" where
the screen says your name. That is the same rule as the six, applied.

## Deliberately not voiced

- **Rung 6 is silent.** Five rungs of people talking at you, then the name
  lights and nobody says anything. That silence is the ending. Don't record one.
  ⛔ "All text lines turned into audible lines" does **not** reach this one — it
  is the only deliberate silence in the game and voicing it deletes the ending.
- **The partial and bank-empty berth fees** quote a number that changes with
  your bank ("7 CR OF 25"). A clip can't say a number it doesn't know, and a
  confident wrong figure is worse than a correct silence. Those stay text.

## Before any of this goes public

⚠️ **Check that your Runway plan actually licenses distributing generated speech
in a released game.** This repo is public and GitHub Pages serves it, so
shipping a clip is publishing it. Worth confirming once. Fine for testing
locally either way.
