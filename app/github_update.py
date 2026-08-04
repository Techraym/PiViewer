import hashlib
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

try:
    from usb_update import release_screen_for_update, show_update_status, version_number
except Exception:
    release_screen_for_update = None
    show_update_status = None
    def version_number(value):
        import re
        nums = re.findall(r"\d+", str(value or ""))
        return int(nums[-1]) if nums else 0

STATE_DIR = Path('/var/lib/piviewer-dev')
GITHUB_UPDATE_DIR = STATE_DIR / 'github-updates'
GITHUB_UPDATE_MARKER = STATE_DIR / 'github-update-in-progress'
GITHUB_UPDATE_STATE = STATE_DIR / 'github-update-last-check.json'
GITHUB_UPDATE_LOG = Path('/var/log/piviewer-dev/github-update.log')
STATUS_SCREEN = Path('/opt/piviewer-dev/app/update_status_screen.py')

DEFAULT_INDEX_URL = 'https://raw.githubusercontent.com/Techraym/PiViewer/main/updates/index.json'
DEFAULT_RELEASE_BASE_URL = 'https://raw.githubusercontent.com/Techraym/PiViewer/main/releases/'
DEFAULT_FILE_PATTERN = 'PiViewer_{version}.zip'
USER_AGENT = 'PiViewer-GitHubUpdate/2029'
_STARTUP_CHECK_USED = False


def cleanup_stale_github_update_state(logger=None):
    try:
        if GITHUB_UPDATE_MARKER.exists():
            age = time.time() - GITHUB_UPDATE_MARKER.stat().st_mtime
            marker_text = GITHUB_UPDATE_MARKER.read_text(encoding='utf-8', errors='ignore').strip()
            if age > 60:
                GITHUB_UPDATE_MARKER.unlink()
                if logger:
                    logger.warning('Achtergebleven GitHub update-lock verwijderd bij opstart: %s leeftijd=%.0fs inhoud=%s', GITHUB_UPDATE_MARKER, age, marker_text)
            elif logger:
                logger.info('GitHub update-lock aanwezig; update vermoedelijk bezig: %s leeftijd=%.0fs', GITHUB_UPDATE_MARKER, age)
        script = STATE_DIR / 'run-github-update.sh'
        if script.exists():
            age = time.time() - script.stat().st_mtime
            if age > 60:
                script.unlink()
                if logger:
                    logger.info('Achtergebleven GitHub update-script verwijderd bij opstart: %s', script)
    except Exception as exc:
        if logger:
            logger.warning('GitHub update cleanup bij opstart mislukt: %s', exc)


