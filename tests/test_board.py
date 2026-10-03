import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from qtqdm.board import TqdmBoard
from qtqdm.board_files import python_environments, split_arguments
from qtqdm.board_process import ProcessRunner


def wait_until(predicate, seconds=6):
    deadline = monotonic() + seconds
    while not predicate():
        if monotonic() >= deadline:
            raise AssertionError("Timed out waiting for process")
        sleep(0.02)


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix="tqdmboard space ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def config(self, script, arguments=""):
        return {"script": str(script), "python": sys.executable,
                "working_directory": str(self.root), "arguments": arguments}

    def test_environment_discovery_and_argument_parsing(self):
        self.assertIn(sys.executable, python_environments(self.root))
        if os.name == "nt":
            self.assertEqual(split_arguments('--path "C:\\folder name\\file.py" --text "two words"'),
                             ["--path", "C:\\folder name\\file.py", "--text", "two words"])
        self.assertEqual(split_arguments('"" literal&value'), ["", "literal&value"])

    def test_process_output_arguments_cwd_exit_and_relaunch(self):
        script = self.root / "example script.py"
        script.write_text("import os,sys\nprint(os.getcwd())\nprint(sys.argv[1:])\nprint('stderr marker',file=sys.stderr)\n", encoding="utf-8")
        runner = ProcessRunner(self.root)
        self.addCleanup(runner.close)
        runner.start(self.config(script, '"two words" literal&value'))
        wait_until(lambda: runner.snapshot()["state"] == "exited")
        first = runner.snapshot()
        self.assertEqual(first["exit_code"], 0)
        self.assertIn(str(self.root), first["console"]["text"])
        self.assertIn("['two words', 'literal&value']", first["console"]["text"])
        self.assertIn("stderr marker", first["console"]["text"])
        self.assertEqual(Path(first["console"]["path"]).read_text(encoding="utf-8"), first["console"]["text"])
        runner.restart(self.config(script))
        wait_until(lambda: runner.snapshot()["job_id"] == 2 and runner.snapshot()["state"] == "exited")
        self.assertNotEqual(runner.snapshot()["console"]["path"], first["console"]["path"])
        self.assertTrue(Path(first["console"]["path"]).is_file())

    def test_running_process_restart_and_force_stop(self):
        script = self.root / "wait.py"
        script.write_text("print('ready',flush=True)\ninput()\n", encoding="utf-8")
        runner = ProcessRunner(self.root)
        self.addCleanup(runner.close)
        config = self.config(script)
        runner.start(config)
        wait_until(lambda: "ready" in runner.snapshot()["console"]["text"])
        with self.assertRaises(ValueError):
            runner.start(config)
        runner.restart(config)
        wait_until(lambda: runner.snapshot()["job_id"] == 2 and "ready" in runner.snapshot()["console"]["text"])
        runner.force_stop()
        wait_until(lambda: not runner.snapshot()["running"] and runner.snapshot()["state"] in ("exited", "failed"))

    def test_app_stays_alive_after_script_exit_and_rejects_foreign_origin(self):
        script = self.root / "example.py"
        script.write_text("print('completed')\n", encoding="utf-8")
        board = TqdmBoard(self.root, records_path=self.root / 'records.sqlite3')
        board.runner.project_root = self.root
        self.addCleanup(board.close)
        url = board.start()
        with urlopen(url + "config", timeout=3) as response:
            self.assertEqual(json.load(response)["config"]["working_directory"], str(self.root))
        request = Request(url + "run", data=json.dumps(self.config(script)).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=3) as response:
            self.assertTrue(json.load(response)["accepted"])
        wait_until(lambda: board.runner.snapshot()["state"] == "exited")
        with urlopen(url, timeout=3) as response:
            self.assertIn(b"Choose Script...", response.read())
        malicious = Request(url + "run", data=b"{}", headers={"Content-Type": "application/json", "Origin": "https://example.com"})
        with self.assertRaises(HTTPError) as error:
            urlopen(malicious, timeout=3)
        self.assertEqual(error.exception.code, 403)

    def test_native_script_selection_and_cancel_through_http(self):
        script = self.root / "測試 script.py"
        script.write_text("print('selected')", encoding="utf-8")
        board = TqdmBoard(self.root, records_path=self.root / 'records.sqlite3')
        self.addCleanup(board.close)
        url = board.start()
        def select():
            request = Request(url + "select-path", data=json.dumps({"kind": "script"}).encode(),
                              headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=3) as response:
                return json.load(response)
        with patch.object(board.picker, "pick", return_value=str(script)):
            result = select()
            self.assertEqual(result["path"], str(script))
            self.assertEqual(result["working_directory"], str(self.root))
            self.assertIn(sys.executable, result["python_environments"])
        with patch.object(board.picker, "pick", return_value=None):
            self.assertIsNone(select()["path"])
        with self.assertRaises(HTTPError) as error:
            urlopen(url + "browse", timeout=3)
        self.assertEqual(error.exception.code, 404)

    def test_stop_during_initialization_reaches_late_dashboard(self):
        script = self.root / "initialize.py"
        script.write_text("from time import sleep\nfrom qtqdm import Qtqdm\n"
                          "print('initializing',flush=True)\nsleep(0.2)\n"
                          "p=Qtqdm(range(1000),open_browser=False)\n"
                          "with p:\n    for step in p:\n        sleep(0.001)\n"
                          "print('result='+p.state,flush=True)\np.wait()\n", encoding="utf-8")
        runner = ProcessRunner(Path.cwd())
        self.addCleanup(runner.close)
        runner.start(self.config(script))
        wait_until(lambda: "initializing" in runner.snapshot()["console"]["text"])
        self.assertIsNone(runner.snapshot()["dashboard_url"])
        runner.stop()
        wait_until(lambda: runner.snapshot()["state"] == "exited")
        self.assertIn("result=stopped", runner.snapshot()["console"]["text"])


if __name__ == "__main__":
    unittest.main()
