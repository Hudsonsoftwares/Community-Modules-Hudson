"""OS-specific probes. Each platform module exposes:

    idle_seconds() -> float
    foreground(capture_title: bool) -> Foreground
    install_autostart(command: list[str]) / remove_autostart()
    run_main_loop(stop_event)   # blocks the main thread when there is no tray icon
"""
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Foreground:
    app: Optional[str] = None       # friendly name, e.g. "Google Chrome"
    process: Optional[str] = None   # exe name / bundle id, e.g. "chrome.exe"
    title: Optional[str] = None     # window title (None if not captured/available)
    locked: bool = False            # screen locked / lock screen in front


def load():
    if sys.platform == "win32":
        from . import windows as mod
    elif sys.platform == "darwin":
        from . import macos as mod
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")
    return mod
