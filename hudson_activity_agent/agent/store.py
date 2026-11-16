"""Offline queue: closed spans wait in SQLite until the server confirms them."""
import json
import sqlite3
import threading
import time


class SpanStore:
    def __init__(self, path, max_rows=200_000):
        self.max_rows = max_rows
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS spans ("
            " uid TEXT PRIMARY KEY, payload TEXT NOT NULL, created REAL NOT NULL)")
        # Checkpoint of the still-open span, so a crash / kill / power loss loses
        # at most one checkpoint interval instead of the whole span.
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS live (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL)")

    def save_live(self, payload) -> None:
        with self._lock:
            if payload:
                self._conn.execute("INSERT OR REPLACE INTO live (id, payload) VALUES (1, ?)",
                                   (json.dumps(payload),))
            else:
                self._conn.execute("DELETE FROM live")

    def recover_live(self) -> bool:
        """On start-up: turn a checkpoint left by an unclean exit into a closed span."""
        with self._lock:
            row = self._conn.execute("SELECT payload FROM live").fetchone()
            self._conn.execute("DELETE FROM live")
        if not row:
            return False
        payload = json.loads(row[0])
        payload["open"] = False
        self.add(payload)
        return True

    def add(self, payload: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO spans (uid, payload, created) VALUES (?, ?, ?)",
                (payload["uid"], json.dumps(payload), time.time()))
            self._prune()

    def batch(self, limit=500) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM spans ORDER BY created LIMIT ?", (limit,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def remove(self, uids) -> None:
        uids = list(uids)
        with self._lock:
            for i in range(0, len(uids), 500):
                chunk = uids[i:i + 500]
                self._conn.execute(
                    f"DELETE FROM spans WHERE uid IN ({','.join('?' * len(chunk))})", chunk)

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM spans")
            self._conn.execute("DELETE FROM live")

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM spans").fetchone()[0]

    def close(self):
        with self._lock:
            self._conn.close()

    def _prune(self):
        # Safety valve if a device stays offline for months: drop the oldest rows.
        (count,) = self._conn.execute("SELECT COUNT(*) FROM spans").fetchone()
        if count > self.max_rows:
            self._conn.execute(
                "DELETE FROM spans WHERE uid IN (SELECT uid FROM spans ORDER BY created LIMIT ?)",
                (count - self.max_rows,))
