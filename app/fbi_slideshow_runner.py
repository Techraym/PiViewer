#!/usr/bin/env python3
"""Lichte USB Photo Viewer voor PiViewer.

Versie 2.0.11:
- fbi wordt niet meer per foto opnieuw gestart.
- Eén fbi-proces krijgt de volledige fotolijst en wisselt zelf door.
- Daardoor verschijnt het Debian/root login-scherm niet meer tussen foto's.
"""
import argparse
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path

running = True
current = None


def stop_child():
    global current
    if current and current.poll() is None:
        try:
            os.killpg(os.getpgid(current.pid), signal.SIGTERM)
            current.wait(timeout=2.0)
        except Exception:
            try:
                os.killpg(os.getpgid(current.pid), signal.SIGKILL)
            except Exception:
                pass
    current = None


def handle_signal(signum, frame):
    global running
    running = False
    stop_child()


def read_playlist(path: Path):
    if not path.exists():
        return []
    files = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and Path(line).exists():
            files.append(line)
    return files


def build_fbi_cmd(files, duration, vt, shuffle=False):
    ordered = list(files)
    if shuffle:
        random.shuffle(ordered)

    # fbi slideshow-opties:
    # -T 1       gebruik virtuele terminal 1
    # -a         auto-fit binnen scherm
    # -noverbose geen tekstoverlay
    # -t N       wissel zelf elke N seconden
    # Belangrijk: alle foto's in één fbi-proces meegeven. Niet per foto herstarten.
    cmd = [
        "fbi",
        "-T", str(vt),
        "-a",
        "-noverbose",
        "-t", str(max(1, int(duration))),
    ]
    if shuffle:
        # fbi ondersteunt -u voor random volgorde op veel Debian/Raspberry Pi builds.
        # Als een build dit niet ondersteunt, valt fbi terug met foutcode en proberen we zonder -u.
        cmd.append("-u")
    cmd.extend(ordered)
    return cmd


def launch_fbi(files, duration, vt, shuffle):
    global current
    cmd = build_fbi_cmd(files, duration, vt, shuffle)
    try:
        current = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        return True
    except FileNotFoundError:
        print("fbi ontbreekt. Installeer met: sudo apt install -y fbi", file=sys.stderr, flush=True)
        return False
    except Exception as exc:
        print(f"Kan fbi niet starten: {exc}", file=sys.stderr, flush=True)
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--playlist", required=True)
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--vt", default="1")
    parser.add_argument("--shuffle", action="store_true")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    playlist = Path(args.playlist)
    files = read_playlist(playlist)
    if not files:
        print("Geen foto's in slideshow-playlist", file=sys.stderr, flush=True)
        return 2

    # Console één keer leegmaken; daarna blijft fbi actief en houdt het beeld vast.
    subprocess.run(["/usr/bin/clear"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    last_signature = None
    while running:
        files_now = read_playlist(playlist) or files
        signature = (tuple(files_now), int(args.duration), str(args.vt), bool(args.shuffle))

        # Alleen opnieuw starten als fbi niet draait of de playlist is veranderd.
        if current is None or current.poll() is not None or signature != last_signature:
            stop_child()
            files = files_now
            last_signature = signature
            ok = launch_fbi(files, args.duration, args.vt, args.shuffle)
            if not ok:
                return 127

            # Als fbi direct faalt door -u, probeer zonder shuffle-optie.
            time.sleep(0.8)
            if current and current.poll() is not None and args.shuffle:
                stop_child()
                ok = launch_fbi(files, args.duration, args.vt, False)
                if not ok:
                    return 127

        time.sleep(1.0)

    stop_child()
    return 0


if __name__ == "__main__":
    sys.exit(main())
