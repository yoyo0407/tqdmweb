import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from qtqdm.board import TqdmBoard
from qtqdm.board_files import browse_folder, split_arguments
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

    def test_file_browser_and_argument_parsing(self):
        (self.root / "subfolder").mkdir()
        (self.root / "example.py").write_text("", encoding="utf-8")
        (self.root / "ignored.txt").write_text("", encoding="utf-8")
        listing = browse_folder(self.root)
        self.assertEqual([item["name"] for item in listing["entries"]], ["subfolder", "example.py"])
        self.assertTrue(listing["entries"][0]["directory"])
        self.assertIn(sys.executable, listing["python_environments"])
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
        board = TqdmBoard(self.root)
        board.runner.project_root = self.root
        self.addCleanup(board.close)
        url = board.start()
        with urlopen(url + "browse", timeout=3) as response:
            self.assertEqual(json.load(response)["path"], str(self.root))
        request = Request(url + "run", data=json.dumps(self.config(script)).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=3) as response:
            self.assertTrue(json.load(response)["accepted"])
        wait_until(lambda: board.runner.snapshot()["state"] == "exited")
        with urlopen(url, timeout=3) as response:
            self.assertIn(b"Local File Browser", response.read())
        malicious = Request(url + "run", data=b"{}", headers={"Content-Type": "application/json", "Origin": "https://example.com"})
        with self.assertRaises(HTTPError) as error:
            urlopen(malicious, timeout=3)
        self.assertEqual(error.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
