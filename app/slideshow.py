from pathlib import Path
from typing import Dict, List

from imagecache import prepare_photo_cache
from usbmedia import cleanup_missing_usb_mounts, ensure_usb_mounts


def find_photos(config: Dict, logger=None) -> List[str]:
    ss = config.get("usb_slideshow", {})
    if not ss.get("enabled", True):
        return []

    cleanup_missing_usb_mounts(config, logger)
    auto_mount_paths = ensure_usb_mounts(config, logger)

    extensions = {ext.lower() for ext in ss.get("allowed_extensions", [".jpg", ".jpeg", ".png", ".webp", ".bmp"])}
    excluded_names = {name.lower() for name in ss.get("exclude_filenames", ["nossid.png", "nointernet.png"])}
    photos: List[str] = []
    seen = set()

    scan_paths = list(ss.get("paths", [])) + auto_mount_paths
    for raw_path in scan_paths:
        path = Path(raw_path)
        if not path.exists():
            continue
        try:
            for item in path.rglob("*"):
                if item.is_file() and item.suffix.lower() in extensions and item.name.lower() not in excluded_names:
                    value = str(item)
                    if value not in seen:
                        seen.add(value)
                        photos.append(value)
        except (PermissionError, OSError):
            continue

    if not photos:
        return []

    return prepare_photo_cache(photos, config, logger)
