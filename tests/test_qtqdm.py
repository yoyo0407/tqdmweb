import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.request import urlopen

from qtqdm import Qtqdm
from qtqdm.progress import Progress


class ProgressTests(unittest.TestCase):
    def test_initial_progress_for_resumed_loop(self):
        progress = Progress(range(3, 5), initial=3)
        self.assertEqual(progress.total, 5)
        self.assertEqual(progress.snapshot()["rate"], 0)
        self.assertEqual(list(progress), [3, 4])
        self.assertEqual((progress.started, progress.completed), (5, 5))
        for invalid in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                Progress([], initial=invalid)
        with self.assertRaises(ValueError):
            Progress([], total=2, initial=3)

    def test_started_and_completed_counts(self):
        progress = Progress([1, 2])
        items = iter(progress)
        self.assertEqual(next(items), 1)
        self.assertEqual((progress.started, progress.completed), (1, 0))
        self.assertEqual(list(items), [2])
        self.assertEqual((progress.started, progress.completed), (2, 2))
        self.assertEqual(progress.state, "finished")

    def test_empty_and_unknown_length(self):
        empty = Progress([])
        self.assertEqual(list(empty), [])
        self.assertEqual(empty.state, "finished")
        unknown = Progress(x for x in range(3))
        self.assertEqual(list(unknown), [0, 1, 2])
        self.assertIsNone(unknown.snapshot()["remaining"])

    def test_reuse_is_rejected(self):
        progress = Progress([1, 2])
        list(progress)
        with self.assertRaises(RuntimeError):
            list(progress)
        self.assertEqual(progress.completed, 2)

    def test_full_run_history_is_bounded(self):
        progress = Progress(range(100_000))
        for step in progress:
            progress.set_postfix(loss=step)
        state = progress.snapshot()
        self.assertEqual(len(state["loss_recent"]), 300)
        self.assertLessEqual(len(state["loss_overview"]), 600)
        self.assertEqual(state["loss_overview"][0][1], 0)
        self.assertEqual(state["loss_overview"][-1][1], 99_999)

    def test_invalid_loss_does_not_corrupt_chart(self):
        progress = Progress([])
        progress.set_postfix(loss=0.5)
        for invalid in ("not a number", float("nan"), float("inf")):
            progress.set_postfix(loss=invalid)
        self.assertEqual(len(progress.snapshot()["loss_recent"]), 1)


class WebTests(unittest.TestCase):
    def make_progress(self, items):
        progress = Qtqdm(items, open_browser=False)
        self.addCleanup(progress.close)
        return progress

    def read_state(self, progress):
        with urlopen(progress.url + "state", timeout=3) as response:
            return json.load(response)

    def test_failure_reaches_page_and_is_reraised(self):
        progress = self.make_progress([1, 2, 3])
        with self.assertRaisesRegex(ValueError, "example failure"):
            with progress:
                for item in progress:
                    if item == 2:
                        raise ValueError("example failure")
        state = self.read_state(progress)
        self.assertEqual((state["started"], state["completed"]), (2, 1))
        self.assertEqual(state["state"], "failed")
        self.assertEqual(state["error"], "ValueError: example failure")

    def test_stopped_time_stays_fixed_after_iterator_closes(self):
        progress = self.make_progress([1, 2])
        with progress:
            items = iter(progress)
            next(items)
        stopped_time = progress.finished_at
        items.close()
        self.assertEqual(progress.finished_at, stopped_time)
        self.assertEqual(progress.state, "stopped")

    def test_reopen_and_close(self):
        progress = self.make_progress([1])
        with patch("qtqdm.web.webbrowser.open") as open_page:
            first = progress.show()
            self.assertEqual(progress.show(), first)
            self.assertEqual(open_page.call_count, 2)
        with urlopen(first, timeout=3) as response:
            self.assertIn(b"<canvas", response.read())
        progress.close()
        progress.close()
        self.assertIsNone(progress.server)

    def test_wait_without_terminal_input_closes_cleanly(self):
        progress = self.make_progress([])
        progress._start_server()
        with patch("builtins.input", side_effect=EOFError):
            progress.wait()
        self.assertIsNone(progress.server)


class CsvTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "training.csv"

    def read_rows(self):
        with self.path.open(newline="", encoding="utf-8-sig") as file:
            return list(csv.DictReader(file))

    def test_full_record_is_available_during_run(self):
        progress = Progress(range(650), csv_path=self.path)
        self.addCleanup(progress._close_log)
        for step in progress:
            progress.set_postfix(loss=step)
            if step == 0:
                self.assertEqual(self.read_rows()[0]["value"], "0")
        rows = self.read_rows()
        self.assertEqual(len(rows), 650)
        self.assertEqual([int(row["value"]) for row in rows], list(range(650)))
        self.assertEqual(rows[-1]["update"], "650")
        self.assertEqual(rows[-1]["item"], "650")
        self.assertTrue(progress._csv_log.file.closed)

    def test_dynamic_metrics_and_csv_escaping(self):
        progress = Progress([1], csv_path=self.path)
        for item in progress:
            progress.set_postfix(loss=0.25, note='中文, "引號"\n換行')
            progress.set_postfix(accuracy=0.9)
        rows = self.read_rows()
        self.assertEqual([row["metric"] for row in rows], ["loss", "note", "accuracy"])
        self.assertEqual([row["update"] for row in rows], ["1", "1", "2"])
        self.assertEqual(rows[1]["value"], '中文, "引號"\n換行')

    def test_failure_preserves_written_rows_and_closes_file(self):
        progress = Qtqdm(range(3), open_browser=False, csv_path=self.path)
        self.addCleanup(progress.close)
        with self.assertRaisesRegex(ValueError, "training failed"):
            with progress:
                for step in progress:
                    progress.set_postfix(loss=step)
                    if step == 1:
                        raise ValueError("training failed")
        self.assertEqual(len(self.read_rows()), 2)
        self.assertTrue(progress._csv_log.file.closed)

    def test_existing_file_is_not_overwritten(self):
        self.path.write_text("previous result", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            Progress([], csv_path=self.path)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "previous result")


if __name__ == "__main__":
    unittest.main()
