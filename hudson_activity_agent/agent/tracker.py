"""Turns 5-second samples into spans: consecutive identical samples are merged,
so a typical day produces a few hundred rows instead of thousands."""
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Optional

ACTIVE, IDLE, LOCKED = "active", "idle", "locked"


def iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def next_local_midnight(ts: float) -> float:
    day = datetime.fromtimestamp(ts).date() + timedelta(days=1)
    return datetime.combine(day, dtime.min).timestamp()


@dataclass
class Span:
    uid: str
    start: float
    end: float
    state: str
    app: Optional[str]
    process: Optional[str]
    title: Optional[str]

    def key(self):
        return (self.state, self.app, self.process, self.title)

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_payload(self, is_open: bool = False) -> dict:
        return {
            "uid": self.uid,
            "start": iso_utc(self.start),
            "end": iso_utc(self.end),
            "duration": round(self.duration),
            "state": self.state,
            "app": self.app,
            "process": self.process,
            "title": self.title,
            "open": is_open,
        }


class Tracker:
    def __init__(self, get_setting, emit):
        """get_setting(key) -> value; emit(span) is called for every closed span."""
        self._get = get_setting
        self._emit = emit
        self._lock = threading.Lock()
        self.current: Optional[Span] = None
        self.last_sample: Optional[float] = None

    # ---------------------------------------------------------------- public
    def sample(self, now: float, idle_seconds: float, fg) -> None:
        with self._lock:
            # A long gap between samples means the machine slept / hibernated:
            # end the span at the last time we actually saw the machine running.
            if self.current and self.last_sample is not None and now - self.last_sample > self._gap():
                self._close(self.last_sample)

            key = self._classify(idle_seconds, fg)

            # Split at local midnight so every span belongs to exactly one day.
            while self.current and now >= next_local_midnight(self.current.start):
                self._split(next_local_midnight(self.current.start))

            if self.current is None:
                self._open(now, key)
            elif self.current.key() != key:
                boundary = now
                if key[0] == IDLE and self.current.state == ACTIVE:
                    # The user actually stopped `idle_seconds` ago, not now.
                    boundary = max(self.current.start, now - idle_seconds)
                self._close(boundary)
                self._open(boundary, key)
            else:
                self.current.end = now
            self.last_sample = now

    def pause(self, now: float) -> None:
        """Close the current span (tracking disabled, shutdown...)."""
        with self._lock:
            if self.current:
                recent = self.last_sample is not None and now - self.last_sample <= self._gap()
                self._close(now if recent else self.last_sample)
            self.last_sample = None

    def snapshot(self) -> Optional[dict]:
        """The still-open span, so the server can show live activity."""
        with self._lock:
            if self.current and self.current.duration > 0:
                return self.current.to_payload(is_open=True)
            return None

    # --------------------------------------------------------------- helpers
    def _gap(self) -> float:
        return max(self._get("sample_interval") * 3, 30)

    def _classify(self, idle_seconds, fg):
        if fg.locked:
            return (LOCKED, None, None, None)
        if idle_seconds >= self._get("idle_threshold"):
            return (IDLE, None, None, None)
        title = fg.title if self._get("capture_titles") else None
        if title and fg.process:
            private = {p.lower() for p in self._get("private_apps")}
            if fg.process.lower() in private:
                title = None
        if title:
            title = title.strip()[: self._get("max_title_length")] or None
        return (ACTIVE, fg.app or fg.process or "Unknown", fg.process, title)

    def _open(self, start, key):
        state, app, process, title = key
        self.current = Span(str(uuid.uuid4()), start, start, state, app, process, title)

    def _close(self, end):
        span, self.current = self.current, None
        span.end = end
        if span.duration > 0:
            self._emit(span)

    def _split(self, at):
        key = self.current.key()
        self._close(at)
        self._open(at, key)
