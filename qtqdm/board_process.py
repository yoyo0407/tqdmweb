"""One subprocess at a time, independent of the app HTTP server."""

import codecs
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import Lock, Thread
from urllib.error import URLError
from urllib.request import Request, urlopen

from .board_files import validate_launch
from .console import ConsoleOutput


class ProcessRunner:
    def __init__(self, project_root, records=None):
        self.project_root = Path(project_root).resolve()
        self.records = records
        self.record_id = None
        self._lock = Lock()
        self._process = None
        self._pending = None
        self._closing = False
        self.job_id = 0
        self.state = "idle"
        self.exit_code = None
        self.dashboard_url = None
        self.config = None
        self.error = None
        self.console = ConsoleOutput()
        self._reader_thread = None

    def _start_locked(self, config):
        log_folder = self.project_root / "runs" / "tqdmboard"
        log_folder.mkdir(parents=True, exist_ok=True)
        log_path = log_folder / f"process_{datetime.now():%Y%m%d_%H%M%S_%f}.log"
        output = ConsoleOutput(log_path)
        environment = os.environ.copy()
        environment["TQDMBOARD"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONPATH"] = str(self.project_root) + os.pathsep + environment.get("PYTHONPATH", "")
        command = [config["python"], "-u", config["script"], *config["argv"]]
        record_id = self.records.start(config, log_path) if self.records else None
        if self.records:
            environment['TQDMBOARD_RECORD_ID'] = record_id
            environment['TQDMBOARD_RECORDS_PATH'] = str(self.records.path.resolve())
        try:
            process = subprocess.Popen(command, cwd=config["working_directory"], env=environment,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except OSError:
            output.close()
            if self.records:
                self.records.finish(record_id, "failed", None)
            raise
        self.job_id += 1
        self._process = process
        self.console = output
        self.config = config
        self.record_id = record_id
        self.state = "running"
        self.exit_code = None
        self.dashboard_url = None
        self.error = None
        output.write(f"Command: {subprocess.list2cmdline(command)}\nWorking directory: {config['working_directory']}\n\n")
        self._reader_thread = Thread(target=self._watch, args=(process, output), daemon=True)
        self._reader_thread.start()

    def start(self, data):
        config = validate_launch(data)
        with self._lock:
            if self._closing:
                raise ValueError("App is closing")
            if self._process is not None and self._process.poll() is None:
                raise ValueError("A process is already running; use Restart Process or Stop Process")
            if self._pending is not None:
                raise ValueError("Process restart is pending")
            self._start_locked(config)

    def restart(self, data):
        config = validate_launch(data)
        with self._lock:
            if self._closing or self._pending is not None:
                raise ValueError("Restart is unavailable")
            if self._process is None or self._process.poll() is not None:
                self._start_locked(config)
                return
            self._pending = config
        self.stop()

    def stop(self):
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                return
            if self.state == "stopping":
                return
            self.state = "stopping"
            dashboard_url = self.dashboard_url
        Thread(target=self._stop_gracefully, args=(process, dashboard_url), daemon=True).start()

    def _request_training_stop(self, dashboard_url):
        request = Request(dashboard_url + "control", data=json.dumps({"action": "stop"}).encode(),
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=1):
                pass
        except (URLError, OSError):
            pass

    def _stop_gracefully(self, process, dashboard_url):
        if dashboard_url:
            self._request_training_stop(dashboard_url)
        try:
            process.stdin.write(b"\n")
            process.stdin.flush()
            process.wait(timeout=3)
        except (OSError, ValueError):
            pass
        except subprocess.TimeoutExpired:
            with self._lock:
                if self._process is process and process.poll() is None:
                    self.error = "Process is still stopping. Force Stop terminates it without guaranteed checkpoint saving."

    def force_stop(self):
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self.state = "stopping"
                if os.name == "nt":
                    # venv python.exe can be a redirector with a child interpreter.
                    result = subprocess.run(["taskkill", "/PID", str(self._process.pid), "/T", "/F"],
                                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            creationflags=subprocess.CREATE_NO_WINDOW, check=False)
                    if result.returncode != 0 and self._process.poll() is None:
                        self.error = result.stdout.decode(errors="replace").strip()
                        raise OSError("Force Stop failed: " + self.error)
                else:
                    self._process.terminate()

    def _watch(self, process, output):
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        tail = ""
        while True:
            chunk = os.read(process.stdout.fileno(), 4096)
            if not chunk:
                break
            text = decoder.decode(chunk)
            output.write(text)
            try:
                sys.stdout.write(text)
                sys.stdout.flush()
            except (OSError, UnicodeError):
                pass
            tail = (tail + text)[-2048:]
            match = re.search(r"Qtqdm page: (http://127\.0\.0\.1:\d+/)", tail)
            if match:
                stop_after_initialization = False
                with self._lock:
                    if self._process is process:
                        stop_after_initialization = self.dashboard_url is None and self.state == "stopping"
                        self.dashboard_url = match.group(1)
                if stop_after_initialization:
                    Thread(target=self._request_training_stop, args=(match.group(1),), daemon=True).start()
        remaining = decoder.decode(b"", final=True)
        if remaining:
            output.write(remaining)
        code = process.wait()
        process.stdout.close()
        process.stdin.close()
        output.close()
        with self._lock:
            if self._process is not process:
                return
            self.exit_code = code
            self.state = "exited" if code == 0 else "failed"
            if self.records:
                self.records.finish(self.record_id, self.state, code)
            self.error = None
            if self._pending is not None and not self._closing:
                config = self._pending
                self._pending = None
                try:
                    self._start_locked(config)
                except OSError as error:
                    self.state = "failed"
                    self.error = str(error)

    def snapshot(self):
        with self._lock:
            alive = self._process is not None and self._process.poll() is None
            return {"job_id": self.job_id, "record_id": self.record_id, "state": self.state, "running": alive,
                    "pid": self._process.pid if self._process is not None else None,
                    "exit_code": self.exit_code, "restart_pending": self._pending is not None,
                    "dashboard_url": self.dashboard_url, "config": self.config,
                    "error": self.error, "console": self.console.snapshot()}

    def close(self):
        with self._lock:
            self._closing = True
            self._pending = None
            process = self._process
        try:
            self.stop()
            if process is not None:
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.force_stop()
                    process.wait(timeout=3)
        finally:
            if self._reader_thread is not None:
                self._reader_thread.join(timeout=1)
            self.console.close()
