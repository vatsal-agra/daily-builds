"""TraceRecorder: collects every `trace(event, **fields)` callback from
ConduitSocket / NetworkSimulator / HttpServer into one timestamped,
JSON-serializable event log — the raw material the HTML report renders."""

import threading
import time


class TraceRecorder:
    def __init__(self):
        self._events = []
        self._lock = threading.Lock()
        self._t0 = None

    def tracer(self, side: str):
        """Returns a `trace(event, **fields)` callable tagged with `side`
        (e.g. "client", "server", "netsim") — pass this as the `trace=`
        argument to ConduitSocket/Listener/NetworkSimulator/HttpServer."""

        def trace(event, **fields):
            now = time.monotonic()
            with self._lock:
                if self._t0 is None:
                    self._t0 = now
                self._events.append({"t": now - self._t0, "side": side, "event": event, **fields})

        return trace

    @property
    def events(self):
        with self._lock:
            return list(self._events)

    def clear(self):
        with self._lock:
            self._events.clear()
            self._t0 = None
