import os
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
    # Gebruik de SSID ook als NetworkManager-profielnaam.
    # Daardoor staat een WiFi.txt met SSID=GAST opgeslagen als profiel 'GAST',
    # niet als 'PiViewer WiFi GAST'.
    con_name = ssid
    legacy_name = f'PiViewer WiFi {ssid}'
    if not _nmcli_connection_exists(con_name) and _nmcli_connection_exists(legacy_name):
        _run(['nmcli', 'connection', 'modify', legacy_name, 'connection.id', con_name], timeout=10)

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
