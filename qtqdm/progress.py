"""Small progress tracker independent of the web page."""

from collections import deque
from math import isfinite
from threading import Lock
from time import monotonic

from .csv_log import CsvLog
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
        self.loss_recent = deque(maxlen=300)
        self.loss_overview = []
        self.loss_updates = 0
        self.overview_stride = 1
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
        if "loss" in values:
            try:
                loss = float(values["loss"])
            except (TypeError, ValueError):
                return
            if isfinite(loss):
                with self._history_lock:
                    point = [elapsed, loss]
                    self.loss_recent.append(point)
                    self.loss_updates += 1
                    if (self.loss_updates - 1) % self.overview_stride == 0:
                        self.loss_overview.append(point)
                    if len(self.loss_overview) >= 600:
                        self.loss_overview = self.loss_overview[::2]
                        self.overview_stride *= 2

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
            loss_recent = list(self.loss_recent)
            loss_overview = list(self.loss_overview)
            if loss_recent and loss_overview[-1] is not loss_recent[-1]:
                loss_overview.append(loss_recent[-1])
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
            "loss_recent": loss_recent,
            "loss_overview": loss_overview,
        }