def _read_state():
    try:
        if GITHUB_UPDATE_STATE.exists():
            return json.loads(GITHUB_UPDATE_STATE.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {}


def _write_state(**data):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        current = _read_state()
        current.update(data)
        current['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        tmp = GITHUB_UPDATE_STATE.with_suffix('.tmp')
        tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding='utf-8')
        tmp.replace(GITHUB_UPDATE_STATE)
    except Exception:
        pass


def _due(settings, logger=None):
    global _STARTUP_CHECK_USED
    interval_hours = float(settings.get('interval_hours', 24))
    failure_retry_hours = float(settings.get('failure_retry_hours', 1))
    check_on_startup = bool(settings.get('check_on_startup', True))
    now = time.time()
    st = _read_state()
    last_success = float(st.get('last_success_ts', 0) or 0)
    last_attempt = float(st.get('last_attempt_ts', 0) or 0)
    last_result = str(st.get('last_result', ''))

    if check_on_startup and not _STARTUP_CHECK_USED:
        _STARTUP_CHECK_USED = True
        if logger:
            logger.info('GitHub-update controle toegestaan bij opstart')
        return True

    if last_success and now - last_success < interval_hours * 3600:
        if logger:
            logger.info('GitHub-update controle overgeslagen; laatste succesvolle controle is %.0f minuten geleden', (now - last_success) / 60)
        return False
    if last_result == 'error' and last_attempt and now - last_attempt < failure_retry_hours * 3600:
        if logger:
            logger.info('GitHub-update controle overgeslagen; laatste fout is %.0f minuten geleden', (now - last_attempt) / 60)
        return False
    return True


def _request(url, method='GET', extra_headers=None):
    headers = {'User-Agent': USER_AGENT, 'Cache-Control': 'no-cache', 'Pragma': 'no-cache'}
    if extra_headers:
        headers.update(extra_headers)
    return urllib.request.Request(url, method=method, headers=headers)


def _fetch_text(url, timeout=10, max_bytes=1024 * 256):
    with urllib.request.urlopen(_request(url), timeout=timeout) as resp:
        return resp.read(max_bytes).decode('utf-8', errors='replace')


def _fetch_json(url, timeout=10):
    return json.loads(_fetch_text(url, timeout=timeout))


def _url_exists(url, timeout=8):
    try:
        with urllib.request.urlopen(_request(url, method='HEAD'), timeout=timeout) as resp:
            return 200 <= int(resp.status) < 400
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        if exc.code not in (403, 405):
            return False
    except Exception:
        pass
    try:
        with urllib.request.urlopen(_request(url, extra_headers={'Range': 'bytes=0-0'}), timeout=timeout) as resp:
            return int(resp.status) in (200, 206)
    except urllib.error.HTTPError as exc:
        return exc.code in (200, 206)
    except Exception:
        return False


def _sha256_file(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _parse_sha256_text(text):
    for token in text.replace('\r', ' ').replace('\n', ' ').split():
        token = token.strip().lower()
        if len(token) == 64 and all(c in '0123456789abcdef' for c in token):
            return token
    return ''


def _zip_version(zip_path):
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


def _download(url, target, timeout=120):
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix('.download')
    with urllib.request.urlopen(_request(url), timeout=timeout) as resp, tmp.open('wb') as out:
        shutil.copyfileobj(resp, out)
    tmp.replace(target)


def _entry_from_index(settings, logger, current_number):
    index_url = str(settings.get('index_url') or DEFAULT_INDEX_URL)
    timeout = int(settings.get('timeout_seconds', 10))
    if logger:
        logger.info('GitHub-update index controle gestart: %s', index_url)
    manifest = _fetch_json(index_url, timeout=timeout)
    entries = manifest.get('versions') or manifest.get('releases') or []
    best = None
    best_num = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        num = int(entry.get('version_number') or entry.get('number') or version_number(str(entry.get('version') or entry.get('name') or '')) or 0)
        if num > current_number and num > best_num:
            best = entry
            best_num = num
    latest_num = int(manifest.get('latest') or manifest.get('latest_version_number') or 0)
    if not best and latest_num > current_number:
        base = str(manifest.get('release_base_url') or settings.get('release_base_url') or DEFAULT_RELEASE_BASE_URL)
        if not base.endswith('/'):
            base += '/'
        pattern = str(settings.get('file_pattern') or DEFAULT_FILE_PATTERN)
        name = pattern.replace('{version}', str(latest_num)).replace('{number}', str(latest_num))
        best = {
            'version': f'PiViewer {latest_num}',
            'version_number': latest_num,
            'zip_url': urllib.parse.urljoin(base, name),
            'sha256_url': urllib.parse.urljoin(base, name + '.sha256'),
        }
    if best and logger:
        logger.warning('GitHub-update kandidaat uit index: %s', best)
    return best


def _entry_from_direct_scan(settings, logger, current_number):
    base = str(settings.get('release_base_url') or DEFAULT_RELEASE_BASE_URL)
    if not base.endswith('/'):
        base += '/'
    pattern = str(settings.get('file_pattern') or DEFAULT_FILE_PATTERN)
    lookahead = int(settings.get('lookahead_versions', 20))
    timeout = int(settings.get('timeout_seconds', 8))
    best = None
    if logger:
        logger.info('GitHub direct ZIP scan gestart: base=%s bereik=%s-%s', base, current_number + 1, current_number + lookahead)
    for num in range(current_number + 1, current_number + lookahead + 1):
        name = pattern.replace('{version}', str(num)).replace('{number}', str(num))
        zip_url = urllib.parse.urljoin(base, name)
        if logger:
            logger.info('GitHub ZIP controle: %s', zip_url)
        if _url_exists(zip_url, timeout=timeout):
            best = {'version': f'PiViewer {num}', 'version_number': num, 'zip_url': zip_url, 'sha256_url': zip_url + '.sha256'}
            if logger:
                logger.warning('GitHub online ZIP gevonden: %s', zip_url)
    return best


def _resolve_expected_sha(entry, settings):
    sha = str(entry.get('sha256') or '').strip().lower()
    if sha:
        return sha
    sha_url = str(entry.get('sha256_url') or '')
    if not sha_url and entry.get('zip_url'):
        sha_url = str(entry.get('zip_url')) + '.sha256'
    if sha_url:
        text = _fetch_text(sha_url, timeout=int(settings.get('timeout_seconds', 10)), max_bytes=4096)
        return _parse_sha256_text(text)
    return ''


def _show_update_status(title, current_version='', new_version='', zip_path=None, message=''):
    if callable(show_update_status):
        try:
            show_update_status(title, current_version, new_version, zip_path, message)
        except Exception:
            pass


def _release_screen_for_update(logger=None):
    if callable(release_screen_for_update):
        try:
            release_screen_for_update(logger)
        except Exception:
            pass


def _spawn_installer(zip_path, logger, current_version, new_version):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    GITHUB_UPDATE_LOG.parent.mkdir(parents=True, exist_ok=True)
    _show_update_status('PiViewer GitHub-update gevonden', current_version, new_version, zip_path, 'Er staat een hogere PiViewer-versie klaar op GitHub. SHA-controle is akkoord.')
    tmp = Path('/tmp/piviewer-github-auto-update')
    script = STATE_DIR / 'run-github-update.sh'
    content = f'''#!/usr/bin/env bash
set -euo pipefail
exec >> "{GITHUB_UPDATE_LOG}" 2>&1
echo "===== GITHUB AUTO UPDATE START $(date) ====="
echo "ZIP: {zip_path}"
python3 "{STATUS_SCREEN}" --title "PiViewer GitHub-update" --current "{current_version}" --new "{new_version}" --zip "{zip_path}" --message "Updatebestand van GitHub wordt uitgepakt." || true
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
rm -f "{GITHUB_UPDATE_MARKER}"
python3 "/opt/piviewer-dev/app/update_status_screen.py" --title "PiViewer GitHub-update klaar" --new "{new_version}" --message "De update is klaar. PiViewer wordt schoon opnieuw gestart." || true
echo "Eindherstart van piviewer-dev.service wordt uitgevoerd."
sleep 2
systemctl restart piviewer-dev.service || true
echo "===== GITHUB AUTO UPDATE DONE $(date) ====="
'''
    script.write_text(content, encoding='utf-8')
    os.chmod(script, 0o755)
    GITHUB_UPDATE_MARKER.write_text(str(zip_path), encoding='utf-8')
    if logger:
        logger.warning('GitHub Auto Update gestart vanaf %s; log: %s', zip_path, GITHUB_UPDATE_LOG)
    subprocess.Popen(['bash', '-c', f'sleep 0.5; bash "{script}"'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def check_github_auto_update(config, logger, current_version=None):
    if not current_version:
        try:
            current_version = Path('/opt/piviewer-dev/VERSION').read_text(encoding='utf-8').strip()
        except Exception:
            current_version = 'PiViewer 0'

    updates = config.get('updates', {}) if isinstance(config.get('updates', {}), dict) else {}
    settings = dict(config.get('github_update', {}) if isinstance(config.get('github_update', {}), dict) else {})
    settings.update(updates.get('github_update', {}) if isinstance(updates.get('github_update', {}), dict) else {})
    if not settings:
        settings = {'enabled': True, 'auto_install': True}
    settings.setdefault('index_url', DEFAULT_INDEX_URL)
    settings.setdefault('release_base_url', DEFAULT_RELEASE_BASE_URL)
    settings.setdefault('file_pattern', DEFAULT_FILE_PATTERN)
    settings.setdefault('interval_hours', 24)
    settings.setdefault('failure_retry_hours', 1)
    settings.setdefault('lookahead_versions', 20)
    settings.setdefault('require_sha256', True)
    settings.setdefault('direct_scan_fallback', True)
    settings.setdefault('check_on_startup', True)

    if not settings.get('enabled', True) or not settings.get('auto_install', True):
        return False

    if GITHUB_UPDATE_MARKER.exists():
        try:
            age = time.time() - GITHUB_UPDATE_MARKER.stat().st_mtime
            if age < 180:
                if logger:
                    logger.info('GitHub update-lock aanwezig; auto-update is vermoedelijk nog bezig: %s leeftijd=%.0fs', GITHUB_UPDATE_MARKER, age)
                return True
            GITHUB_UPDATE_MARKER.unlink()
            if logger:
                logger.warning('Oude GitHub update-lock verwijderd tijdens update-check: %s leeftijd=%.0fs', GITHUB_UPDATE_MARKER, age)
        except Exception as exc:
            if logger:
                logger.warning('GitHub update-lock kon niet worden gecontroleerd: %s', exc)
            return True

    if not _due(settings, logger):
        return False

    current_num = version_number(current_version)
    _write_state(last_attempt_ts=time.time(), last_result='checking', index_url=settings.get('index_url'), release_base_url=settings.get('release_base_url'))

    try:
        entry = None
        try:
            entry = _entry_from_index(settings, logger, current_num)
        except Exception as exc:
            if logger:
                logger.warning('GitHub index controle mislukt: %s', exc)

        if not entry and settings.get('direct_scan_fallback', True):
            entry = _entry_from_direct_scan(settings, logger, current_num)

        if not entry:
            _write_state(last_success_ts=time.time(), last_result='ok', online_version=current_version, online_number=current_num, update_available=False)
            if logger:
                logger.info('GitHub-update controle klaar; geen hogere versie gevonden')
            return False

        online_num = int(entry.get('version_number') or entry.get('number') or version_number(str(entry.get('version') or entry.get('name') or '')) or 0)
        online_text = str(entry.get('version') or entry.get('name') or f'PiViewer {online_num}')
        zip_url = str(entry.get('zip_url') or entry.get('url') or '').strip()

        if online_num <= current_num or not zip_url:
            _write_state(last_success_ts=time.time(), last_result='ok', online_version=online_text, online_number=online_num, update_available=False)
            if logger:
                logger.info('GitHub-update controle klaar; online=%s lokaal=%s', online_text, current_version)
            return False

        if logger:
            logger.warning('Hogere PiViewer-versie gevonden op GitHub: huidig=%s (%s), nieuw=%s (%s), url=%s', current_version, current_num, online_text, online_num, zip_url)

        _release_screen_for_update(logger)
        _show_update_status('PiViewer GitHub-update gevonden', current_version, online_text, None, 'Nieuwe ZIP-versie gevonden op GitHub. Download en SHA-controle worden uitgevoerd.')

        expected_sha = _resolve_expected_sha(entry, settings)
        if settings.get('require_sha256', True) and not expected_sha:
            raise RuntimeError('SHA256 ontbreekt; update wordt geweigerd')

        target = GITHUB_UPDATE_DIR / f'PiViewer_{online_num}.zip'
        _download(zip_url, target, timeout=int(settings.get('download_timeout_seconds', 180)))
        actual_sha = _sha256_file(target)

        if expected_sha and actual_sha.lower() != expected_sha.lower():
            try:
                target.unlink()
            except Exception:
                pass
            raise RuntimeError(f'SHA256 mismatch: verwacht={expected_sha} werkelijk={actual_sha}')

        zip_num, zip_text = _zip_version(target)
        if zip_num <= current_num:
            raise RuntimeError(f'Gedownloade ZIP bevat geen hogere versie: {zip_text} ({zip_num})')
        if zip_num != online_num:
            raise RuntimeError(f'ZIP-versie komt niet overeen met manifest: manifest={online_num}, zip={zip_num}')

        _write_state(last_success_ts=time.time(), last_result='update_started', downloaded_zip=str(target), online_version=zip_text, online_number=zip_num, update_available=True, zip_url=zip_url, sha256=actual_sha)
        _spawn_installer(target, logger, current_version, zip_text or online_text)
        return True
    except Exception as exc:
        _write_state(last_result='error', last_error=str(exc), last_error_ts=time.time())
        if logger:
            logger.warning('GitHub-update controle mislukt: %s', exc)
        return False
