#!/usr/bin/env bash
set +e

WORK="${HOME}/PiViewer-pidev-2030"
VERSION="2031"
VERSION_TEXT="PiViewer 2031"
REPO="git@github.com:Techraym/PiViewer.git"

log_step() {
  echo
  echo "=== $1 ==="
}

echo "=== PiViewer 2031 final release build helper v2 ==="
echo "Werkmap: ${WORK}"

if [ ! -d "${WORK}/.git" ]; then
  echo "FOUT: git werkmap niet gevonden: ${WORK}"
  echo "Beschikbare PiViewer mappen:"
  ls -ld "${HOME}"/PiViewer* 2>/dev/null
  echo "RESULT_CODE=1"
  exit 1
fi

cd "${WORK}" || exit 1

log_step "GitHub SSH controleren"
git remote set-url origin "${REPO}"
SSH_TEST="$(ssh -T git@github.com 2>&1 || true)"
echo "${SSH_TEST}"
if ! echo "${SSH_TEST}" | grep -qiE "successfully authenticated|Hi "; then
  echo "FOUT: GitHub SSH werkt niet vanaf PiDev."
  echo "RESULT_CODE=2"
  exit 2
fi

log_step "Lokale mislukte wijzigingen opruimen"
git rebase --abort 2>/dev/null || true
git reset --hard HEAD
git clean -fd

log_step "Laatste GitHub main ophalen"
git fetch origin main
git reset --hard origin/main
PULL_CODE=$?
echo "PULL_CODE=${PULL_CODE}"
if [ "${PULL_CODE}" -ne 0 ]; then
  echo "FOUT: GitHub main ophalen mislukt."
  echo "RESULT_CODE=3"
  exit 3
fi

log_step "Patchbestand maken"
cat > /tmp/piviewer_2031_patch.py <<'PYHELPER'
from pathlib import Path
import json

VERSION_TEXT = "PiViewer 2031"

# VERSION
Path("VERSION").write_text(VERSION_TEXT + "\n", encoding="utf-8")

# main.py: raysnijder.nl/web_update eruit
p = Path("app/main.py")
s = p.read_text(encoding="utf-8")
s = s.replace("from web_update import check_web_auto_update, cleanup_stale_web_update_state\n", "")
s = s.replace("    cleanup_stale_web_update_state(logger)\n", "")
web_block = '''            # Web-update is een extra updatekanaal. USB-update houdt altijd prioriteit.
            if check_web_auto_update(config, logger, APP_VERSION):
                state.update(status="updating", message="Hogere PiViewer-versie op raysnijder.nl gevonden; web-update gestart")
                time.sleep(30)
                continue

'''
s = s.replace(web_block, "")
p.write_text(s, encoding="utf-8")

# web_update.py verwijderen
Path("app/web_update.py").unlink(missing_ok=True)

# web.py: titel uit config, standaard PiViewer final
p = Path("app/web.py")
s = p.read_text(encoding="utf-8")
if "app_title = str(cfg_for_title.get('web', {}).get('title') or 'PiViewer final')" not in s:
    old = """            def layout(self, title: str, content: str, query: Dict[str, List[str]] = None) -> str:\n                query = query or {}\n                return f'''<!doctype html>\n"""
    new = """            def layout(self, title: str, content: str, query: Dict[str, List[str]] = None) -> str:\n                query = query or {}\n                try:\n                    cfg_for_title = load_config()\n                    app_title = str(cfg_for_title.get('web', {}).get('title') or 'PiViewer final')\n                except Exception:\n                    app_title = 'PiViewer final'\n                return f'''<!doctype html>\n"""
    if old not in s:
        raise SystemExit("FOUT: layout-blok niet gevonden in app/web.py")
    s = s.replace(old, new)
s = s.replace("<title>{esc(title)} - PiViewer Dev</title>", "<title>{esc(title)} - {esc(app_title)}</title>")
s = s.replace("<title>{esc(title)} - PiViewer final</title>", "<title>{esc(title)} - {esc(app_title)}</title>")
s = s.replace("<header><h1>PiViewer Dev</h1>{self.nav()}</header>", "<header><h1>{esc(app_title)}</h1>{self.nav()}</header>")
s = s.replace("<header><h1>PiViewer final</h1>{self.nav()}</header>", "<header><h1>{esc(app_title)}</h1>{self.nav()}</header>")
p.write_text(s, encoding="utf-8")

# config voorbeeld: final titel, geen web_update
p = Path("config/piviewer.example.json")
data = json.loads(p.read_text(encoding="utf-8"))
data["version"] = VERSION_TEXT
data.setdefault("web", {})
data["web"]["title"] = "PiViewer final"
if isinstance(data.get("updates"), dict):
    data["updates"].pop("web_update", None)
data.pop("web_update", None)
p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

