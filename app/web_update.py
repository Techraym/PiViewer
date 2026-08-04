import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, Optional, Tuple

from usb_update import release_screen_for_update, show_update_status, version_number

STATE_DIR = Path('/var/lib/piviewer-dev')
WEB_UPDATE_DIR = STATE_DIR / 'web-updates'
WEB_UPDATE_MARKER = STATE_DIR / 'web-update-in-progress'
WEB_UPDATE_STATE = STATE_DIR / 'web-update-last-check.json'
WEB_UPDATE_LOG = Path('/var/log/piviewer-dev/web-update.log')
STATUS_SCREEN = Path('/opt/piviewer-dev/app/update_status_screen.py')

DEFAULT_BASE_URL = 'https://raysnijder.nl/rep/piviewer/'
DEFAULT_CHECK_URL = urllib.parse.urljoin(DEFAULT_BASE_URL, 'latest.json')
DEFAULT_FILE_PATTERN = 'PiViewer_{version}.zip'
USER_AGENT = 'PiViewer-WebUpdate/2024'


def cleanup_stale_web_update_state(logger=None) -> None:
    try:
        if WEB_UPDATE_MARKER.exists():
            age = time.time() - WEB_UPDATE_MARKER.stat().st_mtime
            marker_text = WEB_UPDATE_MARKER.read_text(encoding='utf-8', errors='ignore').strip()
            WEB_UPDATE_MARKER.unlink()
            if logger:
                logger.warning('Achtergebleven web update-lock verwijderd bij opstart: %s leeftijd=%.0fs inhoud=%s', WEB_UPDATE_MARKER, age, marker_text)
        script = STATE_DIR / 'run-web-update.sh'
        if script.exists():
            script.unlink()
            if logger:
                logger.info('Achtergebleven web update-script verwijderd bij opstart: %s', script)
    except Exception as exc:
        if logger:
            logger.warning('Web update cleanup bij opstart mislukt: %s', exc)


def _read_state() -> Dict:
    try:
        if WEB_UPDATE_STATE.exists():
            return json.loads(WEB_UPDATE_STATE.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {}


def _write_state(**data) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        current = _read_state()
        current.update(data)
        current['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        tmp = WEB_UPDATE_STATE.with_suffix('.tmp')
        tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding='utf-8')
        tmp.replace(WEB_UPDATE_STATE)
    except Exception:
        pass


def _due(settings: Dict, logger=None) -> bool:
    interval_hours = float(settings.get('interval_hours', 24))
    failure_retry_hours = float(settings.get('failure_retry_hours', 1))
    now = time.time()
    st = _read_state()
    last_success = float(st.get('last_success_ts', 0) or 0)
    last_attempt = float(st.get('last_attempt_ts', 0) or 0)
    last_result = str(st.get('last_result', ''))
    if last_success and now - last_success < interval_hours * 3600:
        if logger:
            logger.info('Web-update controle overgeslagen; laatste succesvolle controle is %.0f minuten geleden', (now - last_success) / 60)
        return False
    if last_result == 'error' and last_attempt and now - last_attempt < failure_retry_hours * 3600:
        if logger:
            logger.info('Web-update controle overgeslagen; laatste fout is %.0f minuten geleden', (now - last_attempt) / 60)
        return False
    return True


def _urlopen(req: urllib.request.Request, timeout: int):
    return urllib.request.urlopen(req, timeout=timeout)


def _url_exists(url: str, timeout: int = 8) -> bool:
    """Controleer of een ZIP online bestaat. HEAD heeft voorkeur; GET Range is fallback."""
    head_req = urllib.request.Request(url, method='HEAD', headers={
        'User-Agent': USER_AGENT,
        'Cache-Control': 'no-cache',
    })
    try:
        with _urlopen(head_req, timeout=timeout) as resp:
            return 200 <= int(resp.status) < 400
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        # Sommige hostingconfiguraties staan HEAD niet toe.
        if exc.code not in (403, 405):
            return False
    except Exception:
        # Probeer nog één keer met GET Range, omdat sommige servers HEAD vreemd afhandelen.
        pass

    get_req = urllib.request.Request(url, headers={
        'User-Agent': USER_AGENT,
        'Cache-Control': 'no-cache',
        'Range': 'bytes=0-0',
    })
    try:
        with _urlopen(get_req, timeout=timeout) as resp:
            return int(resp.status) in (200, 206)
    except urllib.error.HTTPError as exc:
        return exc.code in (200, 206)
    except Exception:
        return False


def _fetch_json(url: str, timeout: int = 10) -> Dict:
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(1024 * 64).decode('utf-8', errors='replace')
        return json.loads(raw)


def _manifest_version(manifest: Dict) -> Tuple[int, str]:
    text = str(manifest.get('version') or manifest.get('name') or '')
    num = int(manifest.get('number') or manifest.get('version_number') or version_number(text) or 0)
    if not text and num:
        text = f'PiViewer {num}'
    return num, text


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


def _download(url: str, target: Path, timeout: int = 60) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix('.download')
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, timeout=timeout) as resp, tmp.open('wb') as out:
        shutil.copyfileobj(resp, out)
    tmp.replace(target)


