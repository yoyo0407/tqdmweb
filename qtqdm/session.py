"""Run independent training jobs behind one dashboard URL."""

from threading import Condition, Thread
import traceback
import webbrowser

from .dashboard import Dashboard
from .web import Qtqdm


class TrainingSession:
    def __init__(self, parameters, validate):
        self._condition = Condition()
        self._validate = validate
        self.parameters = validate(parameters)
        self._pending = None
        self._starting = True
        self._closing = False
        self.run_id = 0
        self.run_attempt = 0
        self.dashboard = Dashboard(self.snapshot, self.request)
        self.current = Qtqdm([], open_browser=False, dashboard=self.dashboard)

    def new_progress(self, items, parameters=None, **options):
        progress = Qtqdm(items, open_browser=False, dashboard=self.dashboard, **options)
        with self._condition:
            self.current.close()
            self.current = progress
            if parameters is not None:
                self.parameters = self._validate(parameters)
            self.run_id += 1
            self._starting = False
            if self._closing:
                progress.control.request("stop")
        return progress

    def request(self, action, value=None):
        with self._condition:
            if self._closing:
                return False
            if action == "restart":
                if self._pending is not None or self._starting:
                    return False
                if not isinstance(value, dict):
                    raise ValueError("Restart requires a hyperparameter object")
                parameters = self._validate({**self.parameters, **value})
                self._pending = parameters
                self.current.control.request("stop")
                self._condition.notify_all()
                return True
            if self._pending is not None or self._starting:
                return False
            return self.current.control.request(action, value)

    def snapshot(self):
        with self._condition:
            state = self.current.snapshot()
            state["run_id"] = self.run_id
            state["restart"] = {"enabled": not self._closing,
                                "pending": self._pending is not None or self._starting,
                                "parameters": dict(self.parameters)}
            if self._pending is not None:
                state["state"] = "restart_requested"
            elif self._starting:
                state["state"] = "starting"
            return state

    def request_close(self):
        with self._condition:
            self._closing = True
            self._pending = None
            self.current.control.request("stop")
            self._condition.notify_all()

    def _listen_for_close(self):
        try:
            input("Press Enter to close the training session...\n")
        except EOFError:
            pass
        self.request_close()

    def run(self, train, open_browser=True, keep_open=False):
        """The callback creates a fresh progress/model/optimizer for each run."""
        self.dashboard.start()
        if open_browser:
            webbrowser.open(self.dashboard.url)
        if keep_open:
            Thread(target=self._listen_for_close, daemon=True).start()
        try:
            while True:
                with self._condition:
                    if self._closing:
                        return
                    parameters = dict(self.parameters)
                    self.run_attempt += 1
                try:
                    train(self, parameters)
                except Exception as error:
                    # A failed run can still be restarted from the same page.
                    if self.current.state != "failed":
                        self.current.state = "failed"
                        self.current.error = f"{type(error).__name__}: {error}"
                        self.current.console.write(traceback.format_exc())
                    if not keep_open and self._pending is None:
                        raise
                    traceback.print_exc()
                finally:
                    self.current.close()

                with self._condition:
                    self._starting = False
                    if not keep_open and self._pending is None:
                        return
                    while self._pending is None and not self._closing:
                        self._condition.wait()
                    if self._closing:
                        return
                    self.parameters = self._pending
                    self._pending = None
                    self._starting = True
        finally:
            self.current.close()
            self.dashboard.close()
