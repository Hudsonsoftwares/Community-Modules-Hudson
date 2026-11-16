"""Agent entry point: wires config, sampler, offline queue, uploader and tray icon."""
import argparse
import logging
import logging.handlers
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from . import VERSION, platforms
from .api import ApiClient, ApiError
from .config import Config, data_dir, set_data_dir
from .store import SpanStore
from .tracker import Tracker
from .uploader import Uploader

_logger = logging.getLogger("agent")
ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT_INTERVAL = 30  # seconds between saves of the open span
APP_TITLE = "Hudson Activity"


def pair_request_file():
    """Touched by a second launch of the app to ask the running copy to (re)pair."""
    return data_dir() / "pair.request"


_EXTRA_ARGS = []


def self_command():
    """Command line that starts this agent again (autostart / relaunch)."""
    base = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(ROOT / "run_agent.py")]
    return base + _EXTRA_ARGS


# --------------------------------------------------------------------- agent
class Agent:
    def __init__(self, config, plat, client, dry_run=False):
        self.config = config
        self.plat = plat
        self.client = client
        self.dry_run = dry_run
        self.stop_event = threading.Event()
        self.relaunch = False
        self.on_change = None   # tray refresh callback
        self.on_stop = None     # tray stop callback
        self.on_notify = None   # tray balloon callback(title, message)
        self._upload_ok = None
        self._stopped = False
        self._stop_lock = threading.Lock()
        self.tracker = Tracker(config.get, self._on_span_closed)
        self.store = None if dry_run else SpanStore(data_dir() / "queue.db")
        if self.store and self.store.recover_live():
            _logger.info("Recovered the last span from an unclean shutdown")
        self.uploader = None
        if not dry_run:
            self.uploader = Uploader(config, client, self.store, self.tracker,
                                     self._on_upload_result, self.stop_event)
        self._sampler = threading.Thread(target=self._sample_loop, name="sampler", daemon=True)

    # ------------------------------------------------------------ status
    @property
    def status(self):
        if not self.dry_run and not self.config.paired:
            return "unpaired"
        if not self.config.get("tracking_enabled"):
            return "paused"
        if self._upload_ok is False:
            return "offline"
        return "tracking"

    @property
    def status_text(self):
        status = self.status
        if status == "unpaired":
            return "Not paired - tracking stopped"
        if status == "paused":
            return "Paused by your administrator"
        if status == "offline":
            return f"Offline - {self.store.count()} records waiting"
        return "Tracking active"

    def _notify(self, title, message):
        if self.on_notify:
            try:
                self.on_notify(title, message)
            except Exception:  # noqa: BLE001 - balloons are not supported everywhere
                _logger.debug("Notification failed", exc_info=True)

    def _changed(self):
        if self.on_change:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001
                _logger.exception("Tray refresh failed")

    # ------------------------------------------------------------ callbacks
    def _on_span_closed(self, span):
        if self.dry_run:
            fmt = "%H:%M:%S"
            print(f"{datetime.fromtimestamp(span.start):{fmt}}-{datetime.fromtimestamp(span.end):{fmt}} "
                  f"{span.duration:6.0f}s  {span.state:<6} {span.app or '':<28} {span.title or ''}",
                  flush=True)
        else:
            self.store.add(span.to_payload())

    def _on_upload_result(self, result, message):
        previous = self.status
        if result == "unauthorized":
            self.config.unpair()
            self.tracker.pause(time.time())
            self._notify("Tracking stopped",
                         "This computer was unpaired in Odoo. Right-click the tray icon > "
                         "Pair this device... to pair it again.")
        else:
            self._upload_ok = result == "ok"
        if self.status != previous:
            _logger.info("Status: %s (%s)", self.status, message)
        self._changed()  # refresh tooltip/menu either way (queue count, settings)

    # ------------------------------------------------------------ loops
    def _sample_loop(self):
        last_checkpoint = 0.0
        while not self.stop_event.is_set():
            now = time.time()
            try:
                if self.config.get("tracking_enabled") and (self.dry_run or self.config.paired):
                    fg = self.plat.foreground(capture_title=self.config.get("capture_titles"))
                    self.tracker.sample(now, self.plat.idle_seconds(), fg)
                else:
                    self.tracker.pause(now)
                if self.store and now - last_checkpoint >= CHECKPOINT_INTERVAL:
                    self.store.save_live(self.tracker.snapshot())
                    last_checkpoint = now
            except Exception:  # noqa: BLE001 - one bad sample must not stop tracking
                _logger.exception("Sampling failed")
            self._check_pair_request()
            self.stop_event.wait(self.config.get("sample_interval"))

    def _check_pair_request(self):
        request = pair_request_file()
        if not request.exists():
            return
        try:
            request.unlink()
        except OSError:
            return
        _logger.info("Another launch asked to pair this computer")
        # Not from this thread: shutdown() joins the sampler thread.
        threading.Thread(target=self.request_repair, daemon=True).start()

    def start(self):
        _logger.info("Agent %s starting (device %s)", VERSION, self.config.device_uid)
        self._sampler.start()
        if self.uploader:
            self.uploader.start()

    def sync_now(self):
        if self.uploader:
            self.uploader.trigger()

    def request_repair(self):
        """Stop (uploading what is pending for the current employee), then main()
        unpairs and restarts the app, which opens the pairing window."""
        self.relaunch = True
        self.shutdown()

    def shutdown(self):
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True
        _logger.info("Agent stopping")
        self.stop_event.set()
        if self.uploader:
            self.uploader.trigger()
        self._sampler.join(timeout=5)
        self.tracker.pause(time.time())
        if self.store:
            self.store.save_live(None)  # clean exit: the span was closed normally
        if self.uploader and self.config.paired:
            # Best-effort final upload so the last span is not left waiting until next start.
            flush = threading.Thread(target=self._final_upload, daemon=True)
            flush.start()
            flush.join(timeout=5)
        if self.store:
            self.store.close()
        if self.on_stop:
            self.on_stop()

    def _final_upload(self):
        try:
            self.uploader.upload_once()
        except Exception as e:  # noqa: BLE001
            _logger.info("Final upload skipped: %s", e)


