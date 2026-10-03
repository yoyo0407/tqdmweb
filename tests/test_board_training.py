import json
from threading import Event
from time import monotonic, sleep
import unittest
from unittest.mock import patch

from qtqdm.board_training import TrainingBridge
from qtqdm.dashboard import Dashboard


def wait_until(predicate):
    deadline = monotonic() + 4
    while not predicate():
        if monotonic() > deadline:
            raise AssertionError("Training relay timed out")
        sleep(0.02)


class Runner:
    def __init__(self, url):
        self.state = {"job_id": 1, "running": True, "dashboard_url": url}

    def snapshot(self):
        return self.state.copy()


class TrainingBridgeTests(unittest.TestCase):
    def setUp(self):
        self.commands = []
        self.data = {"completed": 7, "console": {"text": "duplicate"}}
        def control(action, value):
            self.commands.append((action, value))
            if action == "invalid":
                raise ValueError("Unknown control")
            return action != "finished"
        self.dashboard = Dashboard(lambda: self.data.copy(), control)
        self.dashboard.start()
        self.addCleanup(self.dashboard.close)
        self.runner = Runner(self.dashboard.url)
        self.bridge = TrainingBridge(self.runner)
        self.addCleanup(self.bridge.close)

    def snapshot(self):
        return self.bridge.snapshot(self.runner.snapshot())

    def test_cached_state_disconnection_and_new_job(self):
        self.bridge.start()
        wait_until(lambda: self.snapshot()["connected"])
        self.assertEqual(self.snapshot()["data"], {"completed": 7})
        self.dashboard.close()
        wait_until(lambda: self.snapshot()["error"] is not None)
        self.assertFalse(self.snapshot()["connected"])
        self.assertEqual(self.snapshot()["data"]["completed"], 7)
        self.runner.state["running"] = False
        self.assertEqual(self.snapshot()["data"]["completed"], 7)
        self.runner.state["job_id"] = 2
        self.assertIsNone(self.snapshot()["data"])

    def test_controls_and_child_errors_are_forwarded(self):
        result, status = self.bridge.control({"job_id": 1, "action": "learning_rate", "value": 0.03})
        self.assertEqual(status, 200)
        self.assertTrue(result["accepted"])
        self.assertEqual(self.commands, [("learning_rate", 0.03)])
        self.assertEqual(self.bridge.control({"job_id": 1, "action": "invalid"})[1], 400)
        self.assertEqual(self.bridge.control({"job_id": 1, "action": "finished"})[1], 409)
        for command in [{"job_id": 0, "action": "stop"}, {"action": "stop"}]:
            with self.assertRaises(ValueError):
                self.bridge.control(command)
        self.runner.state["running"] = False
        with self.assertRaises(ValueError):
            self.bridge.control({"job_id": 1, "action": "stop"})

    def test_slow_old_response_does_not_block_state_or_enter_new_job(self):
        entered, release = Event(), Event()
        class Response:
            def __enter__(self):
                entered.set()
                release.wait(2)
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                return json.dumps({"completed": 999}).encode()
        with patch("qtqdm.board_training.urlopen", return_value=Response()):
            self.bridge.start()
            self.assertTrue(entered.wait(2))
            start = monotonic()
            self.assertIsNone(self.snapshot()["data"])
            self.assertLess(monotonic() - start, 0.1)
            self.runner.state.update(job_id=2, running=False, dashboard_url=None)
            release.set()
            wait_until(lambda: self.bridge._job_id == 2)
            self.assertIsNone(self.snapshot()["data"])


if __name__ == "__main__":
    unittest.main()
