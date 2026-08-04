import os
import signal
import sys
import time
from pathlib import Path

from config import ConfigManager, DEFAULT_CONFIG, ConfigError
from logger import setup_logger
from player import PlayerManager
from scheduler import find_active_schedule
from slideshow import find_photos
from state import RuntimeState
from web import PiViewerWeb
from usbmedia import ensure_usb_mounts
from usb_wifi import apply_usb_wifi_configs
from usb_update import check_usb_auto_update, cleanup_stale_update_state
from web_update import check_web_auto_update, cleanup_stale_web_update_state
from networkcheck import internet_available, last_network_reason

APP_VERSION = Path("/opt/piviewer-dev/VERSION").read_text(encoding="utf-8").strip() if Path("/opt/piviewer-dev/VERSION").exists() else "PiViewer 2027"
CONFIG_PATH = os.environ.get("PIVIEWER_CONFIG", DEFAULT_CONFIG)
LOG_DIR = "/var/log/piviewer-dev"
STATE_FILE = "/var/lib/piviewer-dev/state.json"

running = True


def handle_signal(signum, frame):
    global running
    running = False


def attach_player_options(source, config):
    source["_player"] = dict(config.get("player", {}))
    return source


def build_main_source(config):
    main = dict(config["main_stream"])
    main["id"] = "main_stream"
    return attach_player_options(main, config)


def build_scheduled_source(rule, config):
    stream = dict(rule["stream"])
    stream["id"] = rule.get("id", "scheduled_stream")
    stream["name"] = rule.get("name", stream.get("name", stream["id"]))
    return attach_player_options(stream, config)


def build_slideshow_source(config, photos):
    ss = config.get("usb_slideshow", {})
    return attach_player_options({
        "id": "usb_slideshow",
        "name": "USB slideshow",
        "type": "slideshow",
        "files": photos,
        "duration_seconds": ss.get("duration_seconds", 5),
        "random": ss.get("random", True),
    }, config)



def build_system_image_source(config, image_name="nossid.png", message="Netwerk niet beschikbaar"):
    system_cfg = config.get("system_images", {})
    assets_dir = system_cfg.get("assets_dir", "/opt/piviewer-dev/assets")
    path = Path(assets_dir) / image_name
    return attach_player_options({
        "id": "system_nossid",
        "name": message,
        "type": "slideshow",
        "files": [str(path)],
        "duration_seconds": 3600,
        "random": False,
    }, config)


def source_requires_network(source):
    return source.get("type") in ("hls", "twitch")

def determine_source(config, logger, state):
    active_rule = find_active_schedule(config)
    if active_rule:
        state.update(schedule_active=True)
        return build_scheduled_source(active_rule, config)

    photos = find_photos(config, logger)
    state.update(schedule_active=False, usb_photos=len(photos))
    if photos:
        return build_slideshow_source(config, photos)

    return build_main_source(config)



def determine_fallback_source(config, state):
    """Kies een veilige fallback zonder de actieve planning opnieuw te forceren."""
    photos = find_photos(config, None)
    state.update(schedule_active=False, usb_photos=len(photos))
    if photos:
        return build_slideshow_source(config, photos)
    return build_main_source(config)

def main():
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    cfg = ConfigManager(CONFIG_PATH)
    try:
        config = cfg.load()
    except ConfigError as exc:
        print(f"PiViewer configuratiefout: {exc}", file=sys.stderr)
        sys.exit(1)

    logs = config.get("logs", {})
    logger = setup_logger(
        "piviewer-dev",
        LOG_DIR,
        logs.get("level", "INFO"),
        int(logs.get("max_file_mb", 2)),
        int(logs.get("backup_count", 3)),
    )
    state = RuntimeState(STATE_FILE)
    cleanup_stale_update_state(logger)
    cleanup_stale_web_update_state(logger)
    state.update(
        version=APP_VERSION,
        mode="starting",
        source_id="",
        source_name="",
        source_type="",
        status="starting",
        message="PiViewer wordt gestart; oude update-status opgeschoond",
        player_pid=None,
    )

    web_config = config.get("web", {})
    web = None
    if web_config.get("enabled", True):
        web = PiViewerWeb(web_config.get("host", "0.0.0.0"), int(web_config.get("port", 8080)), state, CONFIG_PATH, logger)
        web.start()

    player = PlayerManager(logger, state, APP_VERSION)
    tick = int(config.get("player", {}).get("scheduler_tick_seconds", 5))
    reload_after = int(config.get("player", {}).get("config_reload_seconds", 10))
    last_reload_check = 0
    logger.info("PiViewer %s gestart met config %s", APP_VERSION, CONFIG_PATH)

    try:
        while running:
            # Eerst controleren of de huidige speler onverwacht is gestopt.
            # Belangrijk: zonder deze check werd een geplande bron die direct stopt
            # steeds opnieuw gestart voordat hij als gefaald werd gemarkeerd.
            # Daardoor bleef het HDMI-scherm op de Debian-login staan tijdens de hele planning.
            player.check_process()

            now = time.time()
            if now - last_reload_check >= reload_after:
                last_reload_check = now
                try:
                    if cfg.reload_if_changed():
                        config = cfg.data
                        logger.info("Configuratie opnieuw geladen")
                except ConfigError as exc:
                    logger.error("Configuratie reload mislukt: %s", exc)
                    state.update(status="config_error", message=str(exc))

            # USB beheer: WiFi.txt en automatische update werken ook zonder foto's op USB.
            usb_mounts = ensure_usb_mounts(config, logger)
            apply_usb_wifi_configs(config, logger, usb_mounts)
            if check_usb_auto_update(config, logger, usb_mounts, APP_VERSION):
                state.update(status="updating", message="Hogere PiViewer-versie op USB gevonden; auto-update gestart")
                time.sleep(30)
                continue

            # Web-update is een extra updatekanaal. USB-update houdt altijd prioriteit.
            if check_web_auto_update(config, logger, APP_VERSION):
                state.update(status="updating", message="Hogere PiViewer-versie op raysnijder.nl gevonden; web-update gestart")
                time.sleep(30)
                continue

            source = determine_source(config, logger, state)
            if source_requires_network(source) and not internet_available(config, logger):
                reason = last_network_reason()
                logger.warning("Streambron vraagt netwerk maar internet is niet beschikbaar; nossid.png wordt getoond: %s", reason)
                state.update(status="network_error", message="WiFi/netwerk niet beschikbaar", network_error=reason)
                source = build_system_image_source(config, "nossid.png", "WiFi/netwerk fout")
            source_id = source.get("id") or source.get("name") or source.get("url") or "unknown"
            cooldown = int(config.get("player", {}).get("failed_source_cooldown_seconds", 60))
            if (
                player.last_failed_source_id == source_id
                and player.last_failed_at
                and time.time() - player.last_failed_at < cooldown
            ):
                logger.warning("Bron %s is net gefaald; tijdelijk fallback gebruiken", source_id)
                source = determine_fallback_source(config, state)
            logger.info("Broncontrole: gekozen bron=%s type=%s naam=%s", source.get("id"), source.get("type"), source.get("name"))
            player.ensure_source(source)
            time.sleep(tick)
    finally:
        logger.info("PiViewer stopt")
        player.stop()
        if web:
            web.stop()
        state.update(status="stopped", message="PiViewer gestopt")


if __name__ == "__main__":
    main()
