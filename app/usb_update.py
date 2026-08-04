import os
import re
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

STATE_DIR = Path('/var/lib/piviewer-dev')
UPDATE_MARKER = STATE_DIR / 'usb-update-in-progress'
UPDATE_LOG = Path('/var/log/piviewer-dev/usb-update.log')
STATUS_SCREEN = Path('/opt/piviewer-dev/app/update_status_screen.py')


def cleanup_stale_update_state(logger=None, force: bool = True) -> None:
    """Ruim een achtergebleven USB update-lock op bij een normale start.

    Tijdens een echte auto-update is piviewer-dev normaal gesproken gestopt.
    Als de service opnieuw start en deze marker nog bestaat, is het in de praktijk
    een stale lock die de status op updating kan laten hangen.
    """
    try:
        if UPDATE_MARKER.exists():
            age = time.time() - UPDATE_MARKER.stat().st_mtime
            marker_text = UPDATE_MARKER.read_text(encoding='utf-8', errors='ignore').strip()
            UPDATE_MARKER.unlink()
            if logger:
                logger.warning('Achtergebleven USB update-lock verwijderd bij opstart: %s leeftijd=%.0fs inhoud=%s', UPDATE_MARKER, age, marker_text)
        # Het tijdelijke run-script mag na een update nooit nodig blijven.
        script = STATE_DIR / 'run-usb-update.sh'
        if script.exists():
            script.unlink()
            if logger:
                logger.info('Achtergebleven USB update-script verwijderd bij opstart: %s', script)
    except Exception as exc:
        if logger:
            logger.warning('USB update cleanup bij opstart mislukt: %s', exc)



def release_screen_for_update(logger=None) -> None:
    """Stop actieve viewers/spelers zodat het updatevenster direct zichtbaar wordt.

    Zonder dit blijft mpv of de framebuffer-slideshow het scherm verversen en zie je
    het updatevenster pas heel kort vlak voordat systemd de service stopt.
    """
    commands = [
        ['pkill', '-f', 'framebuffer_slideshow_runner.py'],
        ['pkill', '-f', 'fbi_slideshow_runner.py'],
        ['pkill', '-f', 'mpv'],
        ['pkill', '-f', 'streamlink'],
        ['killall', 'fbi'],
    ]
    for cmd in commands:
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        except Exception:
            pass
    if logger:
        logger.warning('Actieve speler/viewer gestopt zodat USB update-status direct zichtbaar is')


def show_update_status(title: str, current_version: str = '', new_version: str = '', zip_path: Optional[Path] = None, message: str = '') -> None:
    """Toon een update-status direct op HDMI/framebuffer. Fouten zijn niet fataal."""
    try:
        if not STATUS_SCREEN.exists():
            return
        cmd = [
            'python3', str(STATUS_SCREEN),
            '--title', title,
            '--current', current_version or '',
            '--new', new_version or '',
            '--message', message or 'PiViewer update wordt uitgevoerd.',
        ]
        if zip_path:
            cmd += ['--zip', str(zip_path)]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8, check=False)
    except Exception:
        pass


def version_number(value: str) -> int:
    value = (value or '').strip()
    m = re.search(r'PiViewer\s*(\d+)', value, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r'2\.0\.(\d+)', value)
    if m:
        return 2000 + int(m.group(1))
    m = re.search(r'(\d{4,})', value)
    if m:
        return int(m.group(1))
    return 0


def _zip_version(zip_path: Path) -> Tuple[int, str]:
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            candidates = [name for name in zf.namelist() if name.endswith('/VERSION') or name == 'VERSION']
            if not candidates:
                return 0, ''
            name = sorted(candidates, key=len)[0]
            text = zf.read(name).decode('utf-8', errors='ignore').strip()
            return version_number(text), text
    except Exception:
        return 0, ''


def _find_update_zips(mounts: Iterable[str]):
    for raw in mounts:
        root = Path(raw)
        if not root.exists():
            continue
        try:
            for item in root.glob('*.zip'):
                yield item
            for folder in ('PiViewer_Update', 'PiViewer_Updates', 'PiViewer', 'updates'):
                p = root / folder
                if p.exists():
                    for item in p.glob('*.zip'):
                        yield item
        except OSError:
            continue


