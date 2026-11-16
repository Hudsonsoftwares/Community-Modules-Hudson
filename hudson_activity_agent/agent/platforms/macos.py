"""macOS probes via PyObjC (pyobjc-framework-Cocoa + pyobjc-framework-Quartz).

Permissions:
  * Idle time and the frontmost app need no permission.
  * Window titles need "Screen Recording" (System Settings > Privacy & Security).
    Without it CGWindowList simply omits kCGWindowName and we send no title.
"""
import json
import plistlib
import subprocess
from pathlib import Path

import Quartz
from AppKit import NSWorkspace
from Foundation import NSDate, NSRunLoop

from . import Foreground

LAUNCH_AGENT_LABEL = "com.hudsonsoftwares.activity"
LAUNCH_AGENT_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
SCREENSAVER_BUNDLE = "com.apple.ScreenSaver.Engine"
LOGIN_WINDOW_BUNDLE = "com.apple.loginwindow"


def idle_seconds() -> float:
    return float(Quartz.CGEventSourceSecondsSinceLastEventType(
        Quartz.kCGEventSourceStateCombinedSessionState, Quartz.kCGAnyInputEventType))


def _session_locked() -> bool:
    session = Quartz.CGSessionCopyCurrentDictionary()
    return bool(session and session.get("CGSSessionScreenIsLocked"))


def _window_title(pid):
    options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []
    for win in windows:  # front-to-back order
        if win.get("kCGWindowOwnerPID") == pid and win.get("kCGWindowLayer") == 0:
            return win.get("kCGWindowName") or None
    return None


def foreground(capture_title: bool = True) -> Foreground:
    if _session_locked():
        return Foreground(locked=True)
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return Foreground()
    bundle = app.bundleIdentifier()
    if bundle in (SCREENSAVER_BUNDLE, LOGIN_WINDOW_BUNDLE):
        return Foreground(locked=True)
    pid = app.processIdentifier()
    return Foreground(
        app=app.localizedName(),
        process=bundle or app.localizedName(),
        title=_window_title(pid) if capture_title else None,
    )


def install_autostart(command):
    LAUNCH_AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LAUNCH_AGENT_PATH, "wb") as fh:
        plistlib.dump({
            "Label": LAUNCH_AGENT_LABEL,
            "ProgramArguments": list(command),
            "RunAtLoad": True,
            "KeepAlive": False,
            "ProcessType": "Interactive",
        }, fh)


def remove_autostart():
    LAUNCH_AGENT_PATH.unlink(missing_ok=True)


def message(title, text, yes_no=False) -> bool:
    """Native dialog via AppleScript. Returns True for OK / Yes."""
    buttons = '{"No", "Yes"}' if yes_no else '{"OK"}'
    default = '"Yes"' if yes_no else '"OK"'
    script = (f"display dialog {json.dumps(text)} with title {json.dumps(title)} "
              f"buttons {buttons} default button {default} with icon note")
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return result.returncode == 0 and ("Yes" in result.stdout if yes_no else True)


def run_main_loop(stop_event):
    # NSWorkspace.frontmostApplication is refreshed by notifications delivered on
    # the main run loop, so the main thread must keep pumping it (the tray icon
    # does this for us; this is the headless equivalent).
    loop = NSRunLoop.currentRunLoop()
    while not stop_event.is_set():
        loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.5))
