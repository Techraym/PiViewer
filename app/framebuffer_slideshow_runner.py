#!/usr/bin/env python3
"""PiViewer USB Photo Viewer - directe framebuffer slideshow.

Versie 2028:
- Geen mpv voor foto's.
- Tekent beelden direct naar /dev/fb0.
- De statusbalkklok wordt volledig losgekoppeld van de fotowissel.
- Elke seconde wordt alleen de bovenste statusbalk opnieuw naar de framebuffer
  geschreven; de foto zelf blijft staan tot de ingestelde fotoduur voorbij is.
"""
import argparse
import os
import random
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except Exception as exc:
    print(f"Pillow ontbreekt of kan niet laden: {exc}", file=sys.stderr, flush=True)
    sys.exit(127)

running = True


def handle_signal(signum, frame):
    global running
    running = False


def read_int(path: Path, default: int) -> int:
    try:
        return int(path.read_text().strip())
    except Exception:
        return default


def read_virtual_size(fb_name: str):
    p = Path(f"/sys/class/graphics/{fb_name}/virtual_size")
    try:
        raw = p.read_text().strip()
        w, h = raw.split(',')[:2]
        return int(w), int(h)
    except Exception:
        return 1280, 720


def read_bpp(fb_name: str):
    return read_int(Path(f"/sys/class/graphics/{fb_name}/bits_per_pixel"), 16)


