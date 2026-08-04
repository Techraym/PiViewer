#!/usr/bin/env bash
set +e

WORK="${HOME}/PiViewer-pidev-2030"
VERSION="2034"
VERSION_TEXT="PiViewer 2034"
REPO="git@github.com:Techraym/PiViewer.git"

result_code=0

echo "=== PiViewer 2034 final title migration helper ==="
echo "Werkmap: ${WORK}"

if [ ! -d "${WORK}/.git" ]; then
  echo "FOUT: git werkmap niet gevonden: ${WORK}"
  ls -ld "${HOME}"/PiViewer* 2>/dev/null || true
  echo "RESULT_CODE=1"
  echo "Script klaar. SSH blijft open."
else
  cd "${WORK}"

  echo
  echo "=== GitHub SSH controleren ==="
  git remote set-url origin "${REPO}"
  SSH_TEST="$(ssh -T git@github.com 2>&1 || true)"
  echo "${SSH_TEST}"
  if ! echo "${SSH_TEST}" | grep -qiE "successfully authenticated|Hi "; then
    echo "FOUT: GitHub SSH werkt niet vanaf PiDev."
    result_code=2
  fi

  if [ "${result_code}" -eq 0 ]; then
    echo
    echo "=== Lokale wijzigingen opruimen ==="
    git rebase --abort 2>/dev/null || true
    git reset --hard HEAD
    git clean -fd

    echo
    echo "=== Laatste GitHub main ophalen ==="
    git fetch origin main
    git reset --hard origin/main
    PULL_CODE=$?
    echo "PULL_CODE=${PULL_CODE}"
    if [ "${PULL_CODE}" -ne 0 ]; then
      echo "FOUT: GitHub main ophalen mislukt."
      result_code=3
    fi
  fi

  if [ "${result_code}" -eq 0 ]; then
    echo
    echo "=== Versie naar ${VERSION_TEXT} zetten ==="
    echo "${VERSION_TEXT}" > VERSION

    echo
    echo "=== install_dev.sh migratie voor final titel toevoegen ==="
    python3 - <<'PY2034'
from pathlib import Path

p = Path("scripts/install_dev.sh")
s = p.read_text(encoding="utf-8")
marker = "Config migreren naar final titel"

if marker not in s:
    insert = r'''
echo "[4b/8] Config migreren naar final titel"
export CONFIG_DIR APP_DIR
python3 - <<'PIVIEWER_CONFIG_MIGRATION_PY'
import json
import os
from pathlib import Path

cfg_dir = Path(os.environ.get("CONFIG_DIR", "/etc/piviewer-dev"))
app_dir = Path(os.environ.get("APP_DIR", "/opt/piviewer-dev"))
cfg_path = cfg_dir / "piviewer.json"
version_file = app_dir / "VERSION"

try:
    data = json.loads(cfg_path.read_text(encoding="utf-8"))

    try:
        data["version"] = version_file.read_text(encoding="utf-8").strip()
    except Exception:
        data["version"] = "PiViewer 2034"

    data.setdefault("web", {})
    current_title = str(data["web"].get("title") or "").strip()
    forced_title = str(os.environ.get("PIVIEWER_WEB_TITLE", "")).strip()

    if forced_title:
        data["web"]["title"] = forced_title
    elif not current_title or current_title.lower() in (
        "piviewer dev",
        "piviewer-dev",
        "piviewer development",
        "piviewer test",
    ):
        data["web"]["title"] = "PiViewer final"

    if isinstance(data.get("updates"), dict):
        data["updates"].pop("web_update", None)
    data.pop("web_update", None)

    cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Config migratie OK; webtitel=" + str(data.get("web", {}).get("title")))
except Exception as exc:
    print("WAARSCHUWING: config migratie mislukt:", exc)
PIVIEWER_CONFIG_MIGRATION_PY
'''
    needle = 'echo "[5/8] systemd-service installeren"\n'
    if needle not in s:
        raise SystemExit("FOUT: plek voor configmigratie niet gevonden in scripts/install_dev.sh")
    s = s.replace(needle, insert + "\n" + needle, 1)

p.write_text(s, encoding="utf-8")
print("Patch 2034 OK")
PY2034
    PATCH_CODE=$?
    echo "PATCH_CODE=${PATCH_CODE}"
    if [ "${PATCH_CODE}" -ne 0 ]; then
      result_code=4
    fi
  fi

  if [ "${result_code}" -eq 0 ]; then
    echo
    echo "=== config voorbeeld: final titel ==="
    python3 - <<'PY2034CFG'
import json
from pathlib import Path
p = Path("config/piviewer.example.json")
data = json.loads(p.read_text(encoding="utf-8"))
data["version"] = "PiViewer 2034"
data.setdefault("web", {})
data["web"]["title"] = "PiViewer final"
if isinstance(data.get("updates"), dict):
    data["updates"].pop("web_update", None)
