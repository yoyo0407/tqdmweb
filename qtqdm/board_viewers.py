"""Last-tab shutdown with a refresh grace period and crash fallback."""

from threading import Lock
from time import monotonic


class BoardViewers:
    def __init__(self, grace=3, timeout=90):
        self.grace, self.timeout = grace, timeout
        self._lock = Lock()
        self._viewers = {}
        self._sequences = {}
        self._seen = False
        self._empty_since = None

    def update(self, viewer, closed=False, sequence=None):
        if not isinstance(viewer, str) or not 1 <= len(viewer) <= 100:
            raise ValueError('Invalid viewer ID')
        with self._lock:
            if sequence is not None:
                if type(sequence) is not int or sequence < 0:
                    raise ValueError('Invalid viewer sequence')
                if sequence <= self._sequences.get(viewer, -1):
                    return
                self._sequences[viewer] = sequence
            self._seen = True
            if closed:
                self._viewers.pop(viewer, None)
            else:
                self._viewers[viewer] = monotonic()
                self._empty_since = None

    def should_close(self):
        now = monotonic()
        with self._lock:
            self._viewers = {key: stamp for key, stamp in self._viewers.items() if now - stamp < self.timeout}
            if not self._seen or self._viewers:
                return False
            if self._empty_since is None:
                self._empty_since = now
            return now - self._empty_since >= self.grace
