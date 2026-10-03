"""A local HTTP dashboard with supplied state and command callbacks."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread


class Dashboard:
    def __init__(self, get_state, request_control):
        self.get_state = get_state
        self.request_control = request_control
        self.server = None
        self.url = None

    def start(self):
        if self.server is not None:
            return False

        dashboard = self
        page = Path(__file__).with_name("index.html").read_bytes()
        charts_script = Path(__file__).with_name("charts.js").read_bytes()
        training_script = Path(__file__).with_name("training_view.js").read_bytes()
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
                elif self.path == "/training_view.js":
                    content, kind = training_script, "text/javascript; charset=utf-8"
                elif self.path == "/state":
                    content = json.dumps(dashboard.get_state()).encode("utf-8")
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
                if origin is not None and origin != dashboard.url.rstrip("/"):
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
                    accepted = dashboard.request_control(command.get("action"), command.get("value"))
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

    def close(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
