import socket
import subprocess
import time
from typing import Dict, Tuple

_LAST_CHECK = 0.0
_LAST_RESULT = True
_LAST_REASON = 'startup'
_LAST_LOGGED = None


def _run_route(timeout: int = 3) -> bool:
    try:
        proc = subprocess.run(['ip', 'route', 'get', '1.1.1.1'], capture_output=True, text=True, timeout=timeout)
        return proc.returncode == 0 and 'dev' in (proc.stdout or '')
    except Exception:
        return False


def _socket_check(host: str, port: int, timeout: int) -> Tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f'{host}:{port} bereikbaar'
    except OSError as exc:
        return False, str(exc)


def internet_available(config: Dict, logger=None) -> bool:
    """Controleer lichtgewicht of internet bruikbaar is voor streams.

    Resultaat wordt kort gecachet om de Pi 2 niet onnodig te belasten.
    """
    global _LAST_CHECK, _LAST_RESULT, _LAST_REASON, _LAST_LOGGED

    cfg = config.get('network_monitor', {})
    if not cfg.get('enabled', True):
        return True

    interval = int(cfg.get('check_interval_seconds', 15))
    now = time.time()
    if now - _LAST_CHECK < interval:
        return _LAST_RESULT

    _LAST_CHECK = now
    host = str(cfg.get('check_host', '1.1.1.1'))
    port = int(cfg.get('check_port', 53))
    timeout = int(cfg.get('timeout_seconds', 2))

    if not _run_route(timeout=timeout):
        _LAST_RESULT = False
        _LAST_REASON = 'geen route naar internet'
    else:
        ok, reason = _socket_check(host, port, timeout)
        _LAST_RESULT = ok
        _LAST_REASON = reason if ok else f'internetcheck mislukt: {reason}'

    if logger and _LAST_LOGGED != _LAST_RESULT:
        if _LAST_RESULT:
            logger.info('Netwerk/internet beschikbaar: %s', _LAST_REASON)
        else:
            logger.warning('Netwerk/internet niet beschikbaar: %s', _LAST_REASON)
        _LAST_LOGGED = _LAST_RESULT

    return _LAST_RESULT


def last_network_reason() -> str:
    return _LAST_REASON
