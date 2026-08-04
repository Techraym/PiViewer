#!/usr/bin/env bash
set -euo pipefail

echo "== PiViewer Dev Healthcheck =="
echo

echo "Versie:"
cat /opt/piviewer-dev/VERSION 2>/dev/null || echo "VERSION niet gevonden"
echo

echo "Commando's:"
command -v python3 >/dev/null && echo "python3: OK" || echo "python3: MIST"
command -v mpv >/dev/null && echo "mpv: OK" || echo "mpv: MIST"
command -v streamlink >/dev/null && echo "streamlink: OK" || echo "streamlink: MIST"
echo

echo "Config:"
if [ -f /etc/piviewer-dev/piviewer.json ]; then
  python3 -m json.tool /etc/piviewer-dev/piviewer.json >/dev/null && echo "JSON: OK" || echo "JSON: FOUT"
else
  echo "Config ontbreekt"
fi
echo

echo "Service:"
systemctl is-active piviewer-dev.service || true
systemctl --no-pager --full status piviewer-dev.service | sed -n '1,12p'
echo

echo "Webpoort 8080:"
ss -ltnp 2>/dev/null | grep ':8080' || echo "Geen listener op 8080 gevonden"
