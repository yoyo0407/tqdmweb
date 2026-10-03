"""A tiny local web server for the progress page."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from time import monotonic
import webbrowser
import traceback as traceback_module

from .progress import Progress
from .console import ConsoleCapture, ConsoleOutput


class Qtqdm(Progress):
    def __init__(self, items, total=None, description="", open_browser=True, csv_path=None, initial=0,
                 capture_console=True, console_path=None):
        super().__init__(items, total=total, description=description, csv_path=csv_path, initial=initial)
        self.open_browser = open_browser
        self.server = None
        self.url = None
        self.console = ConsoleOutput(console_path)
        self._console_capture = ConsoleCapture(self.console) if capture_console else None

    def snapshot(self):
        state = super().snapshot()
        state["console"] = self.console.snapshot()
        return state

    def _start_server(self):
        if self.server is not None:
            return False

        progress = self
        page = Path(__file__).with_name("index.html").read_bytes()
        charts_script = Path(__file__).with_name("charts.js").read_bytes()
        console_script = Path(__file__).with_name("console.js").read_bytes()

        class Handler(BaseHTTPRequestHandler):
            def respond(self, content, kind, status=200):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)

            def respond_json(self, data, status=200):
                self.respond(json.dumps(data).encode("utf-8"), "application/json; charset=utf-8", status)

            def do_GET(self):
                if self.path == "/":
                    content, kind = page, "text/html; charset=utf-8"
                elif self.path == "/charts.js":
                    content, kind = charts_script, "text/javascript; charset=utf-8"
                elif self.path == "/console.js":
                    content, kind = console_script, "text/javascript; charset=utf-8"
                elif self.path == "/state":
                    content = json.dumps(progress.snapshot()).encode("utf-8")
                    kind = "application/json; charset=utf-8"
                else:
                    self.send_error(404)
                    return

                self.respond(content, kind)

            def do_POST(self):
                if self.path != "/control":
                    self.send_error(404)
                    return
                # Browser commands must come from our local page as JSON.
                origin = self.headers.get("Origin")
                if origin is not None and origin != progress.url.rstrip("/"):
                    self.respond_json({"error": "Origin is not allowed"}, 403)
                    return
                if self.headers.get_content_type() != "application/json":
                    self.respond_json({"error": "Send application/json"}, 415)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 4096:
                        raise ValueError("Invalid request size")
                    command = json.loads(self.rfile.read(length))
                    if not isinstance(command, dict):
                        raise ValueError("Expected a JSON object")
                    accepted = progress.control.request(command.get("action"), command.get("value"))
                except (ValueError, TypeError, UnicodeError) as error:
                    self.respond_json({"error": str(error)}, 400)
                    return
                if not accepted:
                    self.respond_json({"error": "Command unavailable: task ended, stopping, or save already pending"}, 409)
                    return
                self.respond_json({"accepted": True})

            def log_message(self, format, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/"
        print(f"Qtqdm page: {self.url}", flush=True)
        return True

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
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    def wait(self):
        """Keep a short script's dashboard open until Enter is pressed."""
        try:
            input("Press Enter to close the progress page...")
        except EOFError:
            pass
        finally:
            self.close()
