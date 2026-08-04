import hashlib
from pathlib import Path
from typing import Dict, Iterable, Optional

from wifi import connect_wifi, wifi_status

STATE_DIR = Path('/var/lib/piviewer-dev')
APPLIED_FILE = STATE_DIR / 'usb-wifi-applied.sha256'


def _parse_wifi_txt(path: Path) -> Dict[str, str]:
    """Lees WiFi.txt.

    Veiligheidsregel vanaf PiViewer 2016:
    de eerste niet-lege/niet-comment regel moet expliciet aangeven of het bestand
    gelezen mag worden. Standaard is:

        PIVIEWER_WIFI=READ

    Of om over te slaan:

        PIVIEWER_WIFI=SKIP

    Zonder geldige eerste regel wordt het bestand genegeerd. Zo voorkomt PiViewer
    dat voorbeeldbestanden of oude WiFi.txt-bestanden per ongeluk de WiFi wijzigen.
    """
    data: Dict[str, str] = {}
    text = path.read_text(encoding='utf-8', errors='ignore')

    config_lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        config_lines.append(line)

    if not config_lines:
        data['_ACTION'] = 'SKIP'
        data['_SKIP_REASON'] = 'bestand is leeg'
        return data

    first = config_lines[0]
    first_upper = first.upper().strip()

    read_tokens = {
        'PIVIEWER_WIFI=READ',
        'PIVIEWER_WIFI=YES',
        'PIVIEWER_WIFI=TRUE',
        'WIFI=READ',
        'ACTION=READ',
        'READ=TRUE',
        'ENABLED=TRUE',
        'ENABLED=YES',
        'ACTIVE=TRUE',
        'ACTIVE=YES',
    }
    skip_tokens = {
        'PIVIEWER_WIFI=SKIP',
        'PIVIEWER_WIFI=NO',
        'PIVIEWER_WIFI=FALSE',
        'WIFI=SKIP',
        'ACTION=SKIP',
        'READ=FALSE',
        'ENABLED=FALSE',
        'ENABLED=NO',
        'ACTIVE=FALSE',
        'ACTIVE=NO',
        'SKIP',
    }

    if first_upper in skip_tokens:
        data['_ACTION'] = 'SKIP'
        data['_SKIP_REASON'] = f'eerste regel is {first}'
        return data

    if first_upper not in read_tokens:
        data['_ACTION'] = 'SKIP'
        data['_SKIP_REASON'] = 'eerste regel ontbreekt of is geen PIVIEWER_WIFI=READ'
        return data

    data['_ACTION'] = 'READ'

    # Verwerk alle overige KEY=VALUE-regels. De eerste regel mag ook blijven staan;
    # onbekende sleutels worden verder genegeerd.
    for raw in config_lines:
        if '=' not in raw:
            continue
        key, value = raw.split('=', 1)
        data[key.strip().upper()] = value.strip().strip('"')
    return data

def _find_wifi_txt(mounts: Iterable[str], filename: str) -> Optional[Path]:
    target = filename.lower()
    for raw_mount in mounts:
        root = Path(raw_mount)
        if not root.exists():
            continue
        try:
            for item in root.iterdir():
                if item.is_file() and item.name.lower() == target:
                    return item
        except OSError:
            continue
    return None


def _fingerprint(path: Path) -> str:
    payload = path.read_bytes()
    return hashlib.sha256(str(path).encode('utf-8') + b'\0' + payload).hexdigest()


def apply_usb_wifi_configs(config: Dict, logger, mounts) -> None:
    settings = config.get('usb_wifi', {})
    if not settings.get('enabled', True):
        return

    path = _find_wifi_txt(mounts, settings.get('filename', 'WiFi.txt'))
    if not path:
        return

    try:
        fp = _fingerprint(path)
        if APPLIED_FILE.exists() and APPLIED_FILE.read_text(encoding='utf-8').strip() == fp:
            return
    except Exception:
        fp = ''

    try:
        data = _parse_wifi_txt(path)
    except Exception as exc:
        if logger:
            logger.error('WiFi.txt kon niet worden gelezen: %s', exc)
        return

    action = data.get('_ACTION', 'SKIP')
    if action != 'READ':
        if logger:
            logger.info('WiFi.txt gevonden maar overgeslagen: %s (%s)', path, data.get('_SKIP_REASON', 'niet actief'))
        return

    ssid = data.get('SSID', '').strip()
    password = data.get('PASSWORD', '')
    country = data.get('COUNTRY', 'NL').strip() or 'NL'
    delete_after_success = str(data.get('DELETE_AFTER_SUCCESS', settings.get('delete_after_success', False))).lower() in ('1', 'true', 'yes', 'ja')

    if not ssid:
        if logger:
            logger.warning('WiFi.txt gevonden maar SSID ontbreekt: %s', path)
        return

    current = wifi_status().get('ssid', '')
    if logger:
        logger.info('USB WiFi-config gevonden: %s', path)
        logger.info('USB WiFi SSID: %s', ssid)
        if current == ssid:
            logger.info('WiFi is al verbonden met %s; profiel wordt bijgewerkt indien nodig', ssid)

    result = connect_wifi(ssid, password, country)
    ok = str(result.get('ok', 'false')).lower() == 'true'
    if logger:
        logger.info('USB WiFi resultaat voor %s: %s', ssid, result.get('message', ''))

    if ok:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            APPLIED_FILE.write_text(fp, encoding='utf-8')
        except Exception:
            pass
        if delete_after_success:
            try:
                path.unlink()
                if logger:
                    logger.info('WiFi.txt verwijderd na succesvolle verbinding: %s', path)
            except Exception as exc:
                if logger:
                    logger.warning('WiFi.txt kon niet worden verwijderd: %s', exc)