def _derive_base_url(settings: Dict) -> str:
    base = str(settings.get('base_url') or settings.get('zip_base_url') or '').strip()
    if not base:
        # Compatibel met bestaande 2021/2022-configs die alleen check_url/latest.json bevatten.
        check_url = str(settings.get('check_url') or DEFAULT_CHECK_URL)
        base = urllib.parse.urljoin(check_url, './')
    if not base.endswith('/'):
        base += '/'
    return base


def _candidate_url(base_url: str, pattern: str, version: int) -> str:
    name = pattern.replace('{version}', str(version)).replace('{number}', str(version))
    return urllib.parse.urljoin(base_url, name)


def _find_best_direct_zip(settings: Dict, logger, current_number: int, current_version: str) -> Optional[Tuple[str, int, str]]:
    base_url = _derive_base_url(settings)
    pattern = str(settings.get('file_pattern') or DEFAULT_FILE_PATTERN)
    lookahead = int(settings.get('lookahead_versions', 20))
    timeout = int(settings.get('timeout_seconds', 8))
    start = current_number + 1
    end = current_number + max(1, lookahead)
    best: Optional[Tuple[str, int, str]] = None
    if logger:
        logger.info('Web-ZIP update controle gestart: base_url=%s patroon=%s bereik=%s-%s', base_url, pattern, start, end)
    for num in range(start, end + 1):
        url = _candidate_url(base_url, pattern, num)
        if logger:
            logger.info('Web-ZIP controle: %s', url)
        if _url_exists(url, timeout=timeout):
            best = (url, num, f'PiViewer {num}')
            if logger:
                logger.warning('Online PiViewer ZIP gevonden: %s', url)
    if best:
        return best
    if logger:
        logger.info('Geen hogere PiViewer_XXXX.zip gevonden op domein voor lokale versie %s (%s)', current_version, current_number)
    return None


def _find_manifest_update(settings: Dict, logger, current_number: int, current_version: str) -> Optional[Tuple[str, int, str]]:
    """Fallback voor oude latest.json-flow. Niet meer verplicht, maar blijft bruikbaar."""
    check_url = str(settings.get('check_url') or DEFAULT_CHECK_URL)
    timeout = int(settings.get('timeout_seconds', 10))
    if logger:
        logger.info('Web-update manifest fallback controle gestart: %s', check_url)
    manifest = _fetch_json(check_url, timeout=timeout)
    online_num, online_text = _manifest_version(manifest)
    if logger:
        logger.info('Web-update manifest: huidig=%s (%s), online=%s (%s)', current_version, current_number, online_text, online_num)
    if online_num <= current_number:
        return None
    file_value = manifest.get('zip_url') or manifest.get('url') or manifest.get('file') or 'latest.zip'
    zip_url = urllib.parse.urljoin(check_url, str(file_value))
    return zip_url, online_num, online_text or f'PiViewer {online_num}'


