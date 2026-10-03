"""A tiny local web server for the progress page."""

from time import monotonic
import webbrowser
import traceback as traceback_module
import os
import sqlite3
from threading import Lock

from .progress import Progress
from .console import ConsoleCapture, ConsoleOutput
from .dashboard import Dashboard
from .board_records import archive_progress


# tqdm terminal display options with no meaning on a web page; accepted so scripts run unchanged.
TQDM_DISPLAY_OPTIONS = frozenset({
    "file", "ncols", "nrows", "mininterval", "maxinterval", "miniters", "ascii", "dynamic_ncols",
    "smoothing", "bar_format", "position", "unit_scale", "unit_divisor", "write_bytes", "lock_args",
    "colour", "delay",
})

_active_lock = Lock()
_active_bars = []  # running bars in start order; a new bar nests under the last one


class _ChildControl:
    """Lets a nested bar pause, stop and save through the outermost bar's controls."""

    def __init__(self, root_control):
        self._root = root_control

    def checkpoint(self, final=False, completed=None):
        if final:
            return not self._root.stop_requested
        return self._root.checkpoint()

    @property
    def stop_requested(self):
        return self._root.stop_requested

    def finish(self):
        pass

    def snapshot(self):
        return self._root.snapshot()

    def register_controls(self, **handlers):
        raise RuntimeError("Register controls on the outermost bar")


class Qtqdm(Progress):
    def __init__(self, items=None, total=None, description="", open_browser=True, csv_path=None, initial=0,
                 capture_console=True, console_path=None, desc=None, *, leave=True, disable=False,
                 unit="it", postfix=None, **tqdm_options):
        unknown = set(tqdm_options) - TQDM_DISPLAY_OPTIONS
        if unknown:
            raise TypeError(f"Unsupported Qtqdm argument(s): {', '.join(sorted(unknown))}")
        if desc is not None:
            if description:
                raise ValueError("Use desc or description, not both")
            description = desc
        super().__init__(items, total=total, description=description, csv_path=csv_path, initial=initial)
        self.unit = unit
        self.leave = leave
        self.disable = disable
        self.depth = 0
        self.root = self
        self._children = []
        self._archived = False
        self.open_browser = open_browser and os.environ.get("TQDMBOARD") != "1"
        self._dashboard = Dashboard(self.snapshot, self.control.request, self.history_since)
        self.console = ConsoleOutput(console_path)
        self._console_capture = ConsoleCapture(self.console) if capture_console and not disable else None
        if not disable:
            with _active_lock:
                if _active_bars:
                    self._attach_to(_active_bars[-1])
        if postfix:
            self.set_postfix(postfix if isinstance(postfix, dict) else {"postfix": postfix})

    @property
    def is_child(self):
        return self.root is not self

    @property
    def _has_page(self):
        return not self.disable and not self.is_child

    def _attach_to(self, parent):
        """Show this bar on the outermost page instead of starting another server."""
        self.root = parent.root
        self.depth = parent.depth + 1
        self.control = _ChildControl(self.root.control)
        self._console_capture = None
        self.open_browser = False
        # A new inner loop replaces finished bars at its level, like a terminal redraw.
        self.root._children = [bar for bar in self.root._children
                               if bar.depth < self.depth or bar.state in ("waiting", "running")]
        self.root._children.append(self)

    def _on_start(self):
        # Only running bars can own nested bars, so an unused bar never captures later ones.
        if not self.disable:
            with _active_lock:
                _active_bars.append(self)

    def _deactivate(self):
        with _active_lock:
            if self in _active_bars:
                _active_bars.remove(self)
            if self.is_child and not self.leave and self in self.root._children:
                self.root._children.remove(self)

    def set_postfix(self, ordered_dict=None, refresh=True, **values):
        if not self.is_child:
            super().set_postfix(ordered_dict, refresh, **values)
            return
        # Inner loops usually report per-batch loss; chart it on the outermost page.
        values = {**(ordered_dict or {}), **values}
        self.metrics = {**self.metrics, **{key: str(value) for key, value in values.items()}}
        self.root.set_postfix(values)

    def register_controls(self, **handlers):
        if self.is_child:
            raise RuntimeError("Register controls on the outermost bar")
        return super().register_controls(**handlers)

    def mark(self, label):
        if self.is_child:
            return self.root.mark(label)
        return super().mark(label)

    def _archive_result(self):
        if self._archived or not self._has_page:
            return
        try:
            archive_progress(self)
            self._archived = True
        except (OSError, ValueError, sqlite3.Error) as error:
            print(f'Run record could not be finalized: {error}', flush=True)

    def snapshot(self):
        state = super().snapshot()
        state["console"] = self.console.snapshot()
        state["unit"] = self.unit
        with _active_lock:
            children = list(self._children)
        state["bars"] = [{**bar.bar_summary(), "depth": bar.depth, "unit": bar.unit} for bar in children]
        return state

    @property
    def server(self):
        return self._dashboard.server

    @property
    def url(self):
        return self.root._dashboard.url

    def _start_server(self):
        if not self._has_page:
            return False
        return self._dashboard.start()

    def _open_page(self):
        if self._start_server() and self.open_browser:
            webbrowser.open(self.url)

    def __iter__(self):
        self._open_page()
        return self._tracked(super().__iter__())

    def _tracked(self, iterator):
        try:
            yield from iterator
        finally:
            self._deactivate()

    def update(self, n=1):
        self._open_page()
        super().update(n)

    def __enter__(self):
        if self._console_capture is not None:
            self._console_capture.start()
        try:
            self._open_page()
            if self.manual:
                self._begin()
        except BaseException:
            if self._console_capture is not None:
                self._console_capture.stop()
            raise
        return self

    def show(self):
        """Open or reopen the dashboard in the default browser."""
        if self.disable:
            return None
        if self.is_child:
            return self.root.show()
        self._start_server()
        webbrowser.open(self.url)
        return self.url

    def __exit__(self, error_type, error, traceback):
        if error_type is None:
            self._finalize_manual()
        self._deactivate()
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
        self._archive_result()
        return False

    def close(self):
        self._finalize_manual()
        self._deactivate()
        if self._console_capture is not None:
            self._console_capture.stop()
        self.console.close()
        self.control.finish()
        self._close_log()
        self._archive_result()
        self._dashboard.close()

    def wait(self):
        """Keep a short script's dashboard open until Enter is pressed."""
        if os.environ.get("TQDMBOARD") == "1" or not self._has_page:
            # Board owns the result view and persistent history after process exit.
            self.close()
            return
        try:
            input("Press Enter to close the progress page...")
        except EOFError:
            pass
        finally:
            self.close()


def trange(*args, **kwargs):
    """Shortcut for Qtqdm(range(*args), **kwargs), like tqdm.trange."""
    return Qtqdm(range(*args), **kwargs)
