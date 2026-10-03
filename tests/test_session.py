from threading import Event, Thread
from time import monotonic, sleep
import unittest
from unittest.mock import patch

from qtqdm.session import TrainingSession
from training_config import DEFAULT_PARAMETERS, validate_parameters


def wait_until(predicate):
    deadline = monotonic() + 4
    while not predicate():
        if monotonic() >= deadline:
            raise AssertionError("Timed out waiting for session")
        sleep(0.01)


class SessionTests(unittest.TestCase):
    def start_worker(self, session, train):
        patcher = patch.object(session, "_listen_for_close", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        worker = Thread(target=lambda: session.run(train, open_browser=False, keep_open=True), daemon=True)
        worker.start()

        def cleanup():
            session.request_close()
            worker.join(timeout=4)
            self.assertFalse(worker.is_alive())
        self.addCleanup(cleanup)
        return worker

    def test_restart_waits_for_boundary_and_uses_new_progress(self):
        session = TrainingSession(DEFAULT_PARAMETERS, validate_parameters)
        entered, release = Event(), Event()
        runs = []

        def train(current, parameters):
            progress = current.new_progress(range(parameters["target_steps"]), total=parameters["target_steps"])
            runs.append(progress)
            with progress:
                for step in progress:
                    progress.set_postfix(loss=step + 1)
                    if current.run_id == 1 and step == 0:
                        entered.set()
                        release.wait(timeout=4)

        self.start_worker(session, train)
        self.assertTrue(entered.wait(timeout=4))
        original_url = session.dashboard.url
        try:
            self.assertTrue(session.request("restart", {"target_steps": 3, "momentum": 0.5}))
            self.assertFalse(session.request("restart", {"target_steps": 4}))
            self.assertEqual(session.snapshot()["state"], "restart_requested")
            self.assertEqual(runs[0].completed, 0)
        finally:
            release.set()
        wait_until(lambda: session.run_id == 2 and session.current.state == "finished")
        self.assertEqual(session.dashboard.url, original_url)
        self.assertEqual((runs[0].completed, runs[0].state), (1, "stopped"))
        self.assertEqual((runs[1].initial, runs[1].completed), (0, 3))
        self.assertEqual(session.parameters["momentum"], 0.5)
        self.assertEqual(runs[1].snapshot()["charts"]["loss"]["recent"][0][2:], [1, 1])
        self.assertFalse(runs[1].control.snapshot()["pause_requested"])

    def test_restart_after_failure_and_completion(self):
        session = TrainingSession(DEFAULT_PARAMETERS, validate_parameters)

        def train(current, parameters):
            progress = current.new_progress(range(1), total=1)
            with progress:
                if current.run_id == 1:
                    raise ValueError("example training failure")
                list(progress)

        self.start_worker(session, train)
        wait_until(lambda: session.current.state == "failed")
        self.assertTrue(session.request("restart", {}))
        wait_until(lambda: session.run_id == 2 and session.current.state == "finished")
        self.assertTrue(session.request("restart", {}))
        wait_until(lambda: session.run_id == 3 and session.current.state == "finished")
        self.assertIsNone(session.current.error)

    def test_restart_wakes_paused_run(self):
        session = TrainingSession(DEFAULT_PARAMETERS, validate_parameters)

        def train(current, parameters):
            progress = current.new_progress(range(2), total=2)
            if current.run_id == 1:
                progress.control.request("pause")
            with progress:
                list(progress)

        self.start_worker(session, train)
        wait_until(lambda: session.current.control.snapshot()["paused"])
        self.assertTrue(session.request("restart", {"learning_rate": 0.02}))
        wait_until(lambda: session.run_id == 2 and session.current.state == "finished")
        self.assertEqual(session.parameters["learning_rate"], 0.02)

    def test_hyperparameter_validation(self):
        for override in ({"learning_rate": 0}, {"learning_rate": True}, {"learning_rate": float("inf")},
                         {"momentum": 1}, {"momentum": -1}, {"weight_decay": -1},
                         {"target_steps": 0}, {"target_steps": 1.5}, {"unknown": 1}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                validate_parameters({**DEFAULT_PARAMETERS, **override})
        self.assertEqual(validate_parameters(DEFAULT_PARAMETERS), DEFAULT_PARAMETERS)


if __name__ == "__main__":
    unittest.main()
