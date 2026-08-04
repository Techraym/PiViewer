import json
import time
from pathlib import Path
from threading import Lock
from typing import Any, Dict


class RuntimeState:
    def __init__(self, state_file: str = "/var/lib/piviewer-dev/state.json"):
        self.state_file = Path(state_file)
        self.lock = Lock()
        self.data: Dict[str, Any] = {
            "version": "unknown",
            "mode": "starting",
            "source_id": None,
            "source_name": None,
            "source_type": None,
            "status": "starting",
            "message": "PiViewer start",
            "last_change": time.strftime("%Y-%m-%d %H:%M:%S"),
            "player_pid": None,
            "usb_photos": 0,
            "schedule_active": False,
        }
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.write()

    def update(self, **kwargs: Any) -> None:
        with self.lock:
            self.data.update(kwargs)
            self.data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.write_locked()

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return dict(self.data)

    def write(self) -> None:
        with self.lock:
            self.write_locked()

    def write_locked(self) -> None:
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.state_file)
