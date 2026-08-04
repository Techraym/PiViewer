import os
import random
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class PlayerManager:
    def __init__(self, logger, state, app_version: str = "PiViewer 2027"):
        self.logger = logger
        self.state = state
        self.app_version = app_version
        self.process: Optional[subprocess.Popen] = None
        self.current_source_id: Optional[str] = None
        self.current_source_type: Optional[str] = None
        self.last_failed_source_id: Optional[str] = None
        self.last_failed_at: float = 0.0
        self.last_exit_code: Optional[int] = None

    def stop(self) -> None:
        old_source_type = self.current_source_type
        if self.process and self.process.poll() is None:
            self.logger.info("Stop huidige speler pid=%s", self.process.pid)
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.logger.warning("Speler reageert niet op terminate, kill wordt gebruikt")
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                except Exception:
                    self.process.kill()
            except ProcessLookupError:
                pass
            except Exception as exc:
                self.logger.error("Fout bij stoppen speler: %s", exc)

        self.process = None
        self.current_source_id = None
        self.current_source_type = None
        self.state.update(player_pid=None)

        # PiViewer 2030:
        # Als een USB-slideshow stopt, blijft /dev/fb0 soms de laatste foto vasthouden.
        # Dat is verwarrend wanneer de USB-stick verwijderd is en de main stream terug moet komen.
        # Daarom wissen we alleen na slideshow-stop kort het framebufferbeeld.
        if old_source_type == "slideshow":
            self._clear_framebuffer()

    def _clear_framebuffer(self) -> None:
        fb_path = "/dev/fb0"
        try:
            size = os.path.getsize(fb_path)
        except Exception:
            size = 8 * 1024 * 1024

        try:
            with open(fb_path, "wb", buffering=0) as fb:
                chunk = b"\x00" * 1048576
                remaining = size
                while remaining > 0:
                    n = min(len(chunk), remaining)
                    fb.write(chunk[:n])
                    remaining -= n
            self.logger.info("Framebuffer gewist na stoppen slideshow")
        except Exception as exc:
            self.logger.debug("Framebuffer wissen overgeslagen: %s", exc)

    def ensure_source(self, source: Dict[str, Any]) -> None:
        source_id = source.get("id") or source.get("name") or source.get("url") or "unknown"
        if self.current_source_id == source_id and self.process and self.process.poll() is None:
            return
        self.stop()
        self.start(source)

    def start(self, source: Dict[str, Any]) -> None:
        stype = source.get("type", "hls")
        source_id = source.get("id") or source.get("name") or source.get("url") or "unknown"
        self.current_source_id = source_id
        self.current_source_type = stype
        if stype == "twitch":
            cmd = self._twitch_cmd(source)
            if not cmd:
                self.logger.error("Twitch bron '%s' kon geen HLS-url ophalen; bron wordt als gefaald gemarkeerd", source_id)
                self.last_failed_source_id = source_id
                self.last_failed_at = time.time()
                self.last_exit_code = -1
                self.current_source_id = None
                self.current_source_type = None
                self.state.update(status="failed", message="Twitch HLS-url ophalen mislukt; fallback wordt geprobeerd", last_failed_source=source_id, last_exit_code=-1)
                return
        elif stype == "slideshow":
            cmd = self._slideshow_cmd(source)
        else:
            cmd = self._hls_cmd(source)
        self.logger.info("Start bron '%s' met commando: %s", source_id, " ".join(cmd))
        log_path = Path("/var/log/piviewer-dev/player-output.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(log_path, "ab", buffering=0)
        header = f"\n===== {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} START {source_id} =====\n"
        log_handle.write(header.encode("utf-8"))
        self.process = subprocess.Popen(cmd, stdout=log_handle, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        self.state.update(
            mode=stype,
            source_id=source_id,
            source_name=source.get("name", source_id),
            source_type=stype,
            status="playing",
            message="Bron gestart",
            last_change=time.strftime("%Y-%m-%d %H:%M:%S"),
            player_pid=self.process.pid,
        )

    def check_process(self) -> bool:
        if not self.process:
            return False
        code = self.process.poll()
        if code is None:
            return True
        failed_id = self.current_source_id
        self.logger.warning("Speler is gestopt met exitcode %s voor bron %s", code, failed_id)
        self.last_failed_source_id = failed_id
        self.last_failed_at = time.time()
        self.last_exit_code = int(code) if code is not None else None
        self.state.update(status="stopped", message=f"Speler gestopt met exitcode {code}; fallback wordt geprobeerd", player_pid=None, last_failed_source=failed_id, last_exit_code=code)
        self.process = None
        self.current_source_id = None
        self.current_source_type = None
        return False

    def _player_options(self, source: Dict[str, Any]) -> Dict[str, Any]:
        return source.get("_player", {}) or {}


    def _display_bar_settings(self, source: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        opts = self._player_options(source or {})
        raw = opts.get("display_bar", {})
        if raw is False:
            return {"enabled": False}
        if raw is True or not isinstance(raw, dict):
            raw = {}
        return {
            "enabled": bool(raw.get("enabled", True)),
            "height": int(raw.get("height", 32)),
            "font_size": int(raw.get("font_size", 15)),
            "title": str(raw.get("title", "PiViewer by Techraym")),
            "show_seconds": bool(raw.get("show_seconds", True)),
        }

    def _topbar_mpv_args(self, source: Optional[Dict[str, Any]] = None) -> List[str]:
        """Statusbalk voor streamweergave.

        PiViewer 2027 gebruikt bewust geen mpv ass-events/Lua overlay meer voor streams.
        Op sommige Raspberry Pi/mpv combinaties werden ASS-events letterlijk als tekst
        getoond, bijvoorbeeld: "Dialogue: 1,0:00:00...".

        Daarom tekenen we de balk direct in het videobeeld met FFmpeg lavfi drawbox/drawtext.
        Dit is minder gevoelig voor mpv-OSD/subtitle verschillen en blijft ook bij HLS-streams
        zichtbaar op dezelfde plek.
        """
        bar = self._display_bar_settings(source)
        if not bar.get("enabled", True):
            return ["--no-sub", "--sub-auto=no", "--sid=no"]

        def ff_text(value: str) -> str:
            value = str(value or "")
            # Beperk tot veilige tekst voor ffmpeg drawtext.
            value = value.replace("\\", "")
            value = value.replace("'", "")
            value = value.replace(":", "\\:")
            value = value.replace("\n", " ").replace("\r", " ")
            return value

        height = max(28, min(int(bar.get("height", 34)), 56))
        font_size = max(10, min(int(bar.get("font_size", 14)), height - 8))
        margin = 14
        font_file = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        title = ff_text(bar.get("title", "PiViewer by Techraym"))
        version = ff_text(self.app_version)
        time_text = "%{localtime\\:%T}" if bar.get("show_seconds", True) else "%{localtime\\:%H\\:%M}"
        y_expr = f"({height}-text_h)/2"

        filters = [
            f"drawbox=x=0:y=0:w=iw:h={height}:color=black@0.82:t=fill",
            f"drawtext=fontfile={font_file}:text='{time_text}':x={margin}:y={y_expr}:fontsize={font_size}:fontcolor=white",
            f"drawtext=fontfile={font_file}:text='{title}':x=(w-text_w)/2:y={y_expr}:fontsize={font_size}:fontcolor=white",
            f"drawtext=fontfile={font_file}:text='{version}':x=w-text_w-{margin}:y={y_expr}:fontsize={font_size}:fontcolor=white",
        ]
        graph = ",".join(filters)
        return [
            "--no-sub",
            "--sub-auto=no",
            "--sid=no",
            f"--vf-add=lavfi=[{graph}]",
        ]

    def _base_mpv_args(self, source: Optional[Dict[str, Any]] = None) -> List[str]:
        """
        Instelbaar mpv-profiel.

        Waarom:
        - Pi 3B test mag betere beeldkwaliteit gebruiken.
        - Pi 2 doelinstallatie moet lichter kunnen draaien.
        - Beeldkwaliteit mag niet hard op minimum worden gezet.

        quality_profile:
        - pi2_lite: laag CPU/RAM, lagere HLS-variant, geen audio.
        - balanced: beter beeld, nog steeds redelijk licht.
        - quality: beste HLS-variant voor testen op Pi 3B.
        """
        opts = self._player_options(source or {})
        profile = str(opts.get("quality_profile", "balanced")).lower().strip()

        if profile == "pi2_lite":
            defaults = {
                "readahead_seconds": 10,
                "max_cache_mb": 16,
                "hls_bitrate": "min",
                "audio_enabled": False,
                "scale_mode": "bilinear",
                "video_sync": "audio",
            }
        elif profile == "quality":
            defaults = {
                "readahead_seconds": 20,
                "max_cache_mb": 32,
                "hls_bitrate": "max",
                "audio_enabled": True,
                "scale_mode": "spline36",
                "video_sync": "display-resample",
            }
        else:
            defaults = {
                "readahead_seconds": 15,
                "max_cache_mb": 24,
                "hls_bitrate": "max",
                "audio_enabled": False,
                "scale_mode": "bilinear",
                "video_sync": "audio",
            }

        readahead = int(opts.get("readahead_seconds", defaults["readahead_seconds"]))
        cache_mb = int(opts.get("max_cache_mb", defaults["max_cache_mb"]))
        network_timeout = int(opts.get("network_timeout_seconds", 10))
        hls_bitrate = str(opts.get("hls_bitrate", defaults["hls_bitrate"]))
        audio_enabled = bool(opts.get("audio_enabled", defaults["audio_enabled"]))
        scale_mode = str(opts.get("scale_mode", defaults["scale_mode"]))
        video_sync = str(opts.get("video_sync", defaults["video_sync"]))

        args = [
            "mpv",
            "--fs",
            "--no-terminal",
            "--input-terminal=no",
            "--really-quiet",
            "--cache=yes",
            f"--demuxer-readahead-secs={readahead}",
            f"--demuxer-max-bytes={cache_mb}MiB",
            f"--network-timeout={network_timeout}",
            f"--hls-bitrate={hls_bitrate}",
            "--hwdec=auto-safe",
            "--vd-lavc-fast",
            "--framedrop=vo",
            f"--video-sync={video_sync}",
            "--interpolation=no",
            f"--scale={scale_mode}",
            f"--cscale={scale_mode}",
            f"--dscale={scale_mode}",
        ]
        args.extend(self._topbar_mpv_args(source))
        if audio_enabled:
            args.append("--ao=alsa")
        else:
            args.append("--no-audio")
        return args

    def _hls_cmd(self, source: Dict[str, Any]) -> List[str]:
        return self._base_mpv_args(source) + [source["url"]]

    def _twitch_cmd(self, source: Dict[str, Any]) -> List[str]:
        """
        Twitch wordt bewust NIET meer gestart met:
            streamlink --player mpv ...

        Op Raspberry Pi/console sluit mpv dan soms direct af doordat streamlink via stdin
        naar mpv pipet. De stabiele methode is:
            1. streamlink --stream-url haalt de echte tijdelijke HLS-url op
            2. mpv speelt die HLS-url direct af met terminal-input uit
        """
        channel = source.get("channel")
        url = source.get("url", "")
        if not channel and url.startswith("twitch://"):
            channel = url.replace("twitch://", "", 1)
        if not channel and "twitch.tv/" in url:
            channel = url.rstrip("/").split("/")[-1]
        if not channel:
            self.logger.error("Twitch bron mist kanaal: %s", source)
            return []

        twitch_url = f"https://www.twitch.tv/{channel}"
        quality = source.get("quality", "360p")

        try:
            self.logger.info("Twitch HLS-url ophalen via streamlink: %s kwaliteit=%s", twitch_url, quality)
            result = subprocess.run(
                ["streamlink", "--stream-url", twitch_url, quality],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=25,
                check=False,
            )
        except Exception as exc:
            self.logger.error("Streamlink kon Twitch HLS-url niet ophalen: %s", exc)
            return []

        if result.returncode != 0:
            self.logger.error("Streamlink fout voor %s: %s", twitch_url, (result.stderr or result.stdout).strip())
            return []

        hls_url = (result.stdout or "").strip().splitlines()[-1].strip()
        if not hls_url.startswith("http"):
            self.logger.error("Streamlink gaf geen geldige HLS-url terug voor %s: %r", twitch_url, hls_url)
            return []

        self.logger.info("Twitch HLS-url opgehaald voor %s; mpv speelt directe HLS-url", channel)
        return self._base_mpv_args(source) + [hls_url]

    def _slideshow_mpv_args(self, source: Dict[str, Any]) -> List[str]:
        """Lichte en stabiele mpv-argumenten voor foto's.

        Foto's zijn vooraf omgezet naar 1280x720 RGB JPEG-cachebestanden. Daarom gebruiken we
        bewust geen hwdec/hls/netwerkopties. Dit voorkomt groene blokken of zwart beeld op Pi 2/3.
        """
        opts = self._player_options(source or {})
        scale_mode = str(opts.get("scale_mode", "bilinear"))
        return [
            "mpv",
            "--fs",
            "--no-terminal",
            "--input-terminal=no",
            "--really-quiet",
            "--no-audio",
            "--cache=no",
            "--hwdec=no",
            "--video-sync=audio",
            "--interpolation=no",
            f"--scale={scale_mode}",
            f"--cscale={scale_mode}",
            f"--dscale={scale_mode}",
        ]

    def _slideshow_cmd(self, source: Dict[str, Any]) -> List[str]:
        files = source.get("files", [])
        if source.get("random", True):
            random.shuffle(files)
        playlist = Path("/var/lib/piviewer-dev/slideshow.m3u")
        playlist.parent.mkdir(parents=True, exist_ok=True)
        playlist.write_text("\n".join(files) + "\n", encoding="utf-8")
        duration = int(source.get("duration_seconds", 5))

        # USB Photo Viewer gebruikt vanaf 2.0.12 een eigen framebuffer-renderer.
        # fbi toonde de foto's goed, maar gaf tussen beelden een zwart scherm / console-doorbraak.
        # De framebuffer-runner houdt het actieve beeld vast en schrijft periodiek opnieuw naar /dev/fb0.
        cmd = [
            "python3",
            "/opt/piviewer-dev/app/framebuffer_slideshow_runner.py",
            "--playlist", str(playlist),
            "--duration", str(duration),
            "--fb", "/dev/fb0",
            "--vt", "1",
            "--refresh-hold", "0.5",
            "--topbar-version", self.app_version,
        ]
        bar = self._display_bar_settings(source)
        if not bar.get("enabled", True):
            cmd.append("--no-topbar")
        else:
            cmd += [
                "--topbar-title", str(bar.get("title", "PiViewer by Techraym")),
                "--topbar-height", str(bar.get("height", 28)),
                "--topbar-font-size", str(bar.get("font_size", 16)),
            ]
            if not bar.get("show_seconds", True):
                cmd.append("--topbar-no-seconds")
        if source.get("random", True):
            cmd.append("--shuffle")
        return cmd
