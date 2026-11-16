"""System-tray / menu-bar icon (pystray + Pillow). Makes tracking visible to the employee."""
import sys
import webbrowser

import pystray
from PIL import Image, ImageDraw

COLORS = {
    "tracking": (46, 157, 91),
    "paused": (138, 143, 152),
    "offline": (224, 138, 30),
    "unpaired": (214, 69, 69),
}


def _image(status):
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, size - 4, size - 4), fill=COLORS.get(status, COLORS["paused"]))
    # A simple white "H" mark
    draw.rectangle((20, 17, 27, 47), fill="white")
    draw.rectangle((37, 17, 44, 47), fill="white")
    draw.rectangle((20, 29, 44, 35), fill="white")
    return img


class TrayApp:
    def __init__(self, agent):
        self.agent = agent
        self.icon = pystray.Icon(
            "HudsonActivity", _image(agent.status), self._tooltip(), menu=self._menu())

    def _tooltip(self):
        return f"Hudson Activity - {self.agent.status_text}"[:127]

    def _menu(self):
        agent = self.agent
        cfg = agent.config
        return pystray.Menu(
            pystray.MenuItem(lambda _i: agent.status_text, None, enabled=False),
            pystray.MenuItem(lambda _i: f"Employee: {cfg.employee_name or '-'}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open my activity", self._open_dashboard,
                             visible=lambda _i: bool(cfg.get("dashboard_url"))),
            pystray.MenuItem("Sync now", lambda: agent.sync_now(), visible=lambda _i: cfg.paired),
            pystray.MenuItem("Pair this device...", lambda: agent.request_repair(),
                             visible=lambda _i: not cfg.paired),
            pystray.MenuItem("Pair with another employee...", self._repair,
                             visible=lambda _i: cfg.paired),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit, visible=lambda _i: cfg.get("allow_quit")),
        )

    def _open_dashboard(self):
        url = self.agent.config.get("dashboard_url")
        if url:
            webbrowser.open(url)

    def _repair(self):
        name = self.agent.config.employee_name or "the current employee"
        if self.agent.plat.message(
                "Hudson Activity",
                f"This computer is tracking for {name}.\n\nPair it with a different employee? "
                "You will need a new pairing code from Odoo.", yes_no=True):
            self.agent.request_repair()

    def notify(self, title, message):
        self.icon.notify(message, title)

    def _quit(self):
        self.agent.shutdown()
        self.icon.stop()

    def refresh(self):
        # Called from worker threads; AppKit UI must only be touched on the main thread.
        if sys.platform == "darwin":
            from PyObjCTools import AppHelper
            AppHelper.callAfter(self._refresh)
        else:
            self._refresh()

    def _refresh(self):
        self.icon.icon = _image(self.agent.status)
        self.icon.title = self._tooltip()
        self.icon.update_menu()

    def stop(self):
        self.icon.stop()

    def run(self):
        def setup(icon):
            icon.visible = True
        self.icon.run(setup=setup)  # blocks; must be on the main thread (macOS)