def _spawn_installer(zip_path: Path, logger, current_version: str, new_version: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    WEB_UPDATE_LOG.parent.mkdir(parents=True, exist_ok=True)
    show_update_status('PiViewer web-update gevonden', current_version, new_version, zip_path, 'Er staat een hogere PiViewer-versie klaar op raysnijder.nl. De update wordt voorbereid.')
    tmp = Path('/tmp/piviewer-web-auto-update')
    script = STATE_DIR / 'run-web-update.sh'
    content = f'''#!/usr/bin/env bash
set -euo pipefail
exec >> "{WEB_UPDATE_LOG}" 2>&1
echo "===== WEB AUTO UPDATE START $(date) ====="
echo "ZIP: {zip_path}"
python3 "{STATUS_SCREEN}" --title "PiViewer web-update" --current "{current_version}" --new "{new_version}" --zip "{zip_path}" --message "Updatebestand van raysnijder.nl wordt uitgepakt." || true
rm -rf "{tmp}"
mkdir -p "{tmp}"
cp "{zip_path}" "{tmp}/update.zip"
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
rm -f "{WEB_UPDATE_MARKER}"
python3 "/opt/piviewer-dev/app/update_status_screen.py" --title "PiViewer web-update klaar" --new "{new_version}" --message "De update is klaar. PiViewer wordt schoon opnieuw gestart." || true
echo "Eindherstart van piviewer-dev.service wordt uitgevoerd."
sleep 2
systemctl restart piviewer-dev.service || true
echo "===== WEB AUTO UPDATE DONE $(date) ====="
'''
    script.write_text(content, encoding='utf-8')
    os.chmod(script, 0o755)
    WEB_UPDATE_MARKER.write_text(str(zip_path), encoding='utf-8')
    if logger:
        logger.warning('Web Auto Update gestart vanaf %s; log: %s', zip_path, WEB_UPDATE_LOG)
    subprocess.Popen(['bash', '-c', f'sleep 0.5; bash "{script}"'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def check_web_auto_update(config: Dict, logger, current_version: str) -> bool:
    updates = config.get('updates', {}) if isinstance(config.get('updates', {}), dict) else {}
    settings = dict(config.get('web_update', {}) if isinstance(config.get('web_update', {}), dict) else {})
    settings.update(updates.get('web_update', {}) if isinstance(updates.get('web_update', {}), dict) else {})

    if not settings:
        settings = {
            'enabled': True,
            'auto_install': True,
            'base_url': DEFAULT_BASE_URL,
            'file_pattern': DEFAULT_FILE_PATTERN,
            'interval_hours': 24,
            'lookahead_versions': 20,
        }
    # Vanaf PiViewer 2024 is direct PiViewer_XXXX.zip scannen de standaard, ook als
    # een oude config nog check_url=latest.json bevat.
    settings.setdefault('base_url', _derive_base_url(settings))
    settings.setdefault('file_pattern', DEFAULT_FILE_PATTERN)
    settings.setdefault('lookahead_versions', 20)
    settings.setdefault('direct_zip_scan', True)
    settings.setdefault('manifest_fallback', False)

    if not settings.get('enabled', True):
        return False
    if not settings.get('auto_install', True):
        return False

    if WEB_UPDATE_MARKER.exists():
        try:
            age = time.time() - WEB_UPDATE_MARKER.stat().st_mtime
            if age < 180:
                if logger:
                    logger.info('Web update-lock aanwezig; auto-update is vermoedelijk nog bezig: %s leeftijd=%.0fs', WEB_UPDATE_MARKER, age)
                return True
            WEB_UPDATE_MARKER.unlink()
            if logger:
                logger.warning('Oude web update-lock verwijderd tijdens update-check: %s leeftijd=%.0fs', WEB_UPDATE_MARKER, age)
        except Exception as exc:
            if logger:
                logger.warning('Web update-lock kon niet worden gecontroleerd: %s', exc)
            return True

    if not _due(settings, logger):
        return False

    current_num = version_number(current_version)
    _write_state(last_attempt_ts=time.time(), last_result='checking', update_mode='direct_zip_scan', base_url=settings.get('base_url'), file_pattern=settings.get('file_pattern'))

    try:
        found: Optional[Tuple[str, int, str]] = None
        if settings.get('direct_zip_scan', True):
            found = _find_best_direct_zip(settings, logger, current_num, current_version)
        if not found and settings.get('manifest_fallback', False):
            try:
                found = _find_manifest_update(settings, logger, current_num, current_version)
            except Exception as exc:
                if logger:
                    logger.warning('Manifest fallback mislukt: %s', exc)

        if not found:
            _write_state(last_success_ts=time.time(), last_result='ok', online_version=current_version, online_number=current_num, update_available=False)
            return False

        zip_url, online_num, online_text = found
        target = WEB_UPDATE_DIR / f'PiViewer_{online_num}.zip'
        if logger:
            logger.warning('Hogere PiViewer-versie gevonden op web: huidig=%s (%s), nieuw=%s (%s), url=%s', current_version, current_num, online_text, online_num, zip_url)
        release_screen_for_update(logger)
        show_update_status('PiViewer web-update gevonden', current_version, online_text, None, 'Nieuwe ZIP-versie gevonden op raysnijder.nl. Het updatebestand wordt gedownload.')
        _download(zip_url, target, timeout=int(settings.get('download_timeout_seconds', 120)))
        zip_num, zip_text = _zip_version(target)
        if zip_num <= current_num:
            raise RuntimeError(f'Gedownloade ZIP bevat geen hogere versie: {zip_text} ({zip_num})')
        _write_state(last_success_ts=time.time(), last_result='update_started', downloaded_zip=str(target), online_version=zip_text, online_number=zip_num, update_available=True, zip_url=zip_url)
        _spawn_installer(target, logger, current_version, zip_text or online_text)
        return True
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, RuntimeError) as exc:
        _write_state(last_result='error', last_error=str(exc), last_error_ts=time.time())
        if logger:
            logger.warning('Web-update controle mislukt: %s', exc)
        return False
