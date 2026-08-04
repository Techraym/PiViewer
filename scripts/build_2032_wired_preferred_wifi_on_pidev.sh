#!/usr/bin/env bash
set +e

WORK="${HOME}/PiViewer-pidev-2030"
VERSION="2032"
VERSION_TEXT="PiViewer 2032"
REPO="git@github.com:Techraym/PiViewer.git"

echo "=== PiViewer 2032 build: WiFi.txt instellen, bedraad voorkeur ==="
echo "Werkmap: ${WORK}"

if [ ! -d "${WORK}/.git" ]; then
  echo "FOUT: git werkmap niet gevonden: ${WORK}"
  ls -ld "${HOME}"/PiViewer* 2>/dev/null
  echo "RESULT_CODE=1"
  exit 1
fi

cd "${WORK}" || exit 1

echo
echo "=== GitHub SSH controleren ==="
git remote set-url origin "${REPO}"
SSH_TEST="$(ssh -T git@github.com 2>&1 || true)"
echo "${SSH_TEST}"
if ! echo "${SSH_TEST}" | grep -qiE "successfully authenticated|Hi "; then
  echo "FOUT: GitHub SSH werkt niet vanaf PiDev."
  echo "RESULT_CODE=2"
  exit 2
fi

echo
echo "=== Lokale wijzigingen opruimen en main ophalen ==="
git rebase --abort 2>/dev/null || true
git reset --hard HEAD
git clean -fd
git fetch origin main
git reset --hard origin/main
PULL_CODE=$?
echo "PULL_CODE=${PULL_CODE}"
if [ "${PULL_CODE}" -ne 0 ]; then
  echo "FOUT: GitHub main ophalen mislukt."
  echo "RESULT_CODE=3"
  exit 3
fi

echo
echo "=== Patch 2032 schrijven ==="
cat > /tmp/piviewer_patch_2032.py <<'PY2032'
from pathlib import Path
import json

VERSION = "2032"
VERSION_TEXT = "PiViewer 2032"

Path("VERSION").write_text(VERSION_TEXT + "\n", encoding="utf-8")

