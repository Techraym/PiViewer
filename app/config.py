import json
import os
from pathlib import Path
from typing import Any, Dict

DEFAULT_CONFIG = "/etc/piviewer-dev/piviewer.json"


class ConfigError(Exception):
    pass


class ConfigManager:
    def __init__(self, path: str = DEFAULT_CONFIG):
        self.path = Path(path)
        self._mtime = 0.0
        self.data: Dict[str, Any] = {}

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            raise ConfigError(f"Configuratiebestand niet gevonden: {self.path}")
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Ongeldige JSON in {self.path}: {exc}") from exc
        self._validate(data)
        self.data = data
        self._mtime = self.path.stat().st_mtime
        return self.data

    def reload_if_changed(self) -> bool:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            raise ConfigError(f"Configuratiebestand niet gevonden: {self.path}")
        if mtime != self._mtime:
            self.load()
            return True
        return False

    def _validate(self, data: Dict[str, Any]) -> None:
        if "main_stream" not in data:
            raise ConfigError("main_stream ontbreekt in configuratie")
        main = data["main_stream"]
        if not main.get("url"):
            raise ConfigError("main_stream.url ontbreekt")
        if "player" not in data:
            raise ConfigError("player ontbreekt in configuratie")
        if "web" not in data:
            data["web"] = {"enabled": True, "host": "0.0.0.0", "port": 8080}

    @property
    def mtime(self) -> float:
        return self._mtime
