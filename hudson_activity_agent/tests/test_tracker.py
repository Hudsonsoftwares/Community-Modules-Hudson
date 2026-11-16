import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.config import DEFAULT_SETTINGS, Config  # noqa: E402
from agent.platforms import Foreground  # noqa: E402
from agent.store import SpanStore  # noqa: E402
from agent.tracker import IDLE, LOCKED, Tracker  # noqa: E402

CHROME = Foreground(app="Google Chrome", process="chrome.exe", title="Inbox")
EXCEL = Foreground(app="Microsoft Excel", process="EXCEL.EXE", title="Budget.xlsx")


class TrackerTest(unittest.TestCase):
    def setUp(self):
        self.settings = dict(DEFAULT_SETTINGS, sample_interval=5, idle_threshold=300)
        self.closed = []
        self.tracker = Tracker(self.settings.get, self.closed.append)
        self.t0 = datetime(2026, 11, 8, 10, 0).timestamp()

    def run_samples(self, start, seconds, fg, idle=lambda t: 0):
        t = start
        while t < start + seconds:
            self.tracker.sample(t, idle(t), fg)
            t += 5
        return t

    def test_identical_samples_merge_into_one_span(self):
        t = self.run_samples(self.t0, 600, CHROME)
        self.tracker.pause(t)
        self.assertEqual(len(self.closed), 1)
        self.assertEqual(self.closed[0].app, "Google Chrome")
        self.assertAlmostEqual(self.closed[0].duration, 600, delta=5)

    def test_app_switch_creates_new_span(self):
        t = self.run_samples(self.t0, 60, CHROME)
        t = self.run_samples(t, 60, EXCEL)
        self.tracker.pause(t)
        self.assertEqual([s.app for s in self.closed], ["Google Chrome", "Microsoft Excel"])

    def test_idle_is_backdated_to_last_input(self):
        last_input = self.t0 + 100
        t = self.run_samples(self.t0, 600, CHROME, idle=lambda t: max(0, t - last_input))
        self.tracker.pause(t)
        active, idle = self.closed
        self.assertEqual(idle.state, IDLE)
        self.assertEqual(active.end, last_input)  # not t0 + 400 when the threshold tripped
        self.assertIsNone(idle.app)

    def test_sleep_gap_closes_span_at_last_sample(self):
        t = self.run_samples(self.t0, 60, CHROME)
        last = t - 5
        self.tracker.sample(last + 3600, 0, CHROME)  # woke up an hour later
        self.assertEqual(len(self.closed), 1)
        self.assertEqual(self.closed[0].end, last)

    def test_locked_screen(self):
        t = self.run_samples(self.t0, 30, CHROME)
        self.run_samples(t, 30, Foreground(locked=True))
        self.assertEqual(self.tracker.current.state, LOCKED)

    def test_private_app_title_is_dropped(self):
        self.settings["private_apps"] = ["chrome.exe"]
        self.tracker.sample(self.t0, 0, CHROME)
        self.assertIsNone(self.tracker.current.title)

    def test_titles_disabled(self):
        self.settings["capture_titles"] = False
        self.tracker.sample(self.t0, 0, CHROME)
        self.assertIsNone(self.tracker.current.title)

    def test_split_at_local_midnight(self):
        start = datetime(2026, 11, 8, 23, 58).timestamp()
        t = self.run_samples(start, 240, CHROME)
        self.tracker.pause(t)
        self.assertEqual(len(self.closed), 2)
        midnight = datetime(2026, 11, 9).timestamp()
        self.assertEqual(self.closed[0].end, midnight)
        self.assertEqual(self.closed[1].start, midnight)

    def test_snapshot_reports_open_span(self):
        self.run_samples(self.t0, 30, CHROME)
        snap = self.tracker.snapshot()
        self.assertTrue(snap["open"])
        self.assertEqual(snap["uid"], self.tracker.current.uid)


class StoreAndConfigTest(unittest.TestCase):
    def test_store_roundtrip_and_prune(self):
        with tempfile.TemporaryDirectory() as d:
            store = SpanStore(os.path.join(d, "q.db"), max_rows=3)
            for i in range(5):
                store.add({"uid": str(i)})
            self.assertEqual([p["uid"] for p in store.batch()], ["2", "3", "4"])
            store.remove(["2", "3"])
            self.assertEqual(store.count(), 1)
            store.close()

    def test_live_checkpoint_recovered_as_closed_span(self):
        with tempfile.TemporaryDirectory() as d:
            store = SpanStore(os.path.join(d, "q.db"))
            store.save_live({"uid": "x", "open": True})
            store.close()
            store = SpanStore(os.path.join(d, "q.db"))  # "restart" after a crash
            self.assertTrue(store.recover_live())
            self.assertEqual(store.batch(), [{"uid": "x", "open": False}])
            self.assertFalse(store.recover_live())
            store.close()

    def test_config_coerces_and_clamps_server_settings(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Config(os.path.join(d, "c.json"))
            cfg.update_settings({"sample_interval": "0", "idle_threshold": 99999,
                                 "private_apps": "bad", "unknown": 1})
            self.assertEqual(cfg.get("sample_interval"), 1)
            self.assertEqual(cfg.get("idle_threshold"), 7200)
            self.assertEqual(cfg.get("private_apps"), [])
            self.assertEqual(Config(os.path.join(d, "c.json")).device_uid, cfg.device_uid)


if __name__ == "__main__":
    unittest.main()