def read_stride(fb_name: str, width: int, bpp: int) -> int:
    """Aantal bytes per framebuffer-regel.

    Niet elke Pi-kernel exposeert dezelfde sysfs-naam. Als er geen stride te
    lezen is, gebruiken we width * bytes_per_pixel. Dat is correct voor de
    standaard Pi framebuffer-configuratie.
    """
    for name in ("stride", "line_length"):
        value = read_int(Path(f"/sys/class/graphics/{fb_name}/{name}"), 0)
        if value > 0:
            return value
    return width * max(1, bpp // 8)


def clear_console(vt: str):
    tty = Path(f"/dev/tty{vt}")
    try:
        subprocess.run(["systemctl", "stop", f"getty@tty{vt}.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except Exception:
        pass
    try:
        with tty.open("wb", buffering=0) as out:
            out.write(b"\033[?25l\033[2J\033[H")
    except Exception:
        pass


def read_playlist(path: Path):
    if not path.exists():
        return []
    files = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and Path(line).exists():
            files.append(line)
    return files


def fit_image(path: str, width: int, height: int, bg=(0, 0, 0)) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")

    if img.width > 0 and img.height > 0:
        scale = min(width / img.width, height / img.height)
        new_w = max(1, int(img.width * scale))
        new_h = max(1, int(img.height * scale))
        if (new_w, new_h) != img.size:
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", (width, height), bg)
    x = (width - img.width) // 2
    y = (height - img.height) // 2
    canvas.paste(img, (x, y))
    return canvas


def load_font(size: int):
    for font_path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            if Path(font_path).exists():
                return ImageFont.truetype(font_path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]
    except Exception:
        return len(text) * 8


def render_topbar(width: int, height: int, title: str, version: str, font_size: int = 15, show_seconds: bool = True) -> Image.Image:
    """Maak alleen de zwarte statusbalk als losse afbeelding."""
    height = max(24, int(height))
    font_size = max(10, min(int(font_size), height - 6))
    bar = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(bar)
    font = load_font(font_size)
    now = datetime.now().strftime("%H:%M:%S" if show_seconds else "%H:%M")

    y = max(1, (height - font_size) // 2 - 1)
    margin = 12

    # Links: tijd.
    draw.text((margin, y), now, font=font, fill=(255, 255, 255))

    # Midden: vaste titel, exact gecentreerd.
    title_w = _text_width(draw, title, font)
    draw.text((max(margin, (width - title_w) // 2), y), title, font=font, fill=(255, 255, 255))

    # Rechts: actuele versie.
    version_w = _text_width(draw, version, font)
    draw.text((max(margin, width - version_w - margin), y), version, font=font, fill=(255, 255, 255))
    return bar


def draw_topbar(img: Image.Image, title: str, version: str, height: int = 32, font_size: int = 15, show_seconds: bool = True) -> Image.Image:
    """Teken de PiViewer infobalk bovenop een foto."""
    img = img.copy()
    w, _ = img.size
    bar = render_topbar(w, height, title, version, font_size, show_seconds)
    img.paste(bar, (0, 0))
    return img


def rgb565_bytes(img: Image.Image) -> bytes:
    data = bytearray()
    pix = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b = pix[x, y]
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            data.append(v & 0xFF)
            data.append((v >> 8) & 0xFF)
    return bytes(data)


def bgrx_bytes(img: Image.Image) -> bytes:
    raw = bytearray()
    for r, g, b in img.getdata():
        raw.extend((b, g, r, 0))
    return bytes(raw)


def image_to_frame_bytes(img: Image.Image, bpp: int) -> bytes:
    if bpp == 16:
        return rgb565_bytes(img)
    if bpp == 32:
        return bgrx_bytes(img)
    return bgrx_bytes(img)


def write_frame(fbdev: Path, frame: bytes):
    with fbdev.open("r+b", buffering=0) as fb:
        fb.seek(0)
        fb.write(frame)


def write_topbar(fbdev: Path, bar: Image.Image, bpp: int, stride: int):
    """Schrijf alleen de bovenste statusbalk naar de framebuffer.

    Hierdoor kan de klok elke seconde lopen zonder dat de volledige foto opnieuw
    geconverteerd en geschreven hoeft te worden. Dat is veel lichter voor de Pi 2.
    """
    row_bytes = image_to_frame_bytes(bar, bpp)
    bytes_per_pixel = max(1, bpp // 8)
    width_bytes = bar.width * bytes_per_pixel
    if stride <= width_bytes:
        with fbdev.open("r+b", buffering=0) as fb:
            fb.seek(0)
            fb.write(row_bytes)
        return

    with fbdev.open("r+b", buffering=0) as fb:
        for y in range(bar.height):
            start = y * width_bytes
            end = start + width_bytes
            fb.seek(y * stride)
            fb.write(row_bytes[start:end])


def prepare_base_image(path: str, width: int, height: int) -> Image.Image:
    return fit_image(path, width, height)


def prepare_frame(path: str, width: int, height: int, bpp: int, topbar: bool = True, topbar_title: str = "PiViewer by Techraym", topbar_version: str = "PiViewer", topbar_height: int = 28, topbar_font_size: int = 16, topbar_seconds: bool = True) -> bytes:
    img = prepare_base_image(path, width, height)
    if topbar:
        img = draw_topbar(img, topbar_title, topbar_version, topbar_height, topbar_font_size, topbar_seconds)
    return image_to_frame_bytes(img, bpp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--playlist", required=True)
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--fb", default="/dev/fb0")
    parser.add_argument("--vt", default="1")
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--refresh-hold", type=float, default=0.5, help="Controle-/klokinterval voor de statusbalk")
    parser.add_argument("--full-refresh-seconds", type=float, default=30.0, help="Schrijf het volledige frame periodiek opnieuw; 0 schakelt dit uit")
    parser.add_argument("--no-topbar", action="store_true")
    parser.add_argument("--topbar-title", default="PiViewer by Techraym")
    parser.add_argument("--topbar-version", default="PiViewer")
    parser.add_argument("--topbar-height", type=int, default=32)
    parser.add_argument("--topbar-font-size", type=int, default=15)
    parser.add_argument("--topbar-no-seconds", action="store_true")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    fbdev = Path(args.fb)
    if not fbdev.exists():
        print(f"Framebuffer ontbreekt: {fbdev}", file=sys.stderr, flush=True)
        return 2

    fb_name = fbdev.name
    width, height = read_virtual_size(fb_name)
    bpp = read_bpp(fb_name)
    stride = read_stride(fb_name, width, bpp)
    print(f"Framebuffer slideshow gestart: {fbdev} {width}x{height} {bpp}bpp stride={stride}", flush=True)

    clear_console(str(args.vt))

    last_playlist_sig = None
    files = []
    idx = 0
    current_base_image = None
    current_full_frame = None
    last_clock_text = None
    last_full_refresh = 0.0
    next_switch = 0.0

    while running:
        files_now = read_playlist(Path(args.playlist))
        sig = tuple(files_now)
        if sig != last_playlist_sig:
            files = list(files_now)
            if args.shuffle:
                random.shuffle(files)
            idx = 0
            current_base_image = None
            current_full_frame = None
            last_clock_text = None
            next_switch = 0.0
            last_playlist_sig = sig
            print(f"Playlist geladen: {len(files)} foto's", flush=True)

        if not files:
            time.sleep(1.0)
            continue

        now = time.time()
        need_new_photo = current_base_image is None or now >= next_switch
        if need_new_photo:
            path = files[idx % len(files)]
            try:
                current_base_image = prepare_base_image(path, width, height)
                last_clock_text = None
                print(f"Toon foto: {path}", flush=True)
            except Exception as exc:
                print(f"Foto overslaan {path}: {exc}", file=sys.stderr, flush=True)
                current_base_image = None
                idx += 1
                next_switch = now + 1.0
                time.sleep(1.0)
                continue
            idx += 1
            next_switch = now + max(1.0, float(args.duration))
            current_full_frame = None

        try:
            if current_base_image is not None:
                if args.no_topbar:
                    if current_full_frame is None or need_new_photo:
                        current_full_frame = image_to_frame_bytes(current_base_image, bpp)
                    write_frame(fbdev, current_full_frame)
                    last_full_refresh = now
                else:
                    clock_format = "%H:%M" if args.topbar_no_seconds else "%H:%M:%S"
                    clock_text = datetime.now().strftime(clock_format)

                    # Bij een nieuwe foto: volledig frame één keer tekenen.
                    if current_full_frame is None:
                        frame_img = draw_topbar(current_base_image, args.topbar_title, args.topbar_version, args.topbar_height, args.topbar_font_size, not args.topbar_no_seconds)
                        current_full_frame = image_to_frame_bytes(frame_img, bpp)
                        write_frame(fbdev, current_full_frame)
                        last_full_refresh = now
                        last_clock_text = clock_text
                    # Daarna elke seconde alleen de bovenste balk verversen.
                    elif clock_text != last_clock_text:
                        bar = render_topbar(width, args.topbar_height, args.topbar_title, args.topbar_version, args.topbar_font_size, not args.topbar_no_seconds)
                        write_topbar(fbdev, bar, bpp, stride)
                        last_clock_text = clock_text
                    # Periodiek volledig hertekenen als extra bescherming tegen console-doorbraak.
                    elif args.full_refresh_seconds > 0 and (now - last_full_refresh) >= float(args.full_refresh_seconds):
                        write_frame(fbdev, current_full_frame)
                        last_full_refresh = now
        except Exception as exc:
            print(f"Framebuffer refresh fout: {exc}", file=sys.stderr, flush=True)
            time.sleep(1.0)

        time.sleep(max(0.1, min(1.0, float(args.refresh_hold))))

    return 0


if __name__ == "__main__":
    sys.exit(main())
