#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(cat "${ROOT_DIR}/VERSION")"
OUT_DIR="${ROOT_DIR}/dist"
mkdir -p "${OUT_DIR}"
ZIP="${OUT_DIR}/piviewer-${VERSION}.zip"

cd "${ROOT_DIR}"
rm -f "${ZIP}"
zip -r "${ZIP}" app config docs scripts systemd README.md CHANGELOG.md VERSION -x '*/__pycache__/*'
cp "${ZIP}" "${OUT_DIR}/latest.zip"

cat > "${OUT_DIR}/latest.json" <<JSON
{
  "project": "PiViewer",
  "version": "${VERSION}",
  "release_type": "dev-preview",
  "zip_url": "https://raysnijder.nl/rep/piviewer/latest.zip",
  "install_command": "curl -fsSL https://raysnijder.nl/rep/piviewer/install.sh | sudo bash"
}
JSON

echo "Gemaakt: ${ZIP}"
echo "Gemaakt: ${OUT_DIR}/latest.zip"
echo "Gemaakt: ${OUT_DIR}/latest.json"
