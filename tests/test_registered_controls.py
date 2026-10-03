from threading import Event, Thread, get_ident
import unittest

from qtqdm import Qtqdm, tqdm
from qtqdm.progress import Progress
from test_control import wait_until


class RegisteredControlTests(unittest.TestCase):
    def test_callbacks_run_at_boundary_on_training_thread_and_save_once(self):
        progress = Progress(range(3))
        applied, saves = [], []
        training_thread = get_ident()
        progress.register_controls(
            set_learning_rate=lambda value: applied.append((value, progress.completed, get_ident())),
            learning_rate=0.1,
            save_checkpoint=lambda: saves.append((progress.completed, get_ident())) or "test.pt",
        )
        progress.control.request("schedule_save", 2)
        for step in progress:
            if step == 0:
                progress.control.request("learning_rate", 0.03)
                self.assertEqual(applied, [])
        self.assertEqual(applied, [(0.03, 1, training_thread)])
        self.assertEqual(saves, [(2, training_thread)])
        self.assertEqual(progress.control.snapshot()["learning_rate"], 0.03)

    def test_callback_failure_is_reported_and_can_be_retried(self):
        progress = Progress(range(3))
        def set_rate(value):
            if value == 0.02:
                raise ValueError("optimizer rejected value")
        progress.register_controls(set_learning_rate=set_rate, learning_rate=0.1)
        progress.control.request("learning_rate", 0.02)
        for step in progress:
            if step == 0:
                state = progress.control.snapshot()
                self.assertEqual(state["learning_rate"], 0.1)
                self.assertIn("optimizer rejected", state["learning_rate_error"])
                progress.control.request("learning_rate", 0.03)
        state = progress.control.snapshot()
        self.assertEqual(state["learning_rate"], 0.03)
        self.assertIsNone(state["learning_rate_error"])

    def test_registered_rate_works_while_paused_without_resuming(self):
        progress = Progress(range(1))
        applied = Event()
        progress.register_controls(set_learning_rate=lambda value: applied.set(), learning_rate=0.1)
        progress.control.request("pause")
        worker = Thread(target=lambda: list(progress), daemon=True)
        worker.start()
        try:
            wait_until(lambda: progress.control.snapshot()["paused"])
            progress.control.request("learning_rate", 0.02)
            self.assertTrue(applied.wait(timeout=3))
            wait_until(lambda: progress.control.snapshot()["learning_rate"] == 0.02)
            self.assertTrue(progress.control.snapshot()["paused"])
            self.assertEqual(progress.completed, 0)
            progress.control.request("stop")
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive())
        finally:
            progress.control.finish()
            worker.join(timeout=3)

    def test_slow_rate_handler_does_not_hold_control_lock(self):
        progress = Progress(range(1))
        entered, release = Event(), Event()
        def set_rate(value):
            entered.set()
            release.wait(timeout=3)
        progress.register_controls(set_learning_rate=set_rate, learning_rate=0.1)
        progress.control.request("learning_rate", 0.02)
        worker = Thread(target=lambda: list(progress), daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(timeout=3))
            self.assertTrue(progress.control.request("stop"))
            release.set()
            worker.join(timeout=3)
            self.assertEqual(progress.completed, 0)
        finally:
            release.set()
            progress.control.finish()
            worker.join(timeout=3)

    def test_registration_validates_before_enabling_any_capability(self):
        progress = Progress([])
        for invalid in (None, 0, -1, True, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                progress.register_controls(save_checkpoint=lambda: "file.pt",
                                           set_learning_rate=lambda value: None, learning_rate=invalid)
            self.assertFalse(progress.control.snapshot()["capabilities"]["save_checkpoint"])
        with self.assertRaises(TypeError):
            progress.register_controls(save_checkpoint="file.pt")
        list(progress)
        with self.assertRaises(RuntimeError):
            progress.register_controls(save_checkpoint=lambda: "file.pt")

    def test_simple_tqdm_import_desc_and_mapping_postfix(self):
        self.assertIs(tqdm, Qtqdm)
        with tqdm(range(2), desc="Simple API", open_browser=False) as progress:
            try:
                for step in progress:
                    progress.set_postfix({"loss": 1 / (step + 1)}, refresh=False, accuracy=0.9)
                state = progress.snapshot()
                self.assertEqual(state["description"], "Simple API")
                self.assertEqual(state["completed"], 2)
                self.assertEqual(state["metrics"]["loss"], "0.5")
                self.assertFalse(state["control"]["capabilities"]["save_checkpoint"])
            finally:
                progress.close()
