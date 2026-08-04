#!/usr/bin/env bash
set +e

WORK="${HOME}/PiViewer-pidev-2030"
VERSION="2033"
VERSION_TEXT="PiViewer 2033"
REPO="git@github.com:Techraym/PiViewer.git"

log(){ echo "$*"; }

log "=== PiViewer 2033 WiFi-profielnaam release build helper ==="
log "Werkmap: ${WORK}"

if [ ! -d "${WORK}/.git" ]; then
  log "FOUT: git werkmap niet gevonden: ${WORK}"
  ls -ld "${HOME}"/PiViewer* 2>/dev/null
  log "RESULT_CODE=1"
  exit 1
fi

cd "${WORK}"

log
log "=== GitHub SSH controleren ==="
git remote set-url origin "${REPO}"
SSH_TEST="$(ssh -T git@github.com 2>&1 || true)"
echo "${SSH_TEST}"
if ! echo "${SSH_TEST}" | grep -qiE "successfully authenticated|Hi "; then
  log "FOUT: GitHub SSH werkt niet vanaf PiDev."
  log "RESULT_CODE=2"
  exit 2
fi

log
log "=== Lokale wijzigingen opruimen en main ophalen ==="
git rebase --abort 2>/dev/null || true
git reset --hard HEAD
git clean -fd
git fetch origin main
git reset --hard origin/main
PULL_CODE=$?
log "PULL_CODE=${PULL_CODE}"
if [ "${PULL_CODE}" -ne 0 ]; then
  log "FOUT: GitHub main ophalen mislukt."
  log "RESULT_CODE=3"
  exit 3
fi

log
log "=== Patch 2033 uitvoeren ==="
python3 - <<'PY2033'
from pathlib import Path
import json

Path("VERSION").write_text("PiViewer 2033\n", encoding="utf-8")

p = Path("app/wifi.py")
s = p.read_text(encoding="utf-8")
old = """def _nmcli_configure_wifi_profile(ssid: str, password: str) -> Tuple[bool, str]:
    con_name = f'PiViewer WiFi {ssid}'
    if not _nmcli_connection_exists(con_name):
"""
new = """def _nmcli_configure_wifi_profile(ssid: str, password: str) -> Tuple[bool, str]:
    # Gebruik de SSID ook als NetworkManager-profielnaam.
    # Daardoor staat een WiFi.txt met SSID=GAST opgeslagen als profiel 'GAST',
    # niet als 'PiViewer WiFi GAST'.
    con_name = ssid
    legacy_name = f'PiViewer WiFi {ssid}'
    if not _nmcli_connection_exists(con_name) and _nmcli_connection_exists(legacy_name):
        _run(['nmcli', 'connection', 'modify', legacy_name, 'connection.id', con_name], timeout=10)

    if not _nmcli_connection_exists(con_name):
"""
if old in s:
    s = s.replace(old, new)
elif "legacy_name = f'PiViewer WiFi {ssid}'" in s and "con_name = ssid" in s:
    pass
else:
    raise SystemExit("FOUT: verwacht WiFi-profielblok niet gevonden in app/wifi.py")
p.write_text(s, encoding="utf-8")

p = Path("config/piviewer.example.json")
data = json.loads(p.read_text(encoding="utf-8"))
data["version"] = "PiViewer 2033"
data.setdefault("web", {})
data["web"]["title"] = "PiViewer final"
if isinstance(data.get("updates"), dict):
    data["updates"].pop("web_update", None)
data.pop("web_update", None)
p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

print("Patch 2033 OK")
PY2033
PATCH_CODE=$?
log "PATCH_CODE=${PATCH_CODE}"
if [ "${PATCH_CODE}" -ne 0 ]; then
  log "FOUT: patch mislukt."
  log "RESULT_CODE=4"
  exit 4
fi

log
log "=== Veiligheidscontrole: geen WiFi-wachtwoord in repo ==="
if grep -R "PASSWORD=" -n . --exclude-dir=.git --exclude='*.log' --exclude='*.md' 2>/dev/null | grep -v 'WiFi.txt' | grep -v 'PASSWORD='; then
  log "FOUT: mogelijke WiFi-password-regel gevonden in repo. Commit geweigerd."
  log "RESULT_CODE=5"
  exit 5
else
  log "OK: geen concrete WiFi-wachtwoordregel gevonden."
fi

log
log "=== Syntax controleren ==="
python3 -m py_compile app/*.py
PY_CODE=$?
log "PY_CODE=${PY_CODE}"
if [ "${PY_CODE}" -ne 0 ]; then
  log "FOUT: Python syntaxcontrole mislukt."
  log "RESULT_CODE=6"
  exit 6
fi

log
log "=== Release ZIP bouwen ==="
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
log "SHA_CODE=${SHA_CODE}"
cd ..
if [ "${SHA_CODE}" -ne 0 ]; then
  log "FOUT: SHA controle mislukt."
  log "RESULT_CODE=7"
  exit 7
fi

log
log "=== updates/index.json schrijven ==="
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
  "notes": "PiViewer 2033: WiFi.txt blijft de WiFi instellen. Bedraad blijft voorkeur bij netwerkkabel. NetworkManager-profielnaam is nu gelijk aan de SSID, bijvoorbeeld GAST. Geen WiFi-wachtwoorden in de release."
}
JSON

log
log "=== Commit en push ==="
git add VERSION app/wifi.py config/piviewer.example.json updates/index.json scripts/build_2033_wifi_profile_name_on_pidev.sh
git add -f "releases/PiViewer_${VERSION}.zip" "releases/PiViewer_${VERSION}.zip.sha256"
git status --short
git commit -m "Release PiViewer 2033 WiFi profile name equals SSID"
COMMIT_CODE=$?
log "COMMIT_CODE=${COMMIT_CODE}"
if [ "${COMMIT_CODE}" -ne 0 ]; then
  log "Geen commit gemaakt of commit mislukt."
fi

git push origin main
PUSH_CODE=$?
log "PUSH_CODE=${PUSH_CODE}"
if [ "${PUSH_CODE}" -ne 0 ]; then
  log "FOUT: push mislukt."
  log "RESULT_CODE=8"
  exit 8
fi

log
log "=== Online controle ==="
sleep 4
curl -I "https://raw.githubusercontent.com/Techraym/PiViewer/main/releases/PiViewer_${VERSION}.zip?t=$(date +%s)" | head -n 8
curl -fsSL "https://raw.githubusercontent.com/Techraym/PiViewer/main/updates/index.json?t=$(date +%s)" | python3 -m json.tool

log
log "RESULT_CODE=0"
log "Script klaar. SSH blijft open."
