"""A tiny local web server for the progress page."""

from time import monotonic
import webbrowser
import traceback as traceback_module
import os

from .progress import Progress
from .console import ConsoleCapture, ConsoleOutput
from .dashboard import Dashboard


class Qtqdm(Progress):
    def __init__(self, items, total=None, description="", open_browser=True, csv_path=None, initial=0,
                 capture_console=True, console_path=None, dashboard=None, desc=None):
        if desc is not None:
            if description:
                raise ValueError("Use desc or description, not both")
            description = desc
        super().__init__(items, total=total, description=description, csv_path=csv_path, initial=initial)
        self.open_browser = open_browser and os.environ.get("TQDMBOARD") != "1"
        self._owns_dashboard = dashboard is None
        self._dashboard = dashboard or Dashboard(self.snapshot, self.control.request)
        self.console = ConsoleOutput(console_path)
        self._console_capture = ConsoleCapture(self.console) if capture_console else None

    def snapshot(self):
        state = super().snapshot()
        state["console"] = self.console.snapshot()
        return state

    @property
    def server(self):
        return self._dashboard.server

    @property
    def url(self):
        return self._dashboard.url

    def _start_server(self):
        return self._dashboard.start()

    def __iter__(self):
        if self._start_server() and self.open_browser:
            webbrowser.open(self.url)
        return super().__iter__()

    def __enter__(self):
        if self._console_capture is not None:
            self._console_capture.start()
        try:
            if self._start_server() and self.open_browser:
                webbrowser.open(self.url)
        except BaseException:
            if self._console_capture is not None:
                self._console_capture.stop()
            raise
        return self

    def show(self):
        """Open or reopen the dashboard in the default browser."""
        self._start_server()
        webbrowser.open(self.url)
        return self.url

    def __exit__(self, error_type, error, traceback):
        self.control.finish()
        if error_type is not None:
            self.state = "failed"
            self.error = f"{error_type.__name__}: {error}"
            self.console.write("".join(traceback_module.format_exception(error_type, error, traceback)))
        elif self.state == "running":
            self.state = "stopped"
        if self.started_at is not None:
            self.finished_at = monotonic()
        self._close_log()
        if self._console_capture is not None:
            self._console_capture.stop()
        self.console.close()
        return False

    def close(self):
        if self._console_capture is not None:
            self._console_capture.stop()
        self.console.close()
        self.control.finish()
        self._close_log()
        if self._owns_dashboard:
            self._dashboard.close()

    def wait(self):
        """Keep a short script's dashboard open until Enter is pressed."""
        try:
            input("Press Enter to close the progress page...")
        except EOFError:
            pass
        finally:
            self.close()
