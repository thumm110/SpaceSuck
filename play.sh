#!/usr/bin/env bash
# SpaceSuck launcher — double-click the desktop icon, this runs.
#
# Why this exists: the game HAS to be served over http://. Browsers block
# fetch() on file://, so a double-clicked space-flight.html silently falls
# back to the placeholder ship and a procedural Earth. This starts a tiny
# local server (only if one isn't already up) and opens the game on it.
#
# Optional arg: a world name spawns you on its doorstep, e.g. "earth" or
# "rubicon" (→ space-flight.html#earth / #rubicon).

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=8123
LOG=/tmp/spacesuck-server.log

# ?v=<timestamp> busts Chrome's cache — a unique URL each launch can't be
# served stale, so you always get the latest build (the game ignores the
# query; it only reads the #earth hash, which still lands after it)
URL="http://localhost:${PORT}/space-flight.html?v=$(date +%s)"
# any body name spawns you on its doorstep (the game lowercases the hash match)
[[ -n "${1:-}" ]] && URL="${URL}#${1}"

# "up" means: something is serving OUR game on that port, not just anything
up() { curl -fs -o /dev/null --max-time 1 "http://localhost:${PORT}/space-flight.html"; }

if ! up; then
  cd "$DIR"
  # --bind 127.0.0.1 keeps the folder off the wifi; setsid detaches the server
  # so it outlives this script and survives the next launch
  setsid nohup python3 -m http.server "$PORT" --bind 127.0.0.1 \
    >"$LOG" 2>&1 </dev/null &

  for _ in $(seq 1 60); do
    up && break
    sleep 0.1
  done
fi

if ! up; then
  echo "SpaceSuck: couldn't serve on port $PORT — is something else using it?" >&2
  ss -lptn "sport = :$PORT" >&2 || true
  # keep the window around so a double-click failure isn't silent
  command -v zenity >/dev/null && zenity --error --text="SpaceSuck: port $PORT is busy.
See $LOG" 2>/dev/null
  exit 1
fi

# --app gives a clean window with no address bar; falls back to the default browser
if command -v google-chrome-stable >/dev/null; then
  exec google-chrome-stable --app="$URL" --start-maximized
else
  exec xdg-open "$URL"
fi
