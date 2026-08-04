#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/piviewer-dev"
CONFIG_DIR="/etc/piviewer-dev"
LOG_DIR="/var/log/piviewer-dev"
STATE_DIR="/var/lib/piviewer-dev"
SERVICE_NAME="piviewer-dev.service"

if [ "${EUID}" -ne 0 ]; then
  echo "Voer dit script uit met sudo/root."
  exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== PiViewer Dev installatie =="
echo "Bron: ${SRC_DIR}"

echo "[1/8] Pakketten installeren"
apt-get update
apt-get install -y python3 python3-pil fbi mpv streamlink curl rsync unzip wireless-tools wpasupplicant rfkill isc-dhcp-client exfatprogs dosfstools ntfs-3g ca-certificates fonts-dejavu-core

echo "[2/8] Mappen aanmaken"
mkdir -p "${APP_DIR}" "${CONFIG_DIR}" "${LOG_DIR}" "${STATE_DIR}" "${STATE_DIR}/photo-cache" "${APP_DIR}/media/fallback" "${APP_DIR}/assets"

echo "[3/8] Applicatiebestanden kopiëren"
rsync -a --delete \
  --exclude='.git' \
  "${SRC_DIR}/" "${APP_DIR}/"

echo "[4/8] Configuratie plaatsen indien nodig"
if [ ! -f "${CONFIG_DIR}/piviewer.json" ]; then
  cp "${APP_DIR}/config/piviewer.example.json" "${CONFIG_DIR}/piviewer.json"
  echo "Nieuwe config geplaatst: ${CONFIG_DIR}/piviewer.json"
else
  cp "${CONFIG_DIR}/piviewer.json" "${CONFIG_DIR}/piviewer.json.backup.$(date +%Y%m%d-%H%M%S)"
  echo "Bestaande config behouden en backup gemaakt."
fi

echo "[5/8] systemd-service installeren"
cp "${APP_DIR}/systemd/${SERVICE_NAME}" "/etc/systemd/system/${SERVICE_NAME}"

if [ -f "${APP_DIR}/systemd/piviewer-github-update.service" ]; then
  cp "${APP_DIR}/systemd/piviewer-github-update.service" "/etc/systemd/system/piviewer-github-update.service"
fi

if [ -f "${APP_DIR}/systemd/piviewer-github-update.timer" ]; then
  cp "${APP_DIR}/systemd/piviewer-github-update.timer" "/etc/systemd/system/piviewer-github-update.timer"
fi

systemctl daemon-reload

echo "[6/8] Rechten zetten"
chmod +x "${APP_DIR}/scripts/"*.sh
chmod 755 "${LOG_DIR}" "${STATE_DIR}"

echo "[7/8] Service inschakelen en starten"
systemctl enable "${SERVICE_NAME}"

if [ -f "/etc/systemd/system/piviewer-github-update.timer" ]; then
  systemctl enable --now piviewer-github-update.timer || true
fi

systemctl restart "${SERVICE_NAME}"

echo "[8/8] Klaar"

echo "[extra] Oude raysnijder.nl web-update resten opruimen"
rm -f "${STATE_DIR}/web-update-in-progress" 2>/dev/null || true
rm -f "${STATE_DIR}/run-web-update.sh" 2>/dev/null || true
rm -f "${STATE_DIR}/web-update-last-check.json" 2>/dev/null || true
rm -rf "${STATE_DIR}/web-updates" 2>/dev/null || true
rm -f "${LOG_DIR}/web-update.log" 2>/dev/null || true

if [ -f "${STATE_DIR}/github-update-in-progress" ] && [ "${PIVIEWER_NO_REBOOT:-0}" != "1" ]; then
  echo "[extra] GitHub-update gedetecteerd; Raspberry Pi reboot over 10 seconden."
  touch "${STATE_DIR}/reboot-after-github-update" 2>/dev/null || true
  nohup bash -c 'sleep 10; /bin/systemctl reboot' > "${LOG_DIR}/reboot-after-github-update.log" 2>&1 &
fi

echo "Status: sudo systemctl status ${SERVICE_NAME}"
echo "Logs:   journalctl -u ${SERVICE_NAME} -f"
echo "Config: ${CONFIG_DIR}/piviewer.json"
echo "Web:    http://<ip-van-pi>:8080"
