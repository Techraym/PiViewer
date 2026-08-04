#!/usr/bin/env bash
set -euo pipefail
USB=$(find /var/lib/piviewer-dev/usbmounts -mindepth 1 -maxdepth 1 -type d | head -n 1)
if [ -z "${USB}" ]; then echo "Geen USB-stick gevonden."; exit 1; fi
sudo mount -o remount,rw "$USB" 2>/dev/null || true
BACKUP_DIR="$USB/PiViewer_Backups"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
VERSION=$(cat /opt/piviewer-dev/VERSION 2>/dev/null | tr ' ' '_' || echo unknown)
BACKUP_NAME="piviewer-backup-${VERSION}-${TIMESTAMP}.tar.gz"
TMP_BACKUP="/tmp/$BACKUP_NAME"
FINAL_BACKUP="$BACKUP_DIR/$BACKUP_NAME"
sudo mkdir -p "$BACKUP_DIR"
sudo tar --exclude="/var/lib/piviewer-dev/photo-cache" --exclude="/var/lib/piviewer-dev/usbmounts" --exclude="/var/lib/piviewer-dev/slideshow.m3u" -czf "$TMP_BACKUP" /opt/piviewer-dev /etc/piviewer-dev /var/log/piviewer-dev
sudo cp "$TMP_BACKUP" "$FINAL_BACKUP"
sudo chown "$USER:$USER" "$FINAL_BACKUP" 2>/dev/null || true
sync
echo "Backup gemaakt: $FINAL_BACKUP"
ls -lh "$FINAL_BACKUP"
