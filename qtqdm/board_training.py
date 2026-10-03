"""Cache the current training state without blocking Board state requests."""

import json
from threading import Event, Lock, Thread
from time import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from .chart_history import history_page


class TrainingBridge:
    def __init__(self, runner):
        self.runner = runner
        self._lock = Lock()
        self._closed = Event()
        self._thread = None
        self._job_id = None
        self._data = None
        self._sampled_at = None
        self._error = None
        self._history = {}
        self._history_cursor = 0

    def history_since(self, job_id, after=0):
        process = self.runner.snapshot()
        with self._lock:
            if job_id != process["job_id"] or job_id != self._job_id:
                raise ValueError("Training process changed; refresh before reading history")
            return history_page(self._history, after, self._history_cursor)

    def start(self):
        self._thread = Thread(target=self._poll, daemon=True)
        self._thread.start()

    def snapshot(self, process):
        with self._lock:
            if self._job_id != process["job_id"]:
                return {"data": None, "connected": False, "error": None}
            fresh = self._sampled_at is not None and time() - self._sampled_at <= 3
            return {"data": self._data, "connected": bool(process["running"] and fresh and not self._error),
                    "sampled_at": self._sampled_at, "error": self._error}

    def _poll(self):
        while not self._closed.is_set():
            process = self.runner.snapshot()
            job_id = process["job_id"]
            with self._lock:
                if self._job_id != job_id:
                    self._job_id = job_id
                    self._data = self._sampled_at = self._error = None
                    self._history = {}
                    self._history_cursor = 0
            if process["running"] and process["dashboard_url"]:
                try:
                    with urlopen(process["dashboard_url"] + "state", timeout=1) as response:
                        data = json.load(response)
                    data.pop("console", None)  # Board already owns the complete process console.
                    # Fetch only new points. Keep them in Board after the child exits.
                    for _ in range(4):
                        if self._history_cursor >= data.get("history_updates", 0) or self._closed.is_set():
                            break
                        with urlopen(process["dashboard_url"] + f"history?after={self._history_cursor}", timeout=1) as response:
                            page = json.load(response)
                        if self.runner.snapshot()["job_id"] != job_id:
                            break
                        with self._lock:
                            for name, points in page["charts"].items():
                                self._history.setdefault(name, []).extend(points)
                            previous = self._history_cursor
                            self._history_cursor = page["next_update"]
                        if self._history_cursor <= previous:
                            break
                    error = None
                except (OSError, URLError, ValueError) as exception:
                    data, error = None, str(exception)
                current = self.runner.snapshot()
                if current["job_id"] == job_id and current["dashboard_url"] == process["dashboard_url"]:
                    with self._lock:
                        self._error = error
                        if data is not None:
                            self._data, self._sampled_at = data, time()
            self._closed.wait(0.25)

    def control(self, command):
        process = self.runner.snapshot()
        if command.get("job_id") != process["job_id"] or not process["running"] or not process["dashboard_url"]:
            raise ValueError("Training process changed or is unavailable; refresh before retrying")
        payload = {"action": command.get("action"), "value": command.get("value")}
        request = Request(process["dashboard_url"] + "control", data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=2) as response:
                return json.load(response), response.status
        except HTTPError as error:
            return json.load(error), error.code

    def close(self):
        self._closed.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
