#!/usr/bin/env python3
"""PiViewer update-status scherm.

Tekent een eenvoudige statusmelding direct naar /dev/fb0 zodat de gebruiker op HDMI
ziet dat een USB auto-update bezig is. Dit gebruikt geen X/desktop en is licht genoeg
voor Raspberry Pi 2.
"""
import argparse
from pathlib import Path
import subprocess
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception as exc:
    print(f"Pillow ontbreekt: {exc}", file=sys.stderr)
    sys.exit(127)


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


def font(size: int):
    for p in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def bgrx_bytes(img: Image.Image) -> bytes:
    raw = bytearray()
    for r, g, b in img.convert("RGB").getdata():
        raw.extend((b, g, r, 0))
    return bytes(raw)


def rgb565_bytes(img: Image.Image) -> bytes:
    data = bytearray()
    for r, g, b in img.convert("RGB").getdata():
        v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        data.append(v & 0xFF)
        data.append((v >> 8) & 0xFF)
    return bytes(data)


def wrap_text(draw, text, fnt, max_width):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), test, font=fnt)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = test
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render(width, height, title, lines):
    img = Image.new("RGB", (width, height), (23, 23, 23))
    draw = ImageDraw.Draw(img)
    title_font = font(max(28, min(width, height) // 16))
    body_font = font(max(18, min(width, height) // 30))
    small_font = font(max(14, min(width, height) // 42))

    margin = max(30, width // 24)
    y = max(35, height // 12)

    # Header bar
    draw.rectangle((0, 0, width, max(90, height // 7)), fill=(17, 17, 17))
    draw.text((margin, y // 2), "PiViewer", font=title_font, fill=(255, 255, 255))

    y = max(120, height // 5)
    draw.text((margin, y), title, font=title_font, fill=(255, 255, 255))
    y += int(title_font.size * 1.5)

    max_w = width - 2 * margin
    for line in lines:
        for wrapped in wrap_text(draw, line, body_font, max_w):
            draw.text((margin, y), wrapped, font=body_font, fill=(220, 220, 220))
            y += int(body_font.size * 1.45)
        y += int(body_font.size * 0.5)

    footer = "Schakel de Raspberry Pi niet uit en verwijder de USB-stick niet."
    draw.text((margin, height - margin - small_font.size), footer, font=small_font, fill=(180, 180, 180))
    return img


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fb", default="/dev/fb0")
    parser.add_argument("--vt", default="1")
    parser.add_argument("--title", default="Update wordt voorbereid")
    parser.add_argument("--current", default="")
    parser.add_argument("--new", default="")
    parser.add_argument("--zip", default="")
    parser.add_argument("--message", default="Een hogere PiViewer-versie is gevonden op USB.")
    args = parser.parse_args()

    fbdev = Path(args.fb)
    if not fbdev.exists():
        print(f"Framebuffer ontbreekt: {fbdev}", file=sys.stderr)
        return 2

    fb_name = fbdev.name
    width, height = read_virtual_size(fb_name)
    bpp = read_bpp(fb_name)
    clear_console(args.vt)

    lines = [args.message]
    if args.current:
        lines.append(f"Huidige versie: {args.current}")
    if args.new:
        lines.append(f"Nieuwe versie: {args.new}")
    if args.zip:
        lines.append(f"Updatebestand: {Path(args.zip).name}")
    lines.append("De installatie wordt automatisch uitgevoerd. Daarna start PiViewer opnieuw.")

    img = render(width, height, args.title, lines)
    if bpp == 16:
        frame = rgb565_bytes(img)
    else:
        frame = bgrx_bytes(img)
    with fbdev.open("r+b", buffering=0) as fb:
        fb.seek(0)
        fb.write(frame)
    return 0


if __name__ == "__main__":
    sys.exit(main())
