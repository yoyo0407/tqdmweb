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
        self._rate_handler = None
        self._rate_error = None
        self._save_handler = None
        self._save_requested = False
        self._saving = False
        self._last_checkpoint = None
        self._save_error = None
        self._save_request_id = 0
        self._save_completed_id = 0
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
                self._save_request_id += 1
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
                if self._rate_handler is None:
                    raise ValueError("This training loop has not enabled learning-rate control")
                self._pending_learning_rate = value
                self._rate_error = None
            self._condition.notify_all()
            return True

    def register_controls(self, *, save_checkpoint=None, set_learning_rate=None, learning_rate=None):
        """Register callbacks before iteration; each runs on the training thread."""
        for handler in (save_checkpoint, set_learning_rate):
            if handler is not None and not callable(handler):
                raise TypeError("Control handlers must be callable")
        if set_learning_rate is not None:
            if (isinstance(learning_rate, bool) or not isinstance(learning_rate, (int, float))
                    or not isfinite(learning_rate) or learning_rate <= 0):
                raise ValueError("Provide the current finite positive learning_rate")
        elif learning_rate is not None:
            raise ValueError("learning_rate requires set_learning_rate")
        with self._condition:
            if save_checkpoint is not None:
                self._save_handler = save_checkpoint
            if set_learning_rate is not None:
                self._rate_handler = set_learning_rate
                self._learning_rate = learning_rate

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
                    self._save_request_id += 1
                    self._save_at_step = None
                if self._pending_learning_rate is not None and not self._stop_requested:
                    rate = self._pending_learning_rate
                    self._pending_learning_rate = None
                    handler = self._rate_handler
                    operation = "learning_rate"
                elif self._save_requested:
                    self._save_requested = False
                    self._saving = True
                    self._save_error = None
                    handler = self._save_handler
                    operation = "save"
                    save_request_id = self._save_request_id
                elif final or self._stop_requested or not self._pause_requested:
                    self._paused = False
                    if final:
                        self._finished = True
                    return not self._stop_requested
                else:
                    self._condition.wait()
                    continue

            # Callbacks run outside the lock so the web server remains responsive.
            try:
                if operation == "learning_rate":
                    handler(rate)
                else:
                    path = handler()
                    if path is None:
                        raise ValueError("Checkpoint handler must return its file path")
                    path = str(path)
            except Exception as error:
                with self._condition:
                    if operation == "learning_rate":
                        self._rate_error = f"{type(error).__name__}: {error}"
                    else:
                        self._save_error = f"{type(error).__name__}: {error}"
            else:
                with self._condition:
                    if operation == "learning_rate":
                        self._learning_rate = rate
                        self._rate_error = None
                    else:
                        self._last_checkpoint = path
            finally:
                with self._condition:
                    if operation == "save":
                        self._saving = False
                        self._save_completed_id = save_request_id
                    self._condition.notify_all()

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
                "learning_rate_error": self._rate_error,
                "capabilities": {"pause": True, "stop": True,
                                 "save_checkpoint": self._save_handler is not None,
                                 "learning_rate": self._rate_handler is not None},
                "save_requested": self._save_requested,
                "saving": self._saving,
                "last_checkpoint": self._last_checkpoint,
                "save_error": self._save_error,
                "save_request_id": self._save_request_id,
                "save_completed_id": self._save_completed_id,
                "save_at_step": self._save_at_step,
                "completed": self._completed,
                "total": self._total,
            }