wifi_py = r'''import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

WPA_CONF = Path('/etc/wpa_supplicant/wpa_supplicant.conf')
WIRED_ROUTE_METRIC = '100'
WIFI_ROUTE_METRIC = '600'


def _run(cmd: List[str], timeout: int = 12) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout or '') + (proc.stderr or '')
        return proc.returncode == 0, out.strip()
    except FileNotFoundError:
        return False, f"Commando niet gevonden: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return False, f"Timeout bij commando: {' '.join(cmd)}"
    except Exception as exc:
        return False, str(exc)


def _is_wireless_interface(name: str) -> bool:
    if name.startswith(('wl', 'wlan')):
        return True
    return (Path('/sys/class/net') / name / 'wireless').exists()


def _is_virtual_interface(name: str) -> bool:
    prefixes = ('lo', 'docker', 'veth', 'br-', 'virbr', 'tun', 'tap', 'wg', 'tailscale', 'zt')
    return name == 'lo' or name.startswith(prefixes)


def ethernet_interfaces() -> List[str]:
    root = Path('/sys/class/net')
    result: List[str] = []
    if not root.exists():
        return result
    for item in sorted(root.iterdir()):
        name = item.name
        if _is_virtual_interface(name) or _is_wireless_interface(name):
            continue
        carrier = item / 'carrier'
        if carrier.exists():
            result.append(name)
    return result


def wired_link_connected() -> bool:
    for name in ethernet_interfaces():
        carrier = Path('/sys/class/net') / name / 'carrier'
        try:
            if carrier.read_text(encoding='utf-8', errors='ignore').strip() == '1':
                return True
        except Exception:
            continue
    return False


def active_wired_interfaces() -> List[str]:
    active: List[str] = []
    for name in ethernet_interfaces():
        carrier = Path('/sys/class/net') / name / 'carrier'
        try:
            if carrier.read_text(encoding='utf-8', errors='ignore').strip() == '1':
                active.append(name)
        except Exception:
            pass
    return active


def _nmcli_connection_exists(name: str) -> bool:
    if not shutil.which('nmcli'):
        return False
    ok, _ = _run(['nmcli', '-t', 'connection', 'show', name], timeout=8)
    return ok


def _nmcli_wifi_connections() -> List[str]:
    if not shutil.which('nmcli'):
        return []
    ok, out = _run(['nmcli', '-t', '-f', 'NAME,TYPE', 'connection', 'show'], timeout=10)
    result: List[str] = []
    if not ok:
        return result
    for line in out.splitlines():
        parts = line.split(':')
        if len(parts) >= 2 and parts[-1] in ('wifi', '802-11-wireless'):
            result.append(':'.join(parts[:-1]).replace('\\:', ':'))
    return result


def _nmcli_active_connections() -> List[Tuple[str, str, str]]:
    if not shutil.which('nmcli'):
        return []
    ok, out = _run(['nmcli', '-t', '-f', 'NAME,TYPE,DEVICE', 'connection', 'show', '--active'], timeout=10)
    result: List[Tuple[str, str, str]] = []
    if not ok:
        return result
    for line in out.splitlines():
        parts = line.split(':')
        if len(parts) >= 3:
            name = ':'.join(parts[:-2]).replace('\\:', ':')
            result.append((name, parts[-2], parts[-1]))
    return result


def apply_wired_preferred_metrics() -> None:
    if not shutil.which('nmcli'):
        return

    for name, typ, dev in _nmcli_active_connections():
        if typ in ('ethernet', '802-3-ethernet'):
            _run(['nmcli', 'connection', 'modify', name,
                  'connection.autoconnect', 'yes',
                  'ipv4.route-metric', WIRED_ROUTE_METRIC,
                  'ipv6.route-metric', WIRED_ROUTE_METRIC], timeout=10)
            if dev:
                _run(['nmcli', 'device', 'reapply', dev], timeout=10)

    for name in _nmcli_wifi_connections():
        _run(['nmcli', 'connection', 'modify', name,
              'connection.autoconnect', 'yes',
              'ipv4.route-metric', WIFI_ROUTE_METRIC,
              'ipv6.route-metric', WIFI_ROUTE_METRIC,
              'connection.autoconnect-priority', '-10'], timeout=10)


def wifi_status() -> Dict[str, str]:
    ok_ssid, ssid = _run(['iwgetid', '-r'], timeout=5)
    ok_ip, ips = _run(['hostname', '-I'], timeout=5)
    ok_link, link = _run(['ip', '-o', 'link', 'show', 'wlan0'], timeout=5)
    ok_rfkill, rfkill = _run(['rfkill', 'list', 'wifi'], timeout=5)
    wired = wired_link_connected()
    wired_ifaces = ','.join(active_wired_interfaces())
    return {
        'interface': 'wlan0',
        'ssid': ssid if ok_ssid and ssid else '',
        'ip_addresses': ips if ok_ip else '',
        'wlan0': 'aanwezig' if ok_link else 'niet gevonden',
        'rfkill': rfkill if ok_rfkill else '',
        'wired_connected': 'true' if wired else 'false',
        'wired_interfaces': wired_ifaces,
        'network_preference': 'bedraad' if wired else 'wifi',
    }


def scan_wifi() -> List[str]:
    networks = set()
    if shutil.which('nmcli'):
        ok, out = _run(['nmcli', '-t', '-f', 'SSID', 'dev', 'wifi', 'list'], timeout=15)
        if ok:
            for line in out.splitlines():
                ssid = line.strip().replace('\\:', ':')
                if ssid:
                    networks.add(ssid)
    if not networks and shutil.which('iwlist'):
        ok, out = _run(['iwlist', 'wlan0', 'scan'], timeout=20)
        if ok:
            for line in out.splitlines():
                line = line.strip()
                if 'ESSID:' in line:
                    ssid = line.split('ESSID:', 1)[1].strip().strip('"')
                    if ssid:
                        networks.add(ssid)
    return sorted(networks, key=str.lower)


def _escape_wpa(value: str) -> str:
    return value.replace('\\', '\\\\').replace('"', '\\"')


def _write_wpa_supplicant(ssid: str, password: str, country: str = 'NL') -> str:
    WPA_CONF.parent.mkdir(parents=True, exist_ok=True)
    if WPA_CONF.exists():
        backup = WPA_CONF.with_suffix('.conf.backup')
        try:
            backup.write_text(WPA_CONF.read_text(encoding='utf-8', errors='ignore'), encoding='utf-8')
        except Exception:
            pass
        content = WPA_CONF.read_text(encoding='utf-8', errors='ignore')
    else:
        content = ''

    header = f"country={country}\nctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\nupdate_config=1\n"
    if 'ctrl_interface=' not in content:
        content = header + '\n' + content
    elif 'country=' not in content:
        content = f"country={country}\n" + content

    if password:
        network = (
            '\nnetwork={\n'
            f'    ssid="{_escape_wpa(ssid)}"\n'
            f'    psk="{_escape_wpa(password)}"\n'
            '    key_mgmt=WPA-PSK\n'
            '}\n'
        )
    else:
        network = (
            '\nnetwork={\n'
            f'    ssid="{_escape_wpa(ssid)}"\n'
            '    key_mgmt=NONE\n'
            '}\n'
        )
    content = content.rstrip() + '\n' + network
    WPA_CONF.write_text(content, encoding='utf-8')
    os.chmod(WPA_CONF, 0o600)
    return str(WPA_CONF)


def _nmcli_configure_wifi_profile(ssid: str, password: str) -> Tuple[bool, str]:
    con_name = f'PiViewer WiFi {ssid}'
    if not _nmcli_connection_exists(con_name):
        ok, out = _run(['nmcli', 'connection', 'add',
                        'type', 'wifi',
                        'ifname', 'wlan0',
                        'con-name', con_name,
                        'ssid', ssid], timeout=15)
        if not ok:
            return False, out

    cmd = ['nmcli', 'connection', 'modify', con_name,
           'connection.autoconnect', 'yes',
           'connection.autoconnect-priority', '-10',
           'ipv4.method', 'auto',
           'ipv4.route-metric', WIFI_ROUTE_METRIC,
           'ipv6.method', 'auto',
           'ipv6.route-metric', WIFI_ROUTE_METRIC]
    if password:
        cmd += ['wifi-sec.key-mgmt', 'wpa-psk', 'wifi-sec.psk', password]
    else:
        cmd += ['wifi-sec.key-mgmt', 'none']
    ok, out = _run(cmd, timeout=15)
    if not ok:
        return False, out
    return True, con_name


def connect_wifi(ssid: str, password: str, country: str = 'NL', activate: bool = True) -> Dict[str, str]:
    ssid = (ssid or '').strip()
    password = password or ''
    country = (country or 'NL').strip().upper()[:2]
    if not ssid:
        return {'ok': 'false', 'message': 'SSID ontbreekt.'}
    if password and len(password) < 8:
        return {'ok': 'false', 'message': 'WiFi-wachtwoord moet minimaal 8 tekens zijn.'}

    wired = wired_link_connected()
    apply_wired_preferred_metrics()

    if shutil.which('nmcli'):
        ok_profile, profile_msg = _nmcli_configure_wifi_profile(ssid, password)
        if not ok_profile:
            nmcli_error = profile_msg
        else:
            if wired and not activate:
                return {
                    'ok': 'true',
                    'message': f'WiFi-profiel opgeslagen voor {ssid}. Netwerkkabel is aangesloten; bedraad blijft voorkeur.',
                    'details': f'NetworkManager profiel: {profile_msg}',
                }

            if shutil.which('rfkill'):
                _run(['rfkill', 'unblock', 'wifi'], timeout=5)
            ok_up, out_up = _run(['nmcli', 'connection', 'up', profile_msg], timeout=35)
            apply_wired_preferred_metrics()
            if ok_up:
                extra = ' Bedraad blijft voorkeur.' if wired else ''
                return {'ok': 'true', 'message': f'Verbonden met {ssid} via NetworkManager.{extra}'}
            nmcli_error = out_up
    else:
        nmcli_error = 'nmcli niet aanwezig; wpa_supplicant fallback gebruikt.'

    path = _write_wpa_supplicant(ssid, password, country)
    if wired and not activate:
        return {
            'ok': 'true',
            'message': f'WiFi-configuratie opgeslagen voor {ssid}. Netwerkkabel is aangesloten; bedraad blijft voorkeur. Bestand: {path}',
            'details': nmcli_error,
        }

    if shutil.which('rfkill'):
        _run(['rfkill', 'unblock', 'wifi'], timeout=5)

    cmds = [
        ['wpa_cli', '-i', 'wlan0', 'reconfigure'],
        ['systemctl', 'restart', 'wpa_supplicant'],
        ['dhclient', '-r', 'wlan0'],
        ['dhclient', 'wlan0'],
    ]
    results = []
    for cmd in cmds:
        if shutil.which(cmd[0]):
            ok, out = _run(cmd, timeout=20)
            results.append(f"{'OK' if ok else 'WARN'} {' '.join(cmd)} {out}".strip())

    return {
        'ok': 'true',
        'message': f'WiFi-configuratie opgeslagen voor {ssid}. Bestand: {path}. Mogelijk is een reboot nodig.',
        'details': nmcli_error + '\n' + '\n'.join(results),
    }
'''

