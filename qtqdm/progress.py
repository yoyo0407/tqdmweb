"""Small progress tracker independent of the web page."""

from math import isfinite
from threading import Lock
from time import monotonic

from .csv_log import CsvLog
from .chart_history import ChartHistory
from .control import TrainingControl


class Progress:
    def __init__(self, items, total=None, description="", csv_path=None, initial=0):
        if type(initial) is not int or initial < 0:
            raise ValueError("initial must be a non-negative integer")
        self.items = items
        if total is None:
            try:
                total = initial + len(items)
            except TypeError:
                pass
        if total is not None and total < 0:
            raise ValueError("total must be non-negative")
        if total is not None and initial > total:
            raise ValueError("initial cannot exceed total")
        self.total = total
        self.description = description
        self.started = initial
        self.completed = initial
        self.initial = initial
        self.started_at = None
        self.finished_at = None
        self.state = "waiting"
        self.error = None
        self.metrics = {}
        self._chart_history = {}
        self._metric_updates = 0
        self._history_lock = Lock()
        self.control = TrainingControl()
        self.control.configure_steps(initial, total)
        self._csv_log = CsvLog(csv_path) if csv_path is not None else None

    def set_postfix(self, **values):
        """Display named values such as loss or accuracy on the page."""
        elapsed = 0 if self.started_at is None else monotonic() - self.started_at
        if self._csv_log is not None and values:
            self._csv_log.write(elapsed, self.started, values)
        self.metrics = {**self.metrics, **{key: str(value) for key, value in values.items()}}
        self._metric_updates += 1
        for name, value in values.items():
            if isinstance(value, bool):
                continue
            try:
                number = float(value)
            except (TypeError, ValueError, OverflowError):
                continue
            if isfinite(number):
                with self._history_lock:
                    if name not in self._chart_history:
                        self._chart_history[name] = ChartHistory()
                    history = self._chart_history[name]
                    history.append([elapsed, number, self.started, self._metric_updates])

    def __iter__(self):
        if self.started_at is not None:
            raise RuntimeError("Create a new Progress object for each loop")
        self.started_at = monotonic()
        self.state = "running"
        try:
            for item in self.items:
                if not self.control.checkpoint(completed=self.completed):
                    self.state = "stopped"
                    return
                self.started += 1
                yield item
                self.completed += 1
        except BaseException:
            if self.state != "failed":
                self.state = "stopped"
            raise
        else:
            self.state = "finished" if self.control.checkpoint(final=True, completed=self.completed) else "stopped"
        finally:
            self.control.finish()
            if self.finished_at is None:
                self.finished_at = monotonic()
            self._close_log()

    def _close_log(self):
        if self._csv_log is not None:
            self._csv_log.close()

    def snapshot(self):
        control = self.control.snapshot()
        state = self.state
        if state in ("waiting", "running") and not control["finished"]:
            if control["saving"]:
                state = "saving"
            elif control["stop_requested"]:
                state = "stop_requested"
            elif control["paused"]:
                state = "paused"
            elif control["pause_requested"]:
                state = "pause_requested"
        with self._history_lock:
            charts = {name: history.snapshot() for name, history in self._chart_history.items()}
            loss = charts.get("loss", {"recent": [], "overview": []})
        now = self.finished_at if self.finished_at is not None else monotonic()
        elapsed = 0 if self.started_at is None else now - self.started_at
        rate = (self.completed - self.initial) / elapsed if elapsed > 0 else 0
        remaining = None
        if self.total is not None and rate > 0:
            remaining = max(0, self.total - self.completed) / rate
        return {
            "description": self.description,
            "started": self.started,
            "completed": self.completed,
            "total": self.total,
            "elapsed": elapsed,
            "rate": rate,
            "remaining": remaining,
            "state": state,
            "control": control,
            "error": self.error,
            "metrics": self.metrics,
            "charts": charts,
            "loss_recent": [point[:2] for point in loss["recent"]],
            "loss_overview": [point[:2] for point in loss["overview"]],
        }