data.pop("web_update", None)
p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("Config voorbeeld OK; webtitel=PiViewer final")
PY2034CFG

    echo
    echo "=== Controle: web.py gebruikt configtitel met fallback final ==="
    grep -n "app_title.*PiViewer final" app/web.py || true
    grep -n "<header><h1>{esc(app_title)}</h1>" app/web.py || true

    echo
    echo "=== Syntax controleren ==="
    python3 -m py_compile app/*.py
    PY_CODE=$?
    echo "PY_CODE=${PY_CODE}"
    if [ "${PY_CODE}" -ne 0 ]; then
      result_code=5
    fi
  fi

  if [ "${result_code}" -eq 0 ]; then
    echo
    echo "=== Release ZIP bouwen ==="
    mkdir -p releases updates
    rm -f "releases/PiViewer_${VERSION}.zip" "releases/PiViewer_${VERSION}.zip.sha256"
    cd ..
    rm -rf "PiViewer_${VERSION}"
    rsync -a --delete \
      --exclude='.git' \
      --exclude='releases/PiViewer_*.zip' \
      --exclude='releases/PiViewer_*.zip.sha256' \
      "PiViewer-pidev-2030/" "PiViewer_${VERSION}/"
    zip -qr "PiViewer_${VERSION}.zip" "PiViewer_${VERSION}"
    mv "PiViewer_${VERSION}.zip" "PiViewer-pidev-2030/releases/PiViewer_${VERSION}.zip"
    cd "PiViewer-pidev-2030/releases"
    sha256sum "PiViewer_${VERSION}.zip" > "PiViewer_${VERSION}.zip.sha256"
    ZIP_SHA="$(sha256sum "PiViewer_${VERSION}.zip" | awk '{print $1}')"
    sha256sum -c "PiViewer_${VERSION}.zip.sha256"
    SHA_CODE=$?
    echo "SHA_CODE=${SHA_CODE}"
    cd ..
    if [ "${SHA_CODE}" -ne 0 ]; then
      result_code=6
    fi
  fi

  if [ "${result_code}" -eq 0 ]; then
    echo
    echo "=== updates/index.json schrijven ==="
    cat > updates/index.json <<JSON
{
  "project": "PiViewer",
  "version": "PiViewer ${VERSION}",
  "latest": ${VERSION},
  "version_number": ${VERSION},
  "channel": "stable",
  "minimum_device": "Raspberry Pi 2",
  "check_interval_hours": 24,
  "zip_url": "https://raw.githubusercontent.com/Techraym/PiViewer/main/releases/PiViewer_${VERSION}.zip",
  "sha256_url": "https://raw.githubusercontent.com/Techraym/PiViewer/main/releases/PiViewer_${VERSION}.zip.sha256",
  "sha256": "${ZIP_SHA}",
  "release_date": "2026-08-04",
  "notes": "PiViewer 2034: bestaande configs met PiViewer Dev worden bij installatie automatisch gemigreerd naar PiViewer final. PiDev kan lokaal met PIVIEWER_WEB_TITLE=PiViewer Dev blijven testen."
}
JSON

    echo
    echo "=== Git commit maken ==="
    git add -A VERSION scripts/install_dev.sh config/piviewer.example.json updates/index.json scripts/build_2034_final_title_migration_on_pidev.sh
    git add -f "releases/PiViewer_${VERSION}.zip" "releases/PiViewer_${VERSION}.zip.sha256"
    git status --short
    git commit -m "Release PiViewer 2034 force final title migration"
    COMMIT_CODE=$?
    echo "COMMIT_CODE=${COMMIT_CODE}"
    if [ "${COMMIT_CODE}" -ne 0 ]; then
      echo "Geen commit gemaakt of commit mislukt."
    fi

    echo
    echo "=== Push naar GitHub ==="
    git push origin main
    PUSH_CODE=$?
    echo "PUSH_CODE=${PUSH_CODE}"
    if [ "${PUSH_CODE}" -ne 0 ]; then
      result_code=7
    fi
  fi

  if [ "${result_code}" -eq 0 ]; then
    echo
    echo "=== Online controle ==="
    sleep 4
    curl -I "https://raw.githubusercontent.com/Techraym/PiViewer/main/releases/PiViewer_${VERSION}.zip?t=$(date +%s)" | head -n 8
    curl -fsSL "https://raw.githubusercontent.com/Techraym/PiViewer/main/updates/index.json?t=$(date +%s)" | python3 -m json.tool
  fi

  echo
  echo "RESULT_CODE=${result_code}"
  echo "Script klaar. SSH blijft open."
fi
