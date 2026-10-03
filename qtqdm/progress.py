"""Small progress tracker independent of the web page."""

from math import isfinite
from threading import Lock
from time import monotonic

from .csv_log import CsvLog
from .chart_history import ChartHistory, history_page
from .control import TrainingControl


class Progress:
    def __init__(self, items=None, total=None, description="", csv_path=None, initial=0):
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
        self.events = []
        self.control = TrainingControl()
        self.control.on_event = self._record_event
        self.control.configure_steps(initial, total)
        self._csv_log = CsvLog(csv_path) if csv_path is not None else None
        self._finalized = False

    @property
    def manual(self):
        """True when counts come from update() instead of iterating items."""
        return self.items is None

    @property
    def n(self):
        return self.completed

    @property
    def stopped(self):
        """Manual loops check this after update() and break when Stop is accepted."""
        return self.state == "stopped" or self.control.stop_requested

    def set_description(self, desc=None, refresh=True):
        self.description = desc or ""

    def _record_event(self, kind, label):
        with self._history_lock:
            elapsed = 0 if self.started_at is None else monotonic() - self.started_at
            self.events.append([elapsed, kind, self.started, self._metric_updates, label])

    def mark(self, label):
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 100:
            raise ValueError("Event label must be a non-empty string of at most 100 characters")
        self._record_event("mark", label.strip())

    def update(self, n=1):
        """Advance a manual bar by n completed items, then handle controls at this boundary."""
        if not self.manual:
            raise RuntimeError("update() is only for bars created without an iterable")
        if type(n) is not int or n < 0:
            raise ValueError("n must be a non-negative integer")
        if self.state not in ("waiting", "running"):
            self.completed += n
            self.started = self.completed
            return
        self._begin()
        self.completed += n
        self.started = self.completed
        if not self.control.checkpoint(completed=self.completed):
            self.state = "stopped"

    def _begin(self):
        if self.started_at is None:
            self.started_at = monotonic()
            self.state = "running"
            self._on_start()

    def _on_start(self):
        """Hook for subclasses when the bar starts running."""

    def _finalize_manual(self):
        """End a manual bar once: run a pending save, then record finished or stopped."""
        if not self.manual or self._finalized:
            return
        self._finalized = True
        if self.state in ("waiting", "running"):
            self._begin()
            complete = self.total is None or self.completed >= self.total
            ok = self.control.checkpoint(final=True, completed=self.completed)
            self.state = "finished" if ok and complete else "stopped"
        self.control.finish()
        if self.finished_at is None:
            self.finished_at = monotonic()
        self._close_log()

    def register_controls(self, *, save_checkpoint=None, set_learning_rate=None, learning_rate=None):
        """Keep model-specific code in the script, not in the web server."""
        if self.started_at is not None:
            raise RuntimeError("Register controls before starting the loop")
        self.control.register_controls(save_checkpoint=save_checkpoint,
                                       set_learning_rate=set_learning_rate, learning_rate=learning_rate)
        return self

    def set_postfix(self, ordered_dict=None, refresh=True, **values):
        """Display named values such as loss or accuracy on the page."""
        values = {**(ordered_dict or {}), **values}
        elapsed = 0 if self.started_at is None else monotonic() - self.started_at
        if self._csv_log is not None and values:
            self._csv_log.write(elapsed, self.started, values)
        self.metrics = {**self.metrics, **{key: str(value) for key, value in values.items()}}
        with self._history_lock:
            self._metric_updates += 1
            for name, value in values.items():
                if isinstance(value, bool):
                    continue
                try:
                    number = float(value)
                except (TypeError, ValueError, OverflowError):
                    continue
                if isfinite(number):
                    if name not in self._chart_history:
                        self._chart_history[name] = ChartHistory()
                    history = self._chart_history[name]
                    history.append([elapsed, number, self.started, self._metric_updates])

    def __iter__(self):
        if self.manual:
            raise TypeError("This bar has no iterable; call update() instead")
        if self.started_at is not None:
            raise RuntimeError("Create a new Progress object for each loop")
        self.started_at = monotonic()
        self.state = "running"
        self._on_start()
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

    def history_since(self, after=0, limit=2000):
        with self._history_lock:
            return history_page({name: history.full for name, history in self._chart_history.items()},
                                after, self._metric_updates, limit)

    def _close_log(self):
        if self._csv_log is not None:
            self._csv_log.close()

    def _timing(self):
        now = self.finished_at if self.finished_at is not None else monotonic()
        elapsed = 0 if self.started_at is None else now - self.started_at
        rate = (self.completed - self.initial) / elapsed if elapsed > 0 else 0
        remaining = None
        if self.total is not None and rate > 0:
            remaining = max(0, self.total - self.completed) / rate
        return elapsed, rate, remaining

    def bar_summary(self):
        """Counts and timing for one bar, without metrics or control state."""
        elapsed, rate, remaining = self._timing()
        return {"description": self.description, "started": self.started, "completed": self.completed,
                "total": self.total, "elapsed": elapsed, "rate": rate, "remaining": remaining,
                "state": self.state}

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
            history_updates = self._metric_updates
            events = list(self.events)
        elapsed, rate, remaining = self._timing()
        return {
            "history_updates": history_updates,
            "events": events,
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
        }
