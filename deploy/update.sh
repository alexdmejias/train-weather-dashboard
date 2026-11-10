#!/usr/bin/env bash
# Pull-based updater. Runs ON THE PI from dashboard-update.timer (every ~5 min).
#
#   1. fetch the `deploy` branch (CI only moves it after tests pass)
#   2. if it moved: check it out, reinstall if deps/units changed, restart
#   3. health check: the service must stay up; otherwise roll back and
#      remember the bad commit so it isn't retried until `deploy` moves again
#
# Run by hand:  bash deploy/update.sh          (UPDATE_BRANCH=other to override)
# config.toml is untracked + gitignored, so `git reset --hard` never touches it.
set -euo pipefail

main() {
  DIR="$(cd "$(dirname "$0")/.." && pwd)"
  BRANCH="${UPDATE_BRANCH:-deploy}"
  SERVICE=dashboard
  BAD="$DIR/.git/update-bad-rev"
  cd "$DIR"

  git fetch --quiet origin "$BRANCH"
  old=$(git rev-parse HEAD)
  new=$(git rev-parse FETCH_HEAD)
  [ "$old" = "$new" ] && exit 0
  if [ -f "$BAD" ] && [ "$(cat "$BAD")" = "$new" ]; then
    exit 0   # already tried this one and rolled back
  fi

  changed=$(git diff --name-only "$old" "$new")
  reinstall=0
  if echo "$changed" | grep -qE '^(requirements\.txt|deploy/(install\.sh|.*\.service|.*\.timer))$'; then
    reinstall=1
  fi

  # The timer has no terminal, so sudo must work without a password. Check
  # before touching the checkout: otherwise the new code lands on disk, the
  # restart fails, and the old process keeps running (hot-reloading half of
  # the new files). Nothing is changed, so the next tick simply retries.
  if ! can_sudo "$reinstall"; then
    echo "✗ can't update to ${new::7}: $USER needs passwordless sudo for" \
         "$([ "$reinstall" = 1 ] && echo "install.sh (this update changes dependencies or units)" || echo "systemctl restart $SERVICE")." \
         "See docs/remote-updates.md → Permissions." >&2
    exit 1
  fi

  echo "updating ${old::7} → ${new::7}"
  git reset --hard --quiet "$new"

  if [ "$reinstall" = 1 ]; then
    echo "dependencies or units changed → re-running install.sh"
    bash deploy/install.sh --auto-update
  fi

  if restart_and_check; then
    rm -f "$BAD"
    echo "ok: running ${new::7}"
  else
    echo "✗ ${new::7} failed health check — rolling back to ${old::7}" >&2
    echo "$new" > "$BAD"
    git reset --hard --quiet "$old"
    restart_and_check || echo "✗ rollback is unhealthy too — check journalctl -u $SERVICE" >&2
    exit 1
  fi
}

# Can sudo run what this update needs without a password? `sudo -n -l <cmd>`
# asks the sudoers policy without running the command or prompting.
can_sudo() {
  if [ "$1" = 1 ]; then
    sudo -n true 2>/dev/null
  else
    sudo -n -l systemctl restart "$SERVICE" >/dev/null 2>&1
  fi
}

# Healthy = a NEW process that is still the same process 30 s after start (no
# crash loop; Restart=always would otherwise hide a crash by starting a new
# PID). Requiring a new PID means a restart that didn't happen can't pass.
restart_and_check() {
  local before pid
  before=$(systemctl show -p MainPID --value "$SERVICE")
  if ! sudo -n systemctl restart "$SERVICE"; then
    echo "✗ couldn't restart $SERVICE" >&2
    return 1
  fi
  sleep 5
  pid=$(systemctl show -p MainPID --value "$SERVICE")
  [ "$pid" != 0 ] && [ "$pid" != "$before" ] || return 1
  sleep 30
  [ "$(systemctl is-active "$SERVICE")" = active ] &&
    [ "$pid" != 0 ] && [ "$(systemctl show -p MainPID --value "$SERVICE")" = "$pid" ]
}

# Everything is inside main() so bash has parsed the whole file before
# `git reset` rewrites it.
main "$@"; exit