usb_wifi_py = r'''import hashlib
from pathlib import Path
from typing import Dict, Iterable, Optional

from wifi import connect_wifi, wifi_status, wired_link_connected, active_wired_interfaces, apply_wired_preferred_metrics

STATE_DIR = Path('/var/lib/piviewer-dev')
APPLIED_FILE = STATE_DIR / 'usb-wifi-applied.sha256'


def _parse_wifi_txt(path: Path) -> Dict[str, str]:
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


def _truthy(value) -> bool:
    return str(value).strip().lower() in ('1', 'true', 'yes', 'ja', 'on')


def apply_usb_wifi_configs(config: Dict, logger, mounts) -> None:
    settings = config.get('usb_wifi', {})
    if not settings.get('enabled', True):
        return

    try:
        apply_wired_preferred_metrics()
    except Exception as exc:
        if logger:
            logger.warning('Netwerkvoorkeur bedraad/wifi kon niet worden toegepast: %s', exc)

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
    delete_after_success = _truthy(data.get('DELETE_AFTER_SUCCESS', settings.get('delete_after_success', False)))

    if not ssid:
        if logger:
            logger.warning('WiFi.txt gevonden maar SSID ontbreekt: %s', path)
        return

    wired = wired_link_connected()
    activate_when_wired = _truthy(data.get('ACTIVATE_WHEN_WIRED', settings.get('activate_when_wired', False)))
    activate_wifi = (not wired) or activate_when_wired

    current = wifi_status().get('ssid', '')
    if logger:
        logger.info('USB WiFi-config gevonden: %s', path)
        logger.info('USB WiFi SSID: %s', ssid)
        if wired:
            logger.info('Netwerkkabel actief op %s; WiFi.txt wordt gebruikt om het profiel op te slaan, maar bedraad blijft voorkeur.', ','.join(active_wired_interfaces()) or 'ethernet')
        if current == ssid:
            logger.info('WiFi is al verbonden met %s; profiel wordt bijgewerkt indien nodig', ssid)

    result = connect_wifi(ssid, password, country, activate=activate_wifi)
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
'''