def _find_best_update(mounts: Iterable[str], current_number: int) -> Optional[Tuple[Path, int, str]]:
    best: Optional[Tuple[Path, int, str]] = None
    for zip_path in _find_update_zips(mounts):
        num, text = _zip_version(zip_path)
        if num <= current_number:
            continue
        if best is None or num > best[1]:
            best = (zip_path, num, text)
    return best


def _spawn_installer(zip_path: Path, logger, current_version: str = '', new_version: str = '') -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    UPDATE_LOG.parent.mkdir(parents=True, exist_ok=True)
    show_update_status('PiViewer update gevonden', current_version, new_version, zip_path, 'Een hogere PiViewer-versie staat op de USB-stick. De update wordt voorbereid.')
    tmp = Path('/tmp/piviewer-usb-auto-update')
    script = STATE_DIR / 'run-usb-update.sh'
    content = f'''#!/usr/bin/env bash
set -euo pipefail
exec >> "{UPDATE_LOG}" 2>&1
echo "===== USB AUTO UPDATE START $(date) ====="
echo "ZIP: {zip_path}"
python3 "{STATUS_SCREEN}" --title "PiViewer wordt bijgewerkt" --current "{current_version}" --new "{new_version}" --zip "{zip_path}" --message "Updatebestand wordt gekopieerd en uitgepakt." || true
rm -rf "{tmp}"
mkdir -p "{tmp}"
cp "{zip_path}" "{tmp}/update.zip"
python3 "{STATUS_SCREEN}" --title "PiViewer wordt bijgewerkt" --current "{current_version}" --new "{new_version}" --zip "{zip_path}" --message "Updatebestand wordt uitgepakt." || true
unzip -o "{tmp}/update.zip" -d "{tmp}"
cd "{tmp}"/PiViewer_*
python3 "{STATUS_SCREEN}" --title "PiViewer wordt geïnstalleerd" --current "{current_version}" --new "{new_version}" --zip "{zip_path}" --message "Nieuwe bestanden worden geplaatst. Even geduld." || true
echo "Installatiemap: $(pwd)"
if [ -f scripts/install_dev.sh ]; then
  bash scripts/install_dev.sh
elif [ -f scripts/install.sh ]; then
  bash scripts/install.sh
else
  echo "Geen installatiescript gevonden"
  exit 1
fi
rm -rf "{tmp}"
rm -f "{UPDATE_MARKER}"
python3 "/opt/piviewer-dev/app/update_status_screen.py" --title "PiViewer update klaar" --new "{new_version}" --message "De update is klaar. PiViewer wordt nu nogmaals herstart zodat de viewer schoon opnieuw start." || true
echo "Eindherstart van piviewer-dev.service wordt uitgevoerd zodat update-status/foto-viewer niet blijft hangen."
sleep 2
systemctl restart piviewer-dev.service || true
echo "===== USB AUTO UPDATE DONE $(date) ====="
'''
    script.write_text(content, encoding='utf-8')
    os.chmod(script, 0o755)
    UPDATE_MARKER.write_text(str(zip_path), encoding='utf-8')
    if logger:
        logger.warning('USB Auto Update gestart vanaf %s; log: %s', zip_path, UPDATE_LOG)
    subprocess.Popen(['bash', '-c', f'sleep 0.5; sudo bash "{script}"'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def check_usb_auto_update(config: Dict, logger, mounts, current_version: str) -> bool:
    settings = config.get('usb_update', {})
    if not settings.get('enabled', True):
        return False
    if UPDATE_MARKER.exists():
        try:
            age = time.time() - UPDATE_MARKER.stat().st_mtime
            if age < 120:
                if logger:
                    logger.info('USB update-lock aanwezig; auto-update is vermoedelijk nog bezig: %s leeftijd=%.0fs', UPDATE_MARKER, age)
                return True
            UPDATE_MARKER.unlink()
            if logger:
                logger.warning('Oude USB update-lock verwijderd tijdens update-check: %s leeftijd=%.0fs', UPDATE_MARKER, age)
        except Exception as exc:
            if logger:
                logger.warning('USB update-lock kon niet worden gecontroleerd: %s', exc)
            return True

    current = version_number(current_version)
    best = _find_best_update(mounts, current)
    if not best:
        return False

    zip_path, new_num, new_text = best
    if logger:
        logger.warning('Hogere PiViewer-versie gevonden op USB: huidig=%s (%s), nieuw=%s (%s)', current_version, current, new_text, new_num)
    release_screen_for_update(logger)
    _spawn_installer(zip_path, logger, current_version, new_text)
    return True
