"""Background thread that ships queued spans to Odoo in batches."""
import logging
import threading

from .api import ApiError, Unauthorized

_logger = logging.getLogger(__name__)

BATCH_SIZE = 500
MAX_BACKOFF = 900


class Uploader(threading.Thread):
    def __init__(self, config, client, store, tracker, on_result, stop_event):
        super().__init__(name="uploader", daemon=True)
        self.config = config
        self.client = client
        self.store = store
        self.tracker = tracker
        self.on_result = on_result  # on_result(status: "ok" | "offline" | "unauthorized", message)
        self.stop_event = stop_event
        self._wake = threading.Event()

    def trigger(self):
        self._wake.set()

    def run(self):
        backoff = 0
        self._wake.set()  # upload (and fetch settings) right after start-up
        while not self.stop_event.is_set():
            self._wake.wait(backoff or self.config.get("upload_interval"))
            self._wake.clear()
            if self.stop_event.is_set() or not self.config.paired:
                continue
            try:
                self.upload_once()
                backoff = 0
            except Unauthorized as e:
                _logger.warning("Server rejected the device token: %s", e)
                self.on_result("unauthorized", str(e))
                backoff = 0
            except ApiError as e:
                backoff = min(max(backoff * 2, 30), MAX_BACKOFF)
                _logger.info("Upload failed (%s); retrying in %ss", e, backoff)
                self.on_result("offline", str(e))
            except Exception as e:  # noqa: BLE001 - never let the thread die
                backoff = min(max(backoff * 2, 30), MAX_BACKOFF)
                _logger.exception("Unexpected upload error")
                self.on_result("offline", str(e))

    def upload_once(self):
        """Drain the queue. An empty request still acts as a heartbeat and
        returns the latest settings."""
        while True:
            closed = self.store.batch(BATCH_SIZE)
            live = self.tracker.snapshot()
            spans = closed + ([live] if live else [])
            resp = self.client.ingest(spans)
            self.store.remove(s["uid"] for s in closed)
            if isinstance(resp.get("config"), dict):
                self.config.update_settings(resp["config"])
            self.on_result("ok", f"{len(spans)} spans sent")
            if len(closed) < BATCH_SIZE:
                return
