"""Thread-safe recorder of real protocol events, for the HTML visualizer."""
import json
import threading
import time


class EventLog:
    def __init__(self, label=""):
        self.label = label
        self.t0 = time.monotonic()
        self._lock = threading.Lock()
        self.events = []

    def record(self, kind, **fields):
        rec = {"t": time.monotonic() - self.t0, "kind": kind}
        rec.update(fields)
        with self._lock:
            self.events.append(rec)

    def to_list(self):
        with self._lock:
            return list(self.events)

    def dump(self, path):
        with self._lock:
            data = {"label": self.label, "events": self.events}
        with open(path, "w") as f:
            json.dump(data, f, indent=1)


class NullLog:
    """No-op stand-in when a caller doesn't want event recording."""

    def record(self, kind, **fields):
        pass