# ---------------------------------------------------------------- utilities
class InstanceLock:
    def __init__(self, path):
        self.path = path
        self._fh = None

    def acquire(self, wait=0.0) -> bool:
        deadline = time.time() + wait
        self._fh = open(self.path, "a+")
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                if time.time() >= deadline:
                    self._fh.close()
                    self._fh = None
                    return False
                time.sleep(0.5)

    def release(self):
        if self._fh:
            self._fh.close()
            self._fh = None


def setup_logging(verbose):
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(
        data_dir() / "agent.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if verbose or not getattr(sys, "frozen", False):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)


def parse_args(argv):
    p = argparse.ArgumentParser(prog="HudsonActivity", description="Hudson activity tracking agent")
    p.add_argument("--pair-url", help="Odoo server URL to pair with")
    p.add_argument("--pair-code", help="Pairing code generated in Odoo")
    p.add_argument("--unpair", action="store_true", help="Forget the device token and exit")
    p.add_argument("--no-tray", action="store_true", help="Run without the tray icon")
    p.add_argument("--dry-run", action="store_true",
                   help="Print spans to the console instead of uploading (no pairing needed)")
    p.add_argument("--no-autostart", action="store_true", help="Do not register start at login")
    p.add_argument("--remove-autostart", action="store_true", help="Unregister start at login and exit")
    p.add_argument("--data-dir", help="Override the data directory")
    p.add_argument("--sample-interval", type=int, help="Local override (testing)")
    p.add_argument("--idle-threshold", type=int, help="Local override (testing)")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--version", action="version", version=VERSION)
    p.add_argument("--wait-lock", action="store_true", help=argparse.SUPPRESS)
    return p.parse_args(argv)


def _maybe_autostart(args, plat):
    if args.no_autostart or not getattr(sys, "frozen", False):
        return
    try:
        plat.install_autostart(self_command())
        _logger.info("Registered start at login")
    except Exception:  # noqa: BLE001
        _logger.exception("Could not register start at login")


# ---------------------------------------------------------------------- main
def main(argv=None):
    args = parse_args(argv)
    if args.data_dir:
        set_data_dir(args.data_dir)
        _EXTRA_ARGS[:] = ["--data-dir", args.data_dir]
    setup_logging(args.verbose)
    lock = InstanceLock(data_dir() / "agent.lock")
    if not lock.acquire(wait=15 if args.wait_lock else 0):
        _second_launch(args)
        return 0
    try:
        return _run(args)
    finally:
        lock.release()


def _second_launch(args):
    """The app was started while it is already running (e.g. the user double-clicked
    the exe again). Explain where it is and offer to pair, instead of exiting silently."""
    print("Hudson Activity is already running.", file=sys.stderr)
    if args.no_tray or args.dry_run or args.pair_url or args.unpair or args.remove_autostart:
        return
    try:
        config = Config()
        plat = platforms.load()
        if not config.paired:
            pair_request_file().touch()  # the running copy opens the pairing window
            return
        text = (f"Hudson Activity is already running and tracking for "
                f"{config.employee_name or 'an employee'}.\n\n"
                "Its icon is in the system tray near the clock (click ^ if you don't see it).\n\n"
                "Do you want to pair this computer with a different employee?")
        if plat.message(APP_TITLE, text, yes_no=True):
            pair_request_file().touch()
    except Exception:  # noqa: BLE001
        _logger.exception("Second launch handling failed")


def _reset_queue():
    """Spans queued for a previous pairing must never be sent under a new employee."""
    store = SpanStore(data_dir() / "queue.db")
    store.clear()
    store.close()


def _paired_message(plat, config):
    try:
        plat.message(APP_TITLE,
                     f"This computer is now paired with Odoo for {config.employee_name or 'the employee'}.\n\n"
                     "Hudson Activity keeps running in the background: look for the green \"H\" icon "
                     "in the system tray near the clock. It starts automatically when you log in.")
    except Exception:  # noqa: BLE001
        _logger.debug("Could not show the confirmation", exc_info=True)


def _run(args):
    config = Config()
    if args.unpair:
        config.unpair()
        print("Device unpaired.")
        return 0

    plat = platforms.load()
    if args.remove_autostart:
        plat.remove_autostart()
        print("Start at login removed.")
        return 0

    client = ApiClient(config)
    if args.pair_url or args.pair_code:
        if not (args.pair_url and args.pair_code):
            print("--pair-url and --pair-code must be used together.", file=sys.stderr)
            return 2
        try:
            client.pair(args.pair_url, args.pair_code)
            _reset_queue()
        except ApiError as e:
            print(f"Pairing failed: {e}", file=sys.stderr)
            return 1
        print(f"Paired with {config.server_url} as {config.employee_name or 'unknown employee'}.")
        _maybe_autostart(args, plat)

    # Local overrides are kept in memory only (never saved).
    for key in ("sample_interval", "idle_threshold"):
        value = getattr(args, key)
        if value is not None:
            config.settings[key] = value

    headless = args.no_tray or args.dry_run
    if not config.paired and not args.dry_run:
        if headless:
            print("This device is not paired. Run with --pair-url and --pair-code.", file=sys.stderr)
            return 2
        from .pairing import run_pairing_dialog

        def attempt(url, code):
            try:
                client.pair(url, code)
                _reset_queue()
            except ApiError as e:
                return str(e)
            return None

        if run_pairing_dialog(config.server_url, attempt):
            _maybe_autostart(args, plat)
            _paired_message(plat, config)
        # Cancelled: keep running (red icon) so it can be paired later from the tray.

    agent = Agent(config, plat, client, dry_run=args.dry_run)
    agent.start()

    tray = None
    if not headless:
        try:
            from .tray import TrayApp
            tray = TrayApp(agent)
        except Exception:  # noqa: BLE001 - e.g. pystray missing or no tray available
            _logger.exception("Tray icon unavailable, running headless")

    def _stop(*_):
        agent.stop_event.set()
        if tray:
            tray.stop()

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    if tray:
        agent.on_change = tray.refresh
        agent.on_stop = tray.stop
        agent.on_notify = tray.notify
        tray.run()
    else:
        if args.dry_run:
            print("Dry run: spans are printed when they close. Ctrl+C to stop.", flush=True)
        try:
            plat.run_main_loop(agent.stop_event)
        except KeyboardInterrupt:
            pass
    agent.on_stop = None
    agent.shutdown()

    if agent.relaunch:
        # Re-pair: pending data was uploaded (or attempted) during shutdown.
        config.unpair()
        _reset_queue()
        subprocess.Popen(self_command() + ["--wait-lock"], close_fds=True)
    return 0
