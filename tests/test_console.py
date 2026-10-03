import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.request import urlopen

from qtqdm import Qtqdm
from qtqdm.console import ConsoleOutput


class ConsoleTests(unittest.TestCase):
    def test_stdout_stderr_are_mirrored_and_restored(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        progress = Qtqdm([], open_browser=False)
        self.addCleanup(progress.close)
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            with progress:
                print("stdout message", end="")
                print("stderr message", file=sys.stderr)
                sys.stdout.flush()
                self.assertEqual(sys.stdout.encoding, stdout.encoding)
            self.assertIs(sys.stdout, stdout)
            self.assertIs(sys.stderr, stderr)
        self.assertIn("stdout message", stdout.getvalue())
        self.assertIn("stderr message", stderr.getvalue())
        with urlopen(progress.url + "state", timeout=3) as response:
            text = json.load(response)["console"]["text"]
        self.assertIn("stdout messagestderr message\n", text)

    def test_failure_traceback_is_retained_and_streams_restored(self):
        progress = Qtqdm([], open_browser=False)
        self.addCleanup(progress.close)
        stdout, stderr = sys.stdout, sys.stderr
        with self.assertRaisesRegex(ValueError, "training failed"):
            with progress:
                print("before failure")
                raise ValueError("training failed")
        self.assertIs(sys.stdout, stdout)
        self.assertIs(sys.stderr, stderr)
        text = progress.snapshot()["console"]["text"]
        self.assertIn("before failure", text)
        self.assertIn("Traceback", text)
        self.assertIn("ValueError: training failed", text)

    def test_bounded_view_keeps_full_log_and_flushes(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "console.log"
            output = ConsoleOutput(path, max_chars=16)
            try:
                output.write("first line\n")
                output.write("second line is longer\n")
                self.assertEqual(path.read_text(encoding="utf-8"), "first line\nsecond line is longer\n")
                state = output.snapshot()
                self.assertEqual(len(state["text"]), 16)
                self.assertEqual(state["trimmed_chars"], 17)
                self.assertEqual(state["version"], 2)
            finally:
                output.close()
            with self.assertRaises(FileExistsError):
                ConsoleOutput(path)

    def test_log_write_failure_does_not_interrupt_output(self):
        output = ConsoleOutput()
        file = Mock()
        file.write.side_effect = OSError("disk full")
        output._file = file
        output.write("still visible\n")
        output.write("another line\n")
        state = output.snapshot()
        self.assertIn("still visible", state["text"])
        self.assertEqual(state["error"], "OSError: disk full")
        file.close.assert_called_once()

    def test_plain_text_normalizes_ansi_and_carriage_returns(self):
        output = ConsoleOutput()
        output.write("\x1b[31mred\x1b[0m\rnext\r\n")
        self.assertEqual(output.snapshot()["text"], "red\nnext\n")

    def test_capture_can_be_disabled_and_conflicting_capture_is_rejected(self):
        first = Qtqdm([], open_browser=False)
        second = Qtqdm([], open_browser=False)
        disabled = Qtqdm([], open_browser=False, capture_console=False)
        for progress in (first, second, disabled):
            self.addCleanup(progress.close)
        with first:
            with self.assertRaisesRegex(RuntimeError, "Only one console capture"):
                with second:
                    pass
            with disabled:
                print("outer capture only")
        self.assertIn("outer capture only", first.snapshot()["console"]["text"])
        self.assertNotIn("outer capture only", disabled.snapshot()["console"]["text"])


if __name__ == "__main__":
    unittest.main()