# install_dev.sh: config migreren, web-update resten opruimen, reboot na GitHub-update
p = Path("scripts/install_dev.sh")
s = p.read_text(encoding="utf-8")
needle = '''echo "[8/8] Klaar"
echo "Status: sudo systemctl status ${SERVICE_NAME}"
echo "Logs:   journalctl -u ${SERVICE_NAME} -f"
echo "Config: ${CONFIG_DIR}/piviewer.json"
echo "Web:    http://<ip-van-pi>:8080"
'''
insert = '''echo "[8/8] Config migreren"
python3 - <<'PIVIEWER_CONFIG_MIGRATE'
import json
from pathlib import Path
import os

cfg_path = Path(os.environ.get("PIVIEWER_CONFIG_PATH", "/etc/piviewer-dev/piviewer.json"))
try:
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    data["version"] = "PiViewer 2031"
    data.setdefault("web", {})
    old_title = str(data["web"].get("title") or "").strip()
    if not old_title or old_title.lower() == "piviewer dev":
        data["web"]["title"] = "PiViewer final"
    if isinstance(data.get("updates"), dict):
        data["updates"].pop("web_update", None)
    data.pop("web_update", None)
    cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")
    print("Config migratie OK")
except Exception as exc:
    print("WAARSCHUWING: config migratie mislukt:", exc)
PIVIEWER_CONFIG_MIGRATE

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

echo "[8/8] Klaar"
echo "Status: sudo systemctl status ${SERVICE_NAME}"
echo "Logs:   journalctl -u ${SERVICE_NAME} -f"
echo "Config: ${CONFIG_DIR}/piviewer.json"
echo "Web:    http://<ip-van-pi>:8080"
'''
if "reboot-after-github-update" not in s:
    if needle not in s:
        raise SystemExit("FOUT: eindblok niet gevonden in scripts/install_dev.sh")
    s = s.replace(needle, insert)
p.write_text(s, encoding="utf-8")

# github_auto_update.py: reboot na succesvolle GitHub update
p = Path("app/github_auto_update.py")
s = p.read_text(encoding="utf-8")
old = '''    log(f"GitHub-update naar PiViewer {latest} voltooid.")
    return 0
'''
new = '''    log(f"GitHub-update naar PiViewer {latest} voltooid.")
    reboot_flag = Path("/var/lib/piviewer-dev/reboot-after-github-update")
    if not reboot_flag.exists():
        log("GitHub-update voltooid; Raspberry Pi reboot wordt gestart.")
        try:
            run(["systemctl", "reboot"], check=False)
        except Exception as exc:
            log(f"WAARSCHUWING: reboot starten mislukt: {exc}")
    return 0
'''
if "reboot-after-github-update" not in s:
    if old not in s:
        raise SystemExit("FOUT: voltooid-blok niet gevonden in app/github_auto_update.py")
    s = s.replace(old, new)
p.write_text(s, encoding="utf-8")

print("Patch OK")
PYHELPER

log_step "Patch uitvoeren"
python3 /tmp/piviewer_2031_patch.py
PATCH_CODE=$?
echo "PATCH_CODE=${PATCH_CODE}"
if [ "${PATCH_CODE}" -ne 0 ]; then
  echo "FOUT: patch mislukt."
  echo "RESULT_CODE=4"
  exit 4
fi

log_step "web_update.py uit git verwijderen"
git rm -f app/web_update.py 2>/dev/null || true

log_step "Syntax controleren"
python3 -m py_compile app/*.py
PY_CODE=$?
echo "PY_CODE=${PY_CODE}"
if [ "${PY_CODE}" -ne 0 ]; then
  echo "FOUT: Python syntaxcontrole mislukt."
  echo "RESULT_CODE=5"
  exit 5
fi

log_step "Release ZIP bouwen"
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
  echo "FOUT: SHA controle mislukt."
  echo "RESULT_CODE=6"
  exit 6
fi

log_step "updates/index.json schrijven"
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
  "notes": "PiViewer 2031: officiele webtitel is PiViewer final. GitHub-updates rebooten automatisch na installatie. raysnijder.nl/web-update is verwijderd."
}
JSON

log_step "Git commit maken"
git add -A
git add -f "releases/PiViewer_${VERSION}.zip" "releases/PiViewer_${VERSION}.zip.sha256"
git status --short
git commit -m "Release PiViewer 2031 final title no web update reboot after GitHub update"
COMMIT_CODE=$?
echo "COMMIT_CODE=${COMMIT_CODE}"

log_step "Push naar GitHub"
git push origin main
PUSH_CODE=$?
echo "PUSH_CODE=${PUSH_CODE}"
if [ "${PUSH_CODE}" -ne 0 ]; then
  echo "FOUT: push mislukt."
  echo "RESULT_CODE=7"
  exit 7
fi

log_step "Online controle"
sleep 4
curl -I "https://raw.githubusercontent.com/Techraym/PiViewer/main/releases/PiViewer_${VERSION}.zip?t=$(date +%s)" | head -n 8
curl -fsSL "https://raw.githubusercontent.com/Techraym/PiViewer/main/updates/index.json?t=$(date +%s)" | python3 -m json.tool

echo
echo "RESULT_CODE=0"
echo "Script klaar. SSH blijft open."
