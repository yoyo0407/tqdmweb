"""Local app server: native selection, process launcher and Qtqdm UI."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import shutil
from pathlib import Path
import sys
from threading import Event, Thread
from urllib.parse import parse_qs, urlsplit
import webbrowser

from .board_files import python_environments
from .board_dialog import NativePicker
from .board_process import ProcessRunner
from .board_monitor import ResourceMonitor
from .board_training import TrainingBridge
from .board_records import RunRecords
from .board_viewers import BoardViewers
from .board_files import validate_launch
from .board_checkpoints import inspect_checkpoint
from .board_errors import failure_info


class TqdmBoard:
    def __init__(self, directory=None, port=0, records_path=None):
        self.project_root = Path(__file__).resolve().parent.parent
        self.directory = Path(directory or self.project_root).resolve(strict=True)
        self.records = RunRecords(records_path or self.project_root / "runs" / "tqdmboard" / "records.sqlite3")
        self.records.recover()
        self.viewers = BoardViewers()
        self.runner = ProcessRunner(self.project_root, self.records)
        self.monitor = ResourceMonitor()
        self.training = TrainingBridge(self.runner, self.records)
        self.picker = NativePicker(self.directory)
        self.closed = Event()
        self.server = None
        self.port = port
        self.url = None

    def start(self):
        board = self
        assets = {"/": ("board.html", "text/html"), "/board.js": ("board.js", "text/javascript"),
                  "/board_history.js": ("board_history.js", "text/javascript"),
                  "/board_errors.js": ("board_errors.js", "text/javascript"),
                  "/resources.js": ("resources.js", "text/javascript"),
                  "/console.js": ("console.js", "text/javascript"),
                  "/charts.js": ("charts.js", "text/javascript"),
                  "/training_view.js": ("training_view.js", "text/javascript")}
        files = {route: (Path(__file__).with_name(name).read_bytes(), kind) for route, (name, kind) in assets.items()}

        class Handler(BaseHTTPRequestHandler):
            def respond(self, content, kind, status=200):
                self.send_response(status)
                self.send_header("Content-Type", kind + "; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)

            def respond_json(self, data, status=200):
                self.respond(json.dumps(data).encode("utf-8"), "application/json", status)

            def valid_host(self):
                if self.headers.get("Host") != urlsplit(board.url).netloc:
                    self.respond_json({"error": "Host is not allowed"}, 403)
                    return False
                return True

            def do_GET(self):
                if not self.valid_host():
                    return
                route = urlsplit(self.path)
                try:
                    if route.path in files:
                        self.respond(*files[route.path])
                    elif route.path == "/state":
                        process = board.runner.snapshot()
                        training = board.training.snapshot(process)
                        process['failure'] = process.get('failure') or failure_info(process['state'], process['exit_code'], process['console'], training['data'], process['error'])
                        self.respond_json({**process, "resources": board.monitor.snapshot(),
                                           "training": training})
                    elif route.path == "/config":
                        config = board.runner.snapshot()["config"]
                        script = board.directory / "rl2048_demo.py"
                        self.respond_json({"python_environments": python_environments(board.directory), "config": config or {
                            "script": str(script) if script.is_file() else "", "python": sys.executable,
                            "working_directory": str(board.directory), "arguments": ""}})
                    elif route.path == "/training-history":
                        query = parse_qs(route.query)
                        self.respond_json(board.training.history_since(int(query.get("job_id", ["-1"])[0]),
                                                                      int(query.get("after", ["0"])[0])))
                    elif route.path == "/records":
                        self.respond_json(board.records.list())
                    elif route.path == '/record-export':
                        record_id = parse_qs(route.query).get('id', [''])[0]
                        with board.records.export(record_id) as output:
                            output.seek(0, 2)
                            size = output.tell()
                            output.seek(0)
                            self.send_response(200)
                            self.send_header('Content-Type', 'application/zip')
                            self.send_header('Content-Disposition', f'attachment; filename="run-{record_id}.zip"')
                            self.send_header('Content-Length', str(size))
                            self.end_headers()
                            shutil.copyfileobj(output, self.wfile)
                    elif route.path in ("/record", "/record-history"):
                        query = parse_qs(route.query)
                        record_id = query.get("id", [""])[0]
                        self.respond_json(board.records.get(record_id) if route.path == "/record" else
                                          board.records.history(record_id, int(query.get("after", ["0"])[0])))
                    else:
                        self.send_error(404)
                except (OSError, ValueError) as error:
                    self.respond_json({"error": str(error)}, 400)

            def do_POST(self):
                if not self.valid_host():
                    return
                origin = self.headers.get("Origin")
                if origin is not None and origin != board.url.rstrip("/"):
                    self.respond_json({"error": "Origin is not allowed"}, 403)
                    return
                if self.headers.get_content_type() != "application/json":
                    self.respond_json({"error": "Send application/json"}, 415)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 16384:
                        raise ValueError("Invalid request size")
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict):
                        raise ValueError("Expected a JSON object")
                    if self.path == "/viewer":
                        board.viewers.update(data.get("id"), data.get("closed") is True, data.get("sequence"))
                    elif self.path == "/select-path":
                        path = board.picker.pick(data.get("kind"), data.get("initial"))
                        result = {"path": path}
                        if path and data["kind"] == "script":
                            result.update(working_directory=str(Path(path).parent),
                                          python_environments=python_environments(Path(path).parent))
                        self.respond_json(result)
                        return
                    elif self.path == "/training-control":
                        result, status = board.training.control(data)
                        self.respond_json(result, status)
                        return
                    elif self.path == '/inspect-checkpoint':
                        config = validate_launch(data)
                        self.respond_json(inspect_checkpoint(config, data.get('checkpoint_path', '')))
                        return
                    elif self.path == '/record-rename':
                        board.records.rename(data.get('id'), data.get('name'))
                    elif self.path == '/record-delete':
                        board.records.delete(data.get('id'))
                    elif self.path == "/run":
                        board.runner.start(data)
                    elif self.path == "/restart":
                        board.runner.restart(data)
                    elif self.path == "/stop":
                        board.runner.stop()
                    elif self.path == "/force-stop":
                        board.runner.force_stop()
                    elif self.path == "/shutdown":
                        board.closed.set()
                    else:
                        self.send_error(404)
                        return
                    self.respond_json({"accepted": True})
                except (OSError, ValueError, TypeError, UnicodeError) as error:
                    self.respond_json({"error": str(error)}, 400)

            def log_message(self, format, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/"
        self.monitor.start()
        self.training.start()
        Thread(target=self.server.serve_forever, daemon=True).start()
        Thread(target=self._watch_viewers, daemon=True).start()
        print(f"tqdmboard: {self.url}", flush=True)
        return self.url

    def _watch_viewers(self):
        while not self.closed.wait(0.25):
            if self.viewers.should_close():
                self.closed.set()

    def close(self):
        self.closed.set()
        try:
            self.runner.close()
        finally:
            self.training.close()
            self.records.close()
            self.monitor.close()
            self.picker.close()
            if self.server is not None:
                self.server.shutdown()
                self.server.server_close()
                self.server = None


def main():
    parser = argparse.ArgumentParser(description="Launch Python training scripts from a local browser app")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--records-path", type=Path, help="Run history database location")
    args = parser.parse_args()
    board = TqdmBoard(args.directory, args.port, args.records_path)
    try:
        url = board.start()
        if not args.no_browser:
            webbrowser.open(url)
        print("Press Ctrl+C to stop tqdmboard.", flush=True)
        board.closed.wait()
    except KeyboardInterrupt:
        pass
    finally:
        board.close()
