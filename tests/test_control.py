import json
from threading import Event, Thread, get_ident
from time import monotonic, sleep
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from qtqdm import Qtqdm
from qtqdm.control import TrainingControl
from qtqdm.progress import Progress


def wait_until(predicate):
    deadline = monotonic() + 3
    while not predicate():
        if monotonic() >= deadline:
            raise AssertionError("Timed out waiting for training state")
        sleep(0.01)


class ControlTests(unittest.TestCase):
    def test_save_runs_on_paused_training_thread(self):
        control = TrainingControl()
        calls = []

        def save():
            calls.append(get_ident())
            return "paused.pt"

        control.register_controls(save_checkpoint=save)
        control.request("pause")
        worker = Thread(target=control.checkpoint, daemon=True)
        worker.start()
        try:
            wait_until(lambda: control.snapshot()["paused"])
            control.request("save")
            wait_until(lambda: control.snapshot()["last_checkpoint"] == "paused.pt")
            self.assertEqual(calls, [worker.ident])
            self.assertTrue(worker.is_alive())
            self.assertTrue(control.snapshot()["paused"])
        finally:
            control.finish()
            worker.join(timeout=3)

    def test_slow_save_keeps_control_responsive(self):
        control = TrainingControl()
        entered, release = Event(), Event()

        def save():
            entered.set()
            release.wait(timeout=3)
            return "slow.pt"

        control.register_controls(save_checkpoint=save)
        control.request("save")
        results = []
        worker = Thread(target=lambda: results.append(control.checkpoint()), daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(timeout=3))
            self.assertTrue(control.snapshot()["saving"])
            self.assertFalse(control.request("save"))
            self.assertTrue(control.request("stop"))
            release.set()
            worker.join(timeout=3)
            self.assertEqual(results, [False])
        finally:
            release.set()
            control.finish()
            worker.join(timeout=3)

    def test_save_failure_can_be_retried(self):
        control = TrainingControl()

        def fail():
            raise OSError("disk full")

        control.register_controls(save_checkpoint=fail)
        control.request("save")
        self.assertTrue(control.checkpoint())
        self.assertEqual(control.snapshot()["save_error"], "OSError: disk full")
        control.register_controls(save_checkpoint=lambda: "retry.pt")
        control.request("save")
        self.assertTrue(control.checkpoint())
        self.assertIsNone(control.snapshot()["save_error"])
        self.assertEqual(control.snapshot()["last_checkpoint"], "retry.pt")

    def test_schedule_saves_at_target_once_including_last_step(self):
        for scheduled in (2, 3):
            with self.subTest(step=scheduled):
                progress = Progress(range(3))
                calls = []

                def save():
                    calls.append(progress.completed)
                    return "scheduled.pt"

                progress.register_controls(save_checkpoint=save)
                progress.control.request("schedule_save", scheduled)
                list(progress)
                self.assertEqual(calls, [scheduled])
                self.assertIsNone(progress.control.snapshot()["save_at_step"])

    def test_schedule_validation_and_cancel(self):
        progress = Progress(range(3))
        with self.assertRaises(ValueError):
            progress.control.request("schedule_save", 2)
        calls = []
        progress.register_controls(save_checkpoint=lambda: calls.append(progress.completed) or "test.pt")
        for invalid in (0, -1, 4, True, 1.5):
            with self.assertRaises(ValueError):
                progress.control.request("schedule_save", invalid)
        progress.control.request("schedule_save", 2)
        progress.control.request("cancel_save")
        list(progress)
        self.assertEqual(calls, [])

    def test_last_step_manual_save_is_not_lost(self):
        progress = Progress(range(3))
        calls = []
        progress.register_controls(save_checkpoint=lambda: calls.append(progress.completed) or "final.pt")
        for item in progress:
            if item == 2:
                progress.control.request("save")
        self.assertEqual(calls, [3])

    def test_rate_application_precedes_saving_at_same_boundary(self):
        progress = Progress(range(3))
        calls = []
        rates = [0.1]
        progress.register_controls(save_checkpoint=lambda: calls.append((progress.completed, rates[-1])) or "test.pt",
                                   set_learning_rate=rates.append, learning_rate=0.1)
        progress.control.request("schedule_save", 2)
        for item in progress:
            if item == 0:
                progress.control.request("save")
                progress.control.request("learning_rate", 0.02)
        self.assertEqual(calls, [(1, 0.02), (2, 0.02)])

    def test_finish_clears_future_save(self):
        control = TrainingControl()
        control.register_controls(save_checkpoint=lambda: "test.pt")
        control.request("schedule_save", 10)
        control.request("save")
        control.finish()
        self.assertIsNone(control.snapshot()["save_at_step"])
        self.assertFalse(control.snapshot()["save_requested"])

    def test_pause_resume_and_stop_while_paused(self):
        for action, expected in (("resume", True), ("stop", False)):
            with self.subTest(action=action):
                control = TrainingControl()
                control.request("pause")
                result = []
                worker = Thread(target=lambda: result.append(control.checkpoint()), daemon=True)
                worker.start()
                try:
                    wait_until(lambda: control.snapshot()["paused"])
                    self.assertEqual(result, [])
                    control.request(action)
                    worker.join(timeout=3)
                    self.assertEqual(result, [expected])
                finally:
                    control.finish()
                    worker.join(timeout=3)

    def test_rate_is_validated_and_applied_by_training(self):
        control = TrainingControl()
        with self.assertRaises(ValueError):
            control.request("learning_rate", 0.01)
        rates = []
        control.register_controls(set_learning_rate=rates.append, learning_rate=0.1)
        for invalid in (0, -1, True, None, "bad", float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                control.request("learning_rate", invalid)
        control.request("learning_rate", 0.02)
        self.assertEqual(control.snapshot()["learning_rate"], 0.1)
        control.checkpoint()
        self.assertEqual(rates, [0.02])
        self.assertIsNone(control.snapshot()["pending_learning_rate"])
        self.assertEqual(control.snapshot()["learning_rate"], 0.02)
        control.finish()
        self.assertFalse(control.request("pause"))


class ControlHttpTests(unittest.TestCase):
    def setUp(self):
        self.progress = Qtqdm(range(3), open_browser=False)
        self.progress._start_server()
        self.addCleanup(self.progress.close)

    def post(self, action, value=None, origin=None):
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        request = Request(self.progress.url + "control",
                          data=json.dumps({"action": action, "value": value}).encode(),
                          headers=headers)
        with urlopen(request, timeout=3) as response:
            return json.load(response)

    def test_pause_rate_resume_through_http(self):
        rates = []
        self.progress.register_controls(set_learning_rate=rates.append, learning_rate=0.1)
        self.post("pause")

        def train():
            with self.progress:
                for item in self.progress:
                    pass

        worker = Thread(target=train, daemon=True)
        worker.start()
        try:
            wait_until(lambda: self.progress.snapshot()["state"] == "paused")
            self.assertEqual(self.progress.started, 0)
            self.post("learning_rate", 0.02)
            wait_until(lambda: self.progress.control.snapshot()["learning_rate"] == 0.02)
            self.assertEqual(self.progress.started, 0)
            self.post("resume")
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(rates, [0.02])
            self.assertEqual(self.progress.completed, 3)
            with self.assertRaises(HTTPError) as error:
                self.post("stop")
            self.assertEqual(error.exception.code, 409)
        finally:
            self.progress.control.finish()
            worker.join(timeout=3)

    def test_stop_wakes_paused_loop(self):
        self.post("pause")
        worker = Thread(target=lambda: list(self.progress), daemon=True)
        worker.start()
        try:
            wait_until(lambda: self.progress.snapshot()["state"] == "paused")
            self.post("stop")
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(self.progress.state, "stopped")
            self.assertEqual(self.progress.completed, 0)
        finally:
            self.progress.control.finish()
            worker.join(timeout=3)

    def test_stop_finishes_current_step_before_ending_loop(self):
        entered = Event()
        release = Event()

        def train():
            with self.progress:
                for item in self.progress:
                    entered.set()
                    release.wait(timeout=3)

        worker = Thread(target=train, daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(timeout=3))
            self.post("stop")
            self.assertEqual(self.progress.snapshot()["state"], "stop_requested")
            self.assertEqual((self.progress.started, self.progress.completed), (1, 0))
            release.set()
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(self.progress.state, "stopped")
            self.assertEqual(self.progress.completed, 1)
        finally:
            release.set()
            self.progress.control.finish()
            worker.join(timeout=3)

    def test_bad_commands_are_rejected(self):
        for action, value in (("unknown", None), ("restart", {}), ("learning_rate", -1)):
            with self.assertRaises(HTTPError) as error:
                self.post(action, value)
            self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError) as error:
            self.post("pause", origin="https://example.com")
        self.assertEqual(error.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
