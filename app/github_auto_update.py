#!/usr/bin/env python3
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

APP_DIR = Path("/opt/piviewer-dev")
VERSION_FILE = APP_DIR / "VERSION"
INDEX_URL = "https://raw.githubusercontent.com/Techraym/PiViewer/main/updates/index.json"

STATE_FILE = Path("/var/lib/piviewer-dev/github-update-last-check.json")
LOCK_FILE = Path("/var/lib/piviewer-dev/github-update-in-progress")
DOWNLOAD_DIR = Path("/var/lib/piviewer-dev/github-downloads")
LOG_FILE = Path("/var/log/piviewer-dev/github-update.log")
USER_AGENT = "PiViewer-GitHub-Updater"


def log(message):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp} | {message}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd, check=True):
    log("+ " + " ".join(str(x) for x in cmd))
    return subprocess.run(cmd, check=check)


def read_local_version():
    try:
        text = VERSION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        text = "PiViewer 0"
    m = re.search(r"(\d+)", text)
    return text, int(m.group(1)) if m else 0


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=90) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def install_zip(zip_path, target_version):
    tmp = Path(tempfile.mkdtemp(prefix="piviewer-github-update-"))
    try:
        run(["unzip", "-q", str(zip_path), "-d", str(tmp)])
        expected = tmp / f"PiViewer_{target_version}"
        if expected.is_dir():
            pkg = expected
        else:
            candidates = sorted([p for p in tmp.iterdir() if p.is_dir() and p.name.startswith("PiViewer_")])
            if not candidates:
                raise RuntimeError("Geen PiViewer_* map gevonden in update-ZIP")
            pkg = candidates[-1]

        installer = pkg / "scripts" / "install_dev.sh"
        if not installer.exists():
            raise RuntimeError(f"Installatiescript ontbreekt: {installer}")

        LOCK_FILE.write_text(str(zip_path), encoding="utf-8")

        run(["systemctl", "stop", "piviewer-dev"], check=False)
        run(["pkill", "-f", "mpv"], check=False)
        run(["pkill", "-f", "streamlink"], check=False)
        run(["pkill", "-f", "framebuffer_slideshow_runner.py"], check=False)

        run(["bash", str(installer)])

        try:
            LOCK_FILE.unlink()
        except FileNotFoundError:
            pass

        run(["systemctl", "daemon-reload"], check=False)
        run(["systemctl", "restart", "piviewer-dev"], check=False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    local_name, local_num = read_local_version()
    log(f"GitHub-update controle gestart. Lokaal={local_name} ({local_num})")

    if LOCK_FILE.exists():
        age = int(time.time() - LOCK_FILE.stat().st_mtime)
        if age < 1800:
            log(f"GitHub update-lock aanwezig; update vermoedelijk bezig. Leeftijd={age}s")
            return 0
        log(f"Oude GitHub update-lock verwijderd. Leeftijd={age}s")
        LOCK_FILE.unlink(missing_ok=True)

    try:
        index = fetch_json(INDEX_URL + "?t=" + str(int(time.time())))
    except Exception as exc:
        log(f"GitHub-update index ophalen mislukt: {exc}")
        return 0

    latest = int(index.get("latest") or index.get("version_number") or 0)
    version_name = str(index.get("version") or f"PiViewer {latest}")
    zip_url = str(index.get("zip_url") or "")
    expected_sha = str(index.get("sha256") or "").strip().lower()

    log(f"GitHub-update index: online={version_name} ({latest})")

    STATE_FILE.write_text(json.dumps({
        "last_check": time.strftime("%Y-%m-%d %H:%M:%S"),
        "local_version": local_name,
        "local_number": local_num,
        "online_version": version_name,
        "online_number": latest,
    }, indent=2), encoding="utf-8")

    if latest <= local_num:
        log("Geen hogere GitHub-versie gevonden.")
        return 0

    if not zip_url:
        log("FOUT: zip_url ontbreekt in updates/index.json")
        return 1

    if not expected_sha or len(expected_sha) != 64:
        log("FOUT: geldige sha256 ontbreekt in updates/index.json. Update geweigerd.")
        return 1

    zip_path = DOWNLOAD_DIR / f"PiViewer_{latest}.zip"
    tmp_path = DOWNLOAD_DIR / f"PiViewer_{latest}.zip.tmp"

    log(f"Hogere GitHub-versie gevonden: {local_num} -> {latest}")
    log(f"Download: {zip_url}")

    try:
        download(zip_url + "?t=" + str(int(time.time())), tmp_path)
    except Exception as exc:
        log(f"FOUT: download mislukt: {exc}")
        return 1

    actual_sha = sha256_file(tmp_path)
    log(f"SHA256 verwacht: {expected_sha}")
    log(f"SHA256 berekend: {actual_sha}")

    if actual_sha.lower() != expected_sha:
        tmp_path.unlink(missing_ok=True)
        log("FOUT: SHA256 komt niet overeen. Update geweigerd.")
        return 1

    tmp_path.rename(zip_path)
    log("SHA256 controle OK. Update wordt geïnstalleerd.")

    try:
        install_zip(zip_path, latest)
    except Exception as exc:
        log(f"FOUT tijdens installeren: {exc}")
        try:
            LOCK_FILE.unlink()
        except FileNotFoundError:
            pass
        return 1

    log(f"GitHub-update naar PiViewer {latest} voltooid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
