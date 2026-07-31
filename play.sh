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
#
# "reset" starts a FRESH CAREER (→ #reset): the load wipes the bank, all
# upgrades and any active contract on THIS machine's save. Callsign, settings
# and the garage survive — money and gear, never who you are. The game strips
# #reset from the URL after the wipe (v90.1), so refreshing mid-career is
# safe. It asks before wiping; close any other SpaceSuck tab first, or that
# tab's old bank saves right back over the wipe.
#
# --phone  serve to the WHOLE network instead of just this machine, print the
#          URLs to open on a phone, and don't bother opening a browser here.
#          For testing the touch UI without a push→Pages→reload round trip.
#          Off by default on purpose: the default bind keeps this folder off
#          the wifi. Ctrl-C or `pkill -f "http.server 8123"` when you're done.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=8123
LOG=/tmp/spacesuck-server.log

PHONE=0
ARGS=()
for a in "$@"; do
  if [[ "$a" == "--phone" ]]; then PHONE=1; else ARGS+=("$a"); fi
done
set -- "${ARGS[@]+"${ARGS[@]}"}"

# the wipe itself happens in the game when #reset loads; this gate only makes
# sure it never happens by a slip of the tab key. read's EOF failure + set -e
# means a non-interactive launch with "reset" bails out instead of wiping.
if [[ "${1:-}" == "reset" ]]; then
  echo "SpaceSuck FRESH CAREER: wipes the bank, upgrades and any active contract"
  echo "on this machine's save. Callsign, settings and garage survive."
  echo "Close any other SpaceSuck tab first — an open tab saves its old bank back."
  read -r -p "ENTER to wipe and fly, Ctrl-C to keep your career... "
fi

# ?v=<timestamp> busts Chrome's cache — a unique URL each launch can't be
# served stale, so you always get the latest build (the game ignores the
# query; it only reads the #earth hash, which still lands after it)
URL="http://localhost:${PORT}/space-flight.html?v=$(date +%s)"
# any body name spawns you on its doorstep (the game lowercases the hash match)
[[ -n "${1:-}" ]] && URL="${URL}#${1}"

# "up" means: something is serving OUR game on that port, not just anything
up() { curl -fs -o /dev/null --max-time 1 "http://localhost:${PORT}/space-flight.html"; }

# A localhost-only server already running can't serve your phone, so --phone
# has to take the port over rather than reuse it.
if [[ $PHONE -eq 1 ]] && up && ! curl -fs -o /dev/null --max-time 1 \
     "http://$(hostname -I | awk '{print $1}'):${PORT}/space-flight.html" 2>/dev/null; then
  echo "SpaceSuck: a localhost-only server owns :$PORT — restarting it on all interfaces."
  pkill -f "http\.server ${PORT}" || true
  sleep 0.4
fi

if ! up; then
  cd "$DIR"
  # --bind 127.0.0.1 keeps the folder off the wifi; setsid detaches the server
  # so it outlives this script and survives the next launch
  BIND=127.0.0.1
  [[ $PHONE -eq 1 ]] && BIND=0.0.0.0
  setsid nohup python3 -m http.server "$PORT" --bind "$BIND" \
    >"$LOG" 2>&1 </dev/null &

  for _ in $(seq 1 60); do
    up && break
    sleep 0.1
  done
fi

if [[ $PHONE -eq 1 ]]; then
  HASH=""
  [[ -n "${1:-}" ]] && HASH="#${1}"
  echo
  echo "  SpaceSuck is serving to your network. Open ONE of these on the phone:"
  echo
  # Tailscale first when it's up: it works off your wifi too, and it doesn't
  # care what the router or the firewall think.
  if command -v tailscale >/dev/null && TS=$(tailscale ip -4 2>/dev/null | head -1) && [[ -n "$TS" ]]; then
    echo "    http://${TS}:${PORT}/space-flight.html${HASH}      <- Tailscale (works anywhere)"
  fi
  for ip in $(hostname -I); do
    [[ "$ip" == *:* ]] && continue                    # IPv6 needs [brackets] in a URL; not worth it
    [[ "$ip" == 192.168.122.* ]] && continue          # libvirt's virtual bridge, not your wifi
    [[ "$ip" == 100.* ]] && continue                  # already printed as Tailscale
    echo "    http://${ip}:${PORT}/space-flight.html${HASH}      <- same wifi only"
  done
  echo
  echo "  Edit the file, then just PULL TO REFRESH on the phone. No commit, no push."
  echo "  Add ?v=\$(date +%s) to the URL if Safari serves you a stale copy."
  echo "  Stop it with:  pkill -f 'http.server ${PORT}'"
  echo
  exit 0
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
