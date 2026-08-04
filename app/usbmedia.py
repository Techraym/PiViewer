import os
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

STATE_MOUNT_ROOT_DEFAULT = "/var/lib/piviewer-dev/usbmounts"


def _run(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)


def list_usb_partitions() -> List[Tuple[str, str]]:
    """Return removable USB partitions as (device, safe_name).

    We use lsblk instead of fixed mount paths, so any USB port works.
    Typical result: /dev/sda1 -> sda1.
    """
    result = _run(["lsblk", "-rpno", "NAME,TYPE,RM"])
    devices: List[Tuple[str, str]] = []
    if result.returncode != 0:
        return devices
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        name, typ, rm = parts[0], parts[1], parts[2]
        if typ != "part" or rm != "1":
            continue
        if not name.startswith("/dev/"):
            continue
        safe = Path(name).name.replace("/", "_")
        devices.append((name, safe))
    return devices


def current_mounts() -> Dict[str, str]:
    mounts: Dict[str, str] = {}
    try:
        with open("/proc/mounts", "r", encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 2:
                    mounts[parts[0]] = parts[1].replace("\\040", " ")
    except OSError:
        pass
    return mounts


def ensure_usb_mounts(config: Dict, logger=None) -> List[str]:
    """Mount every removable USB partition and return mount paths.

    This is intentionally simple and Pi-friendly:
    - no udev daemon is required;
    - no database;
    - poll-based detection every scheduler tick;
    - read-only mounts by default to reduce filesystem risk.
    """
    ss = config.get("usb_slideshow", {})
    automount = ss.get("auto_mount", {})
    if not automount.get("enabled", True):
        return []

    mount_root = Path(automount.get("mount_root", STATE_MOUNT_ROOT_DEFAULT))
    readonly = bool(automount.get("readonly", True))
    mount_root.mkdir(parents=True, exist_ok=True)

    existing = current_mounts()
    active_mounts: List[str] = []

    for device, safe in list_usb_partitions():
        if device in existing:
            active_mounts.append(existing[device])
            continue

        mount_point = mount_root / safe
        mount_point.mkdir(parents=True, exist_ok=True)
        opts = "ro,nosuid,nodev,noexec" if readonly else "rw,nosuid,nodev,noexec"
        cmd = ["mount", "-o", opts, device, str(mount_point)]
        result = _run(cmd)
        if result.returncode == 0:
            if logger:
                logger.info("USB-partitie %s automatisch gekoppeld op %s", device, mount_point)
            active_mounts.append(str(mount_point))
        else:
            # Retry without noexec for filesystems/mount helpers that reject combined opts.
            opts2 = "ro,nosuid,nodev" if readonly else "rw,nosuid,nodev"
            result2 = _run(["mount", "-o", opts2, device, str(mount_point)])
            if result2.returncode == 0:
                if logger:
                    logger.info("USB-partitie %s automatisch gekoppeld op %s", device, mount_point)
                active_mounts.append(str(mount_point))
            elif logger:
                logger.warning("USB-partitie %s kon niet worden gekoppeld: %s", device, (result.stderr or result2.stderr).strip())

    return active_mounts


def cleanup_missing_usb_mounts(config: Dict, logger=None) -> None:
    """Unmount stale PiViewer USB mount points whose device disappeared."""
    ss = config.get("usb_slideshow", {})
    automount = ss.get("auto_mount", {})
    mount_root = Path(automount.get("mount_root", STATE_MOUNT_ROOT_DEFAULT))
    if not mount_root.exists():
        return

    present_devices = {dev for dev, _safe in list_usb_partitions()}
    mounts = current_mounts()
    for device, mount_point in list(mounts.items()):
        try:
            mp = Path(mount_point)
        except Exception:
            continue
        if mount_root not in mp.parents and mp != mount_root:
            continue
        if device in present_devices:
            continue
        result = _run(["umount", "-l", mount_point])
        if logger and result.returncode == 0:
            logger.info("Verdwenen USB-mount opgeruimd: %s", mount_point)
