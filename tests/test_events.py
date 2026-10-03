from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest

from qtqdm import Qtqdm
from qtqdm.board_records import RunRecords
from qtqdm.progress import Progress


class EventTests(unittest.TestCase):
    def test_pause_and_resume_are_recorded_at_the_boundary(self):
        progress = Progress(total=5)
        paused, done = Event(), Event()

        def record(kind, label):
            progress._record_event(kind, label)
            if kind == "pause":
                paused.set()

        progress.control.on_event = record
        progress.control.request("pause")
        self.assertEqual(progress.events, [])
        worker = Thread(target=lambda: (progress.update(), done.set()), daemon=True)
        worker.start()
        try:
            self.assertTrue(paused.wait(2))
            self.assertFalse(done.is_set())
            self.assertEqual([event[1] for event in progress.events], ["pause"])
            progress.control.request("resume")
            self.assertTrue(done.wait(2))
            self.assertEqual([event[1] for event in progress.events], ["pause", "resume"])
        finally:
            progress.control.request("stop")
            worker.join(timeout=2)

    def test_learning_rate_records_success_and_old_and_new_values(self):
        progress = Progress(total=2)
        applied = []
        progress.register_controls(set_learning_rate=applied.append, learning_rate=0.001)
        progress.control.request("learning_rate", 0.0001)
        self.assertEqual(progress.events, [])
        progress.update()
        self.assertEqual(applied, [0.0001])
        self.assertEqual(progress.events[0][1:], ["learning_rate", 1, 0, "LR 0.001 → 0.0001"])

    def test_failed_learning_rate_does_not_record_success(self):
        progress = Progress(total=2)

        def reject(value):
            raise ValueError("rejected")

        progress.register_controls(set_learning_rate=reject, learning_rate=0.001)
        progress.control.request("learning_rate", 0.0001)
        progress.update()
        self.assertEqual(progress.events, [])
        self.assertIn("rejected", progress.control.snapshot()["learning_rate_error"])

    def test_save_success_uses_only_the_filename_and_failure_is_recorded(self):
        progress = Progress(total=3)
        paths = iter(["runs/x/model_1.pt", None])

        def save():
            path = next(paths)
            if path is None:
                raise OSError("disk full")
            return path

        progress.register_controls(save_checkpoint=save)
        progress.control.request("save")
        self.assertEqual(progress.events, [])
        progress.update()
        progress.control.request("save")
        progress.update()
        self.assertEqual([(event[1], event[4]) for event in progress.events],
                         [("save", "Saved model_1.pt"), ("save_error", "Save failed")])

    def test_scheduled_save_records_when_the_step_is_reached(self):
        progress = Progress(total=3)
        progress.register_controls(save_checkpoint=lambda: "scheduled.pt")
        progress.control.request("schedule_save", 2)
        progress.update()
        self.assertEqual(progress.events, [])
        progress.update()
        self.assertEqual(progress.events[0][1:], ["save", 2, 0, "Saved scheduled.pt"])

    def test_stop_is_recorded_once(self):
        progress = Progress(total=3)
        progress.control.request("stop")
        self.assertEqual(progress.events, [])
        progress.update()
        progress.control.checkpoint()
        progress.control.checkpoint(final=True)
        progress._finalize_manual()
        self.assertEqual([(event[1], event[4]) for event in progress.events], [("stop", "Stopped")])

    def test_stopping_a_paused_loop_does_not_record_resume(self):
        progress = Progress(total=2)

        def record(kind, label):
            progress._record_event(kind, label)
            if kind == "pause":
                progress.control.request("stop")

        progress.control.on_event = record
        progress.control.request("pause")
        progress.update()
        self.assertEqual([event[1] for event in progress.events], ["pause", "stop"])
        self.assertTrue(progress.stopped)

    def test_mark_format_coordinates_validation_and_snapshot_copy(self):
        progress = Progress(total=10, initial=3)
        progress.update(2)
        progress.set_postfix(loss=0.5)
        progress.mark(" phase 2 ")
        elapsed, kind, step, update, label = progress.events[0]
        self.assertGreaterEqual(elapsed, 0)
        self.assertEqual((kind, step, update, label), ("mark", 5, 1, "phase 2"))
        snapshot = progress.snapshot()
        self.assertEqual(snapshot["events"], progress.events)
        snapshot["events"].clear()
        self.assertEqual(len(progress.events), 1)
        for invalid in ("", "  ", None, 42, "x" * 101):
            with self.assertRaises(ValueError):
                progress.mark(invalid)
        progress.mark("x" * 100)
        self.assertEqual(progress.snapshot()["history_updates"], 1)

    def test_nested_mark_is_recorded_on_the_outer_bar(self):
        outer = Qtqdm(range(1), open_browser=False, capture_console=False)
        try:
            for _ in outer:
                inner = Qtqdm(range(2), open_browser=False, capture_console=False)
                try:
                    for _ in inner:
                        inner.set_postfix(loss=0.5)
                        inner.mark("batch done")
                    self.assertEqual(inner.events, [])
                finally:
                    inner.close()
            self.assertEqual([event[2:] for event in outer.events],
                             [[1, 1, "batch done"], [1, 2, "batch done"]])
        finally:
            outer.close()

    def test_saved_record_preserves_events_after_reopening(self):
        progress = Progress(total=2)
        progress.update()
        progress.mark("phase 2")
        with TemporaryDirectory() as folder:
            path = Path(folder) / "records.sqlite3"
            store = RunRecords(path)
            try:
                record_id = store.start({}, Path(folder) / "console.log")
                store.training(record_id, progress.snapshot())
            finally:
                store.close()
            store = RunRecords(path)
            try:
                self.assertEqual(store.get(record_id)["training"]["data"]["events"], progress.events)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
