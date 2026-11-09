#!/usr/bin/env bash
# Run ON THE PI from the project folder:  bash deploy/install.sh [--auto-update]
#
#   --auto-update   also install a timer that pulls CI-tested updates from
#                   GitHub every 5 min (needs a git clone, not an rsync copy;
#                   see docs/remote-updates.md). Stays on once enabled.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
AUTO_UPDATE=0
if [ "${1:-}" = "--auto-update" ] || systemctl is-enabled --quiet dashboard-update.timer 2>/dev/null; then
  AUTO_UPDATE=1
fi
if [ "$AUTO_UPDATE" = 1 ] && [ ! -d "$DIR/.git" ]; then
  echo "--auto-update needs a git clone of the repo (this folder has no .git)." >&2
  echo "See docs/remote-updates.md." >&2
  exit 1
fi

echo "→ Installing packages"
sudo apt-get update -qq
sudo apt-get install -y python3-pygame python3-requests python3-protobuf python3-pip git
# MTA real-time feeds are protobuf; this is just the generated schema module
sudo pip3 install --break-system-packages --no-deps gtfs-realtime-bindings

echo "→ Adding $USER_NAME to the video/render/input groups (display + touch access)"
sudo usermod -aG video,render,input "$USER_NAME"

echo "→ Installing systemd service"
sed -e "s|__USER__|$USER_NAME|g" -e "s|__DIR__|$DIR|g" "$DIR/deploy/dashboard.service" \
  | sudo tee /etc/systemd/system/dashboard.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now dashboard.service

if [ "$AUTO_UPDATE" = 1 ]; then
  echo "→ Installing auto-update timer (pulls the 'deploy' branch every 5 min)"
  for unit in dashboard-update.service dashboard-update.timer; do
    sed -e "s|__USER__|$USER_NAME|g" -e "s|__DIR__|$DIR|g" "$DIR/deploy/$unit" \
      | sudo tee "/etc/systemd/system/$unit" >/dev/null
  done
  sudo systemctl daemon-reload
  sudo systemctl enable --now dashboard-update.timer
fi

echo
echo "Done. Next:"
echo "  • it runs with the defaults (11106, Steinway St + Broadway)"
echo "  • to customise: cp config.example.toml config.toml, edit, sudo systemctl restart dashboard"
echo "  • add the screen settings from deploy/config.txt.snippet to /boot/firmware/config.txt and reboot"
echo "  • logs:    journalctl -u dashboard -f"
echo "  • restart: sudo systemctl restart dashboard"
[ "$AUTO_UPDATE" = 1 ] && echo "  • updates: journalctl -u dashboard-update  (force a check: sudo systemctl start dashboard-update)"
true
