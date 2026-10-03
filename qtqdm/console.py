"""Mirror Python text output while keeping the original terminal stream."""

from pathlib import Path
import re
import sys
from threading import Lock


class ConsoleOutput:
    def __init__(self, path=None, max_chars=65536):
        self._lock = Lock()
        self._text = ""
        self._version = 0
        self._trimmed = 0
        self._error = None
        self.max_chars = max_chars
        self.path = Path(path).resolve() if path is not None else None
        self._file = self.path.open("x", encoding="utf-8", newline="") if self.path is not None else None

    def write(self, text):
        with self._lock:
            if self._file is not None:
                try:
                    self._file.write(text)
                    self._file.flush()
                except OSError as error:
                    self._error = f"{type(error).__name__}: {error}"
                    try:
                        self._file.close()
                    except OSError:
                        pass
                    self._file = None
            self._text += text
            overflow = max(0, len(self._text) - self.max_chars)
            if overflow:
                self._text = self._text[overflow:]
                self._trimmed += overflow
            self._version += 1

    def snapshot(self):
        with self._lock:
            # The browser is a text viewer, not a terminal emulator.
            text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", self._text)
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            return {"text": text, "version": self._version, "trimmed_chars": self._trimmed,
                    "path": str(self.path) if self.path is not None else None, "error": self._error}

    def close(self):
        with self._lock:
            if self._file is not None:
                try:
                    self._file.close()
                except OSError as error:
                    self._error = f"{type(error).__name__}: {error}"
                finally:
                    self._file = None


class TeeStream:
    def __init__(self, original, output):
        self.original = original
        self.output = output

    def write(self, text):
        result = self.original.write(text)
        if text:
            self.output.write(text)
        return result

    def flush(self):
        return self.original.flush()

    def __getattr__(self, name):
        return getattr(self.original, name)


class ConsoleCapture:
    _active = None
    _lock = Lock()

    def __init__(self, output):
        self.output = output
        self.stdout = None
        self.stderr = None

    def start(self):
        with self._lock:
            if self._active is self:
                return
            if self._active is not None:
                raise RuntimeError("Only one console capture can run per process; use capture_console=False")
            self.stdout = TeeStream(sys.stdout, self.output)
            self.stderr = TeeStream(sys.stderr, self.output)
            sys.stdout, sys.stderr = self.stdout, self.stderr
            ConsoleCapture._active = self

    def stop(self):
        with self._lock:
            if self._active is not self:
                return
            if sys.stdout is self.stdout:
                sys.stdout = self.stdout.original
            if sys.stderr is self.stderr:
                sys.stderr = self.stderr.original
            ConsoleCapture._active = None
