#!/usr/bin/env bash
# Run ON THE PI from the project folder:  bash deploy/install.sh
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="${SUDO_USER:-$USER}"

echo "→ Installing packages"
sudo apt-get update -qq
sudo apt-get install -y python3-pygame python3-requests python3-protobuf python3-pip
# MTA real-time feeds are protobuf; this is just the generated schema module
sudo pip3 install --break-system-packages --no-deps gtfs-realtime-bindings

echo "→ Adding $USER_NAME to the video/render/input groups (display + touch access)"
sudo usermod -aG video,render,input "$USER_NAME"

[ -f "$DIR/config.toml" ] || cp "$DIR/config.example.toml" "$DIR/config.toml"

echo "→ Installing systemd service"
sed -e "s|__USER__|$USER_NAME|g" -e "s|__DIR__|$DIR|g" "$DIR/deploy/dashboard.service" \
  | sudo tee /etc/systemd/system/dashboard.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now dashboard.service

echo
echo "Done. Next:"
echo "  • find your station:  python3 $DIR/tools/find_station.py \"bedford\""
echo "  • edit $DIR/config.toml (station ids, weather location)"
echo "  • add the screen settings from deploy/config.txt.snippet to /boot/firmware/config.txt and reboot"
echo "  • logs:    journalctl -u dashboard -f"
echo "  • restart: sudo systemctl restart dashboard"
