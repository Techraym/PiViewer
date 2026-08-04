#!/usr/bin/env bash
set -euo pipefail

VERSION_TEXT=$(cat /opt/piviewer-dev/VERSION)
VERSION_NUMBER=$(echo "$VERSION_TEXT" | grep -oE '[0-9]+' | tail -n 1)
REPO_DIR="$HOME/PiViewer-github"
REPO_SSH="git@github.com:Techraym/PiViewer.git"
RAW_BASE="https://raw.githubusercontent.com/Techraym/PiViewer/main"

sudo apt update
sudo apt install -y git rsync zip unzip python3

if [ ! -d "$REPO_DIR/.git" ]; then
  git clone "$REPO_SSH" "$REPO_DIR"
else
  git -C "$REPO_DIR" pull --rebase origin main || true
fi

cd "$REPO_DIR"
git checkout -B main

rsync -a --delete /opt/piviewer-dev/ "$REPO_DIR/" \
  --exclude ".git/" \
  --exclude "__pycache__/" \
  --exclude "*.pyc" \
  --exclude "*.pyo" \
  --exclude ".pytest_cache/" \
  --exclude "photo-cache/" \
  --exclude "usbmounts/" \
  --exclude "*.log" \
  --exclude "generated/" \
  --exclude "tmp/" \
  --exclude "*.tar.gz" \
  --exclude "releases/" \
  --exclude "updates/"

cat > .gitignore <<'EOF'
__pycache__/
*.pyc
*.pyo
*.log
.env
.env.*
photo-cache/
usbmounts/
generated/
tmp/
*.tar.gz
EOF

mkdir -p releases updates backup-info

PKG_ROOT=$(mktemp -d)
PKG_DIR="$PKG_ROOT/PiViewer_${VERSION_NUMBER}"
mkdir -p "$PKG_DIR"

rsync -a /opt/piviewer-dev/ "$PKG_DIR/" \
  --exclude "__pycache__/" \
  --exclude "*.pyc" \
  --exclude "*.pyo" \
  --exclude "*.log" \
  --exclude "generated/" \
  --exclude "tmp/" \
  --exclude "*.tar.gz"

(cd "$PKG_ROOT" && zip -qr "$REPO_DIR/releases/PiViewer_${VERSION_NUMBER}.zip" "PiViewer_${VERSION_NUMBER}")
rm -rf "$PKG_ROOT"

sha256sum "releases/PiViewer_${VERSION_NUMBER}.zip" | tee "releases/PiViewer_${VERSION_NUMBER}.zip.sha256"

VERSION_TEXT="$VERSION_TEXT" VERSION_NUMBER="$VERSION_NUMBER" python3 - <<'PY'
import json
import os
import time
from pathlib import Path

version = os.environ['VERSION_TEXT']
num = int(os.environ['VERSION_NUMBER'])
repo = Path('.')
zip_path = repo / 'releases' / f'PiViewer_{num}.zip'
sha_path = repo / 'releases' / f'PiViewer_{num}.zip.sha256'
sha = sha_path.read_text(encoding='utf-8').split()[0]
index_path = repo / 'updates' / 'index.json'
try:
    index = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else {}
except Exception:
    index = {}
versions = [v for v in index.get('versions', []) if int(v.get('version_number', 0) or 0) != num]
versions.append({
    'version': version,
    'version_number': num,
    'zip_url': f'https://raw.githubusercontent.com/Techraym/PiViewer/main/releases/PiViewer_{num}.zip',
    'sha256_url': f'https://raw.githubusercontent.com/Techraym/PiViewer/main/releases/PiViewer_{num}.zip.sha256',
    'sha256': sha,
    'size_bytes': zip_path.stat().st_size,
})
versions = sorted(versions, key=lambda x: int(x.get('version_number', 0) or 0))
index = {
    'project': 'PiViewer',
    'channel': 'main',
    'latest': max(int(v.get('version_number', 0) or 0) for v in versions),
    'release_base_url': 'https://raw.githubusercontent.com/Techraym/PiViewer/main/releases/',
    'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    'versions': versions,
}
index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
PY

cat > backup-info/github-update-current.txt <<EOF
PiViewer GitHub update release gepubliceerd
Datum: $(date)
Host: $(hostname)
Versie: $VERSION_TEXT

Index:
$RAW_BASE/updates/index.json
EOF

git config user.name "Techraym"
git config user.email "techraym@users.noreply.github.com"
git add -A
git commit -m "Publish $VERSION_TEXT with SHA update metadata" || echo "Geen wijzigingen om te committen."
git push -u origin main

echo "Klaar."
echo "$RAW_BASE/updates/index.json"
