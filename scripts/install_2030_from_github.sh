#!/usr/bin/env bash
set -u

WORK="/tmp/piviewer-2030-install"
ZIP_URL="https://raw.githubusercontent.com/Techraym/PiViewer/main/releases/PiViewer_2030.zip"
INDEX_URL="https://raw.githubusercontent.com/Techraym/PiViewer/main/updates/index.json"

say() { printf '\n=== %s ===\n' "$1"; }
fail() { echo "FOUT: $1"; return 1; }

say "PiViewer 2030 installeren vanaf GitHub"
date

say "Benodigdheden installeren"
apt update
apt install -y curl unzip python3 rsync git zip

say "Downloadmap maken"
rm -rf "$WORK"
mkdir -p "$WORK"
cd "$WORK" || { fail "kan niet naar $WORK"; exit 1; }

say "ZIP downloaden"
curl -fL -o PiViewer_2030.zip "${ZIP_URL}?t=$(date +%s)" || { fail "PiViewer_2030.zip downloaden mislukt"; exit 2; }

say "index.json downloaden"
curl -fsSL "${INDEX_URL}?t=$(date +%s)" -o index.json || { fail "updates/index.json downloaden mislukt"; exit 3; }

say "SHA256 controleren"
EXPECTED_SHA="$(python3 - <<'PY'
import json
with open('index.json', 'r', encoding='utf-8') as f:
    print(json.load(f)['sha256'])
PY
)"
ACTUAL_SHA="$(sha256sum PiViewer_2030.zip | awk '{print $1}')"
echo "EXPECTED_SHA=$EXPECTED_SHA"
echo "ACTUAL_SHA=$ACTUAL_SHA"
if [ "$EXPECTED_SHA" != "$ACTUAL_SHA" ]; then
  fail "SHA256 klopt niet. Installatie gestopt."
  exit 4
fi
echo "SHA256 OK."

say "PiViewer stoppen"
systemctl stop piviewer-dev 2>/dev/null || true
pkill -f mpv 2>/dev/null || true
pkill -f streamlink 2>/dev/null || true
pkill -f framebuffer_slideshow_runner.py 2>/dev/null || true

say "Oude update-locks opruimen"
rm -f /var/lib/piviewer-dev/usb-update-in-progress
rm -f /var/lib/piviewer-dev/web-update-in-progress
rm -f /var/lib/piviewer-dev/github-update-in-progress
rm -f /var/lib/piviewer-dev/run-usb-update.sh
rm -f /var/lib/piviewer-dev/run-web-update.sh

say "ZIP uitpakken"
unzip -q PiViewer_2030.zip || { fail "unzip mislukt"; exit 5; }
[ -d PiViewer_2030 ] || { fail "map PiViewer_2030 ontbreekt na unzip"; exit 6; }

say "Installeren"
cd PiViewer_2030 || { fail "kan niet naar PiViewer_2030"; exit 7; }
bash scripts/install_dev.sh || { fail "install_dev.sh mislukt"; exit 8; }

say "GitHub timer activeren"
systemctl daemon-reload
systemctl enable --now piviewer-github-update.timer 2>/dev/null || true

say "PiViewer herstarten"
systemctl restart piviewer-dev

say "Controle"
cat /opt/piviewer-dev/VERSION 2>/dev/null || true
systemctl is-active piviewer-dev 2>/dev/null || true
systemctl list-timers --all | grep -i piviewer-github || true

say "Klaar"
