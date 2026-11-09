#!/usr/bin/env bash
# Watch this folder and push changes to the Pi on every save.
#
#   PI=pi@dashboard.local ./sync.sh
#
# layout.py / theme.py / icons.py hot-reload on the Pi by themselves.
# Changes to anything else (dashboard.py, sources/, config.toml) restart the
# service automatically.
set -euo pipefail
PI="${PI:-pi@dashboard.local}"
DEST="${DEST:-~/train-weather-dashboard}"
HOT='^(layout|theme|icons)\.py$'

push() {
  changed=$(rsync -az --itemize-changes --exclude .git --exclude __pycache__ \
            --exclude docs/ --exclude .pytest_cache ./ "$PI:$DEST/" | awk '/^<f/ {print $2}')
  [ -z "$changed" ] && return
  echo "$(date +%T) synced: $(echo "$changed" | tr '\n' ' ')"
  if echo "$changed" | grep -vqE "$HOT"; then
    echo "           restarting service…"
    ssh "$PI" 'sudo systemctl restart dashboard' || true
  fi
}

push
echo "Watching for changes → $PI:$DEST  (Ctrl-C to stop)"
if command -v fswatch >/dev/null; then
  fswatch -o -l 0.3 -e '\.git/' -e '__pycache__' . | while read -r _; do push; done
elif command -v inotifywait >/dev/null; then
  while inotifywait -qq -r -e close_write,create,delete,move --exclude '(\.git|__pycache__)' .; do push; done
else
  echo "Install fswatch (macOS: brew install fswatch) or inotify-tools (Linux)." >&2
  exit 1
fi
