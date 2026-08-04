import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional

try:
    from PIL import Image, ImageOps, UnidentifiedImageError
except Exception:  # Pillow kan ontbreken bij een oude installatie
    Image = None
    ImageOps = None
    UnidentifiedImageError = Exception


def _safe_cache_name(path: Path, stat) -> str:
    token = f"{path}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8", "ignore")
    return hashlib.sha1(token).hexdigest() + ".jpg"


def _normalise_image(src: Path, dst: Path, max_width: int, max_height: int, quality: int, logger=None) -> bool:
    if Image is None:
        if logger:
            logger.warning("python3-pil/Pillow ontbreekt; originele foto wordt gebruikt: %s", src)
        return False
    try:
        with Image.open(src) as img:
            # Corrigeer telefoonfoto's met EXIF-rotatie.
            img = ImageOps.exif_transpose(img)

            # Alles naar RGB. Alpha/transparantie wordt op zwarte achtergrond gezet.
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                rgba = img.convert("RGBA")
                bg = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
                bg.alpha_composite(rgba)
                img = bg.convert("RGB")
            else:
                img = img.convert("RGB")

            # Verklein alleen, nooit opschalen. Dit voorkomt GPU/decoder problemen op Pi 2/3.
            img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

            # Maak een vaste canvasmaat. mpv hoeft dan niet per foto anders te schalen.
            canvas = Image.new("RGB", (max_width, max_height), (0, 0, 0))
            x = (max_width - img.width) // 2
            y = (max_height - img.height) // 2
            canvas.paste(img, (x, y))

            tmp = dst.with_suffix(".tmp.jpg")
            canvas.save(tmp, "JPEG", quality=quality, optimize=True, progressive=False)
            tmp.replace(dst)
            return True
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        if logger:
            logger.warning("Foto kan niet worden verwerkt en wordt overgeslagen: %s (%s)", src, exc)
        return False


def prepare_photo_cache(files: List[str], config: Dict, logger=None) -> List[str]:
    """Zet USB-foto's om naar Pi-vriendelijke JPEG-cachebestanden.

    Waarom:
    - Grote telefoonfoto's/progressive JPEG/PNG/WebP kunnen op Pi 2/3 via mpv groene blokken
      of zwarte schermen geven.
    - Een vaste 1280x720 RGB JPEG is veel lichter en stabieler voor de slideshow.
    """
    ss = config.get("usb_slideshow", {})
    cache_cfg = ss.get("image_cache", {})
    if not cache_cfg.get("enabled", True):
        return files

    max_width = int(cache_cfg.get("max_width", 1280))
    max_height = int(cache_cfg.get("max_height", 720))
    quality = int(cache_cfg.get("quality", 88))
    cache_dir = Path(cache_cfg.get("cache_dir", "/var/lib/piviewer-dev/photo-cache"))
    cache_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = cache_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    except Exception:
        manifest = {}

    result: List[str] = []
    updated = False

    for raw in files:
        src = Path(raw)
        try:
            stat = src.stat()
        except OSError:
            continue

        cache_name = _safe_cache_name(src, stat)
        dst = cache_dir / cache_name
        key = str(src)
        expected = {
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
            "cache": str(dst),
            "max_width": max_width,
            "max_height": max_height,
            "quality": quality,
        }

        if dst.exists() and manifest.get(key) == expected:
            result.append(str(dst))
            continue

        if _normalise_image(src, dst, max_width, max_height, quality, logger):
            manifest[key] = expected
            result.append(str(dst))
            updated = True
        else:
            # Als conversie niet kan, gebruik origineel als fallback.
            result.append(str(src))

    if updated:
        try:
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except OSError:
            pass

    if logger and result:
        logger.info("USB Photo Viewer gebruikt %s Pi-vriendelijke cachefoto's", len(result))
    return result
