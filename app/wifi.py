import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

WPA_CONF = Path('/etc/wpa_supplicant/wpa_supplicant.conf')


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


def wifi_status() -> Dict[str, str]:
    ok_ssid, ssid = _run(['iwgetid', '-r'], timeout=5)
    ok_ip, ips = _run(['hostname', '-I'], timeout=5)
    ok_link, link = _run(['ip', '-o', 'link', 'show', 'wlan0'], timeout=5)
    ok_rfkill, rfkill = _run(['rfkill', 'list', 'wifi'], timeout=5)
    return {
        'interface': 'wlan0',
        'ssid': ssid if ok_ssid and ssid else '',
        'ip_addresses': ips if ok_ip else '',
        'wlan0': 'aanwezig' if ok_link else 'niet gevonden',
        'rfkill': rfkill if ok_rfkill else '',
    }


def scan_wifi() -> List[str]:
    networks = set()
    # nmcli is fastest/cleanest when NetworkManager is present.
    if shutil.which('nmcli'):
        ok, out = _run(['nmcli', '-t', '-f', 'SSID', 'dev', 'wifi', 'list'], timeout=15)
        if ok:
            for line in out.splitlines():
                ssid = line.strip().replace('\\:', ':')
                if ssid:
                    networks.add(ssid)
    # Fallback for Raspberry Pi OS Lite/wpa_supplicant setups.
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


def connect_wifi(ssid: str, password: str, country: str = 'NL') -> Dict[str, str]:
    ssid = (ssid or '').strip()
    password = password or ''
    country = (country or 'NL').strip().upper()[:2]
    if not ssid:
        return {'ok': 'false', 'message': 'SSID ontbreekt.'}
    if password and len(password) < 8:
        return {'ok': 'false', 'message': 'WiFi-wachtwoord moet minimaal 8 tekens zijn.'}

    # Unblock WiFi if rfkill exists.
    if shutil.which('rfkill'):
        _run(['rfkill', 'unblock', 'wifi'], timeout=5)

    if shutil.which('nmcli'):
        nmcli_cmd = ['nmcli', 'dev', 'wifi', 'connect', ssid]
        if password:
            nmcli_cmd += ['password', password]
        ok, out = _run(nmcli_cmd, timeout=35)
        if ok:
            return {'ok': 'true', 'message': f'Verbonden met {ssid} via NetworkManager.'}
        # Continue to wpa_supplicant fallback and include nmcli error if fallback fails.
        nmcli_error = out
    else:
        nmcli_error = 'nmcli niet aanwezig; wpa_supplicant fallback gebruikt.'

    path = _write_wpa_supplicant(ssid, password, country)
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
