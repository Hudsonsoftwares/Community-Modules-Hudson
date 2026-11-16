"""Persistent agent configuration (server, device token, settings pushed from Odoo)."""
import json
import logging
import os
import sys
import threading
import uuid
from pathlib import Path

from . import APP_NAME

_logger = logging.getLogger(__name__)

# Settings the server may override. The type of each default is the type we coerce to.
DEFAULT_SETTINGS = {
    "tracking_enabled": True,   # server can pause tracking (e.g. outside work hours / not checked in)
    "sample_interval": 5,       # seconds between samples
    "idle_threshold": 300,      # seconds without input before the user counts as idle
    "upload_interval": 120,     # seconds between uploads
    "capture_titles": True,     # send window titles
    "private_apps": [],         # process names (e.g. "WhatsApp.exe") whose titles are never sent
    "max_title_length": 255,
    "allow_quit": True,         # show "Quit" in the tray menu
    "dashboard_url": "",        # "Open my activity" link in the tray menu
}

LIMITS = {
    "sample_interval": (1, 60),
    "idle_threshold": (30, 7200),
    "upload_interval": (15, 3600),
    "max_title_length": (0, 1024),
}

_data_dir_override = None


def set_data_dir(path):
    global _data_dir_override
    _data_dir_override = Path(path)


def data_dir() -> Path:
    if _data_dir_override:
        base_dir = _data_dir_override
    else:
        if sys.platform == "win32":
            base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        elif sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support"
        else:
            base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        base_dir = base / APP_NAME
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _coerce(key, value):
    default = DEFAULT_SETTINGS[key]
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, int):
        value = int(value)
        lo, hi = LIMITS.get(key, (value, value))
        return max(lo, min(hi, value))
    if isinstance(default, list):
        if not isinstance(value, (list, tuple)):
            raise ValueError("expected a list")
        return [str(v) for v in value]
    return str(value or "")


class Config:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / "config.json"
        self._lock = threading.RLock()
        self.server_url = ""
        self.database = ""
        self.token = ""
        self.device_uid = ""
        self.employee_name = ""
        self.settings = dict(DEFAULT_SETTINGS)
        self.load()

    # ------------------------------------------------------------------ io
    def load(self):
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except FileNotFoundError:
            data = {}
        except (OSError, ValueError):
            _logger.warning("Config file %s is unreadable, starting fresh", self.path)
            data = {}
        with self._lock:
            self.server_url = data.get("server_url", "")
            self.database = data.get("database", "")
            self.token = data.get("token", "")
            self.device_uid = data.get("device_uid", "")
            self.employee_name = data.get("employee_name", "")
            self.settings = dict(DEFAULT_SETTINGS)
            self._apply(data.get("settings") or {})
            if not self.device_uid:
                self.device_uid = str(uuid.uuid4())
                self.save()

    def save(self):
        with self._lock:
            data = {
                "server_url": self.server_url,
                "database": self.database,
                "token": self.token,
                "device_uid": self.device_uid,
                "employee_name": self.employee_name,
                "settings": self.settings,
            }
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), "utf-8")
            os.replace(tmp, self.path)

    # ------------------------------------------------------------- settings
    @property
    def paired(self) -> bool:
        return bool(self.server_url and self.token)

    def get(self, key):
        with self._lock:
            return self.settings.get(key, DEFAULT_SETTINGS[key])

    def _apply(self, remote: dict) -> bool:
        changed = False
        for key, value in remote.items():
            if key not in DEFAULT_SETTINGS:
                continue
            try:
                value = _coerce(key, value)
            except (TypeError, ValueError):
                _logger.warning("Ignoring invalid value for setting %s: %r", key, value)
                continue
            if self.settings.get(key) != value:
                self.settings[key] = value
                changed = True
        return changed

    def update_settings(self, remote: dict) -> bool:
        """Apply settings received from the server. Returns True if anything changed."""
        with self._lock:
            changed = self._apply(remote or {})
            if changed:
                self.save()
        return changed

    def unpair(self):
        with self._lock:
            self.token = ""
            self.employee_name = ""
            self.save()