Path("app/wifi.py").write_text(wifi_py, encoding="utf-8")
Path("app/usb_wifi.py").write_text(usb_wifi_py, encoding="utf-8")

cfg_path = Path("config/piviewer.example.json")
data = json.loads(cfg_path.read_text(encoding="utf-8"))
data["version"] = VERSION_TEXT
data.setdefault("usb_wifi", {})
data["usb_wifi"]["activate_when_wired"] = False
data["usb_wifi"]["wired_preferred"] = True
data.setdefault("network_preference", {})
data["network_preference"] = {
    "prefer_wired_when_connected": True,
    "wired_route_metric": 100,
    "wifi_route_metric": 600,
    "note": "WiFi.txt wordt wel gelezen en opgeslagen; bij aangesloten netwerkkabel blijft bedraad de voorkeur."
}
if isinstance(data.get("updates"), dict):
    data["updates"].pop("web_update", None)
data.pop("web_update", None)
cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

print("Patch 2032 OK")
PY2032

python3 /tmp/piviewer_patch_2032.py
PATCH_CODE=$?
echo "PATCH_CODE=${PATCH_CODE}"
if [ "${PATCH_CODE}" -ne 0 ]; then
  echo "FOUT: patch mislukt."
  echo "RESULT_CODE=4"
  exit 4
fi

echo
echo "=== Syntax controleren ==="
python3 -m py_compile app/*.py
PY_CODE=$?
echo "PY_CODE=${PY_CODE}"
if [ "${PY_CODE}" -ne 0 ]; then
  echo "FOUT: Python syntaxcontrole mislukt."
  echo "RESULT_CODE=5"
  exit 5
fi

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
  echo "FOUT: SHA controle mislukt."
  echo "RESULT_CODE=6"
  exit 6
fi

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
  "notes": "PiViewer 2032: WiFi.txt wordt altijd gebruikt om WiFi-profiel in te stellen. Als netwerkkabel is aangesloten blijft bedraad de voorkeur; WiFi krijgt hogere route metric."
}
JSON

echo
echo "=== Git commit maken ==="
git add VERSION app/wifi.py app/usb_wifi.py config/piviewer.example.json updates/index.json scripts/build_2032_wired_preferred_wifi_on_pidev.sh
git add -f "releases/PiViewer_${VERSION}.zip" "releases/PiViewer_${VERSION}.zip.sha256"
git status --short
git commit -m "Release PiViewer 2032 prefer wired while applying WiFi txt"
COMMIT_CODE=$?
echo "COMMIT_CODE=${COMMIT_CODE}"

echo
echo "=== Push naar GitHub ==="
git push origin main
PUSH_CODE=$?
echo "PUSH_CODE=${PUSH_CODE}"
if [ "${PUSH_CODE}" -ne 0 ]; then
  echo "FOUT: push mislukt."
  echo "RESULT_CODE=7"
  exit 7
fi

echo
echo "=== Online controle ==="
sleep 4
curl -I "https://raw.githubusercontent.com/Techraym/PiViewer/main/releases/PiViewer_${VERSION}.zip?t=$(date +%s)" | head -n 8
curl -fsSL "https://raw.githubusercontent.com/Techraym/PiViewer/main/updates/index.json?t=$(date +%s)" | python3 -m json.tool

echo
echo "RESULT_CODE=0"
echo "Script klaar. SSH blijft open."
