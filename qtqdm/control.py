"""Commands shared by the web server and the training loop."""

from math import isfinite
from threading import Condition


class TrainingControl:
    def __init__(self):
        self._condition = Condition()
        self._pause_requested = False
        self._paused = False
        self._stop_requested = False
        self._finished = False
        self._pending_learning_rate = None
        self._learning_rate = None
        self._save_handler = None
        self._save_requested = False
        self._saving = False
        self._last_checkpoint = None
        self._save_error = None
        self._save_at_step = None
        self._completed = 0
        self._total = None

    def request(self, action, value=None):
        if action not in ("pause", "resume", "stop", "learning_rate", "save", "schedule_save", "cancel_save"):
            raise ValueError("Unknown control action")
        if action == "learning_rate":
            if isinstance(value, bool):
                raise ValueError("Learning rate must be a finite positive number")
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError("Learning rate must be a finite positive number") from None
            if not isfinite(value) or value <= 0:
                raise ValueError("Learning rate must be a finite positive number")

        with self._condition:
            if self._finished or self._stop_requested:
                return False
            if action == "pause":
                self._pause_requested = True
            elif action == "resume":
                self._pause_requested = False
            elif action == "stop":
                self._stop_requested = True
            elif action == "save":
                if self._save_handler is None:
                    raise ValueError("This training loop has not enabled model saving")
                if self._save_requested or self._saving:
                    return False
                self._save_requested = True
                self._save_error = None
            elif action == "schedule_save":
                if self._save_handler is None:
                    raise ValueError("This training loop has not enabled model saving")
                if type(value) is not int or value <= self._completed:
                    raise ValueError("Choose an integer step after the current completed step")
                if self._total is not None and value > self._total:
                    raise ValueError("Scheduled step cannot exceed the target")
                self._save_at_step = value
            elif action == "cancel_save":
                self._save_at_step = None
            else:
                if self._learning_rate is None:
                    raise ValueError("This training loop has not enabled learning-rate control")
                self._pending_learning_rate = value
            self._condition.notify_all()
            return True

    def enable_saving(self, handler):
        """Register the training code's save function, returning a file path."""
        if not callable(handler):
            raise TypeError("Save handler must be callable")
        with self._condition:
            self._save_handler = handler

    def configure_steps(self, completed, total):
        with self._condition:
            self._completed = completed
            self._total = total

    def checkpoint(self, final=False, completed=None):
        """Handle commands on the training thread, also while paused."""
        while True:
            with self._condition:
                if completed is not None:
                    self._completed = completed
                self._paused = self._pause_requested and not self._stop_requested and not final
                if self._finished:
                    self._paused = False
                    return False
                if self._save_at_step is not None and self._completed >= self._save_at_step:
                    self._save_requested = True
                    self._save_at_step = None
                if self._save_requested:
                    self._save_requested = False
                    self._saving = True
                    self._save_error = None
                    handler = self._save_handler
                elif final or self._stop_requested or not self._pause_requested:
                    self._paused = False
                    if final:
                        self._finished = True
                    return not self._stop_requested
                else:
                    self._condition.wait()
                    continue

            # File I/O runs outside the lock so the web server remains responsive.
            try:
                path = str(handler())
            except Exception as error:
                with self._condition:
                    self._save_error = f"{type(error).__name__}: {error}"
            else:
                with self._condition:
                    self._last_checkpoint = path
            finally:
                with self._condition:
                    self._saving = False
                    self._condition.notify_all()

    def take_learning_rate(self):
        """The training loop takes a pending value and applies it itself."""
        with self._condition:
            value = self._pending_learning_rate
            self._pending_learning_rate = None
            return value

    def report_learning_rate(self, value):
        with self._condition:
            self._learning_rate = value

    def finish(self):
        with self._condition:
            self._finished = True
            self._paused = False
            self._pending_learning_rate = None
            self._save_requested = False
            self._save_at_step = None
            self._condition.notify_all()

    def snapshot(self):
        with self._condition:
            return {
                "pause_requested": self._pause_requested,
                "paused": self._paused,
                "stop_requested": self._stop_requested,
                "finished": self._finished,
                "learning_rate": self._learning_rate,
                "pending_learning_rate": self._pending_learning_rate,
                "saving_enabled": self._save_handler is not None,
                "save_requested": self._save_requested,
                "saving": self._saving,
                "last_checkpoint": self._last_checkpoint,
                "save_error": self._save_error,
                "save_at_step": self._save_at_step,
                "completed": self._completed,
                "total": self._total,
            }
