import json
from time import monotonic, sleep
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from qtqdm.board_training import TrainingBridge
from qtqdm.dashboard import Dashboard
from qtqdm.progress import Progress


class Runner:
    def __init__(self, url):
        self.data = {"job_id": 1, "running": True, "dashboard_url": url}

    def snapshot(self):
        return self.data.copy()


def wait_until(predicate):
    deadline = monotonic() + 6
    while not predicate():
        if monotonic() > deadline:
            raise AssertionError("Full history timed out")
        sleep(0.02)


class FullHistoryTests(unittest.TestCase):
    def test_twenty_thousand_updates_recover_from_cursor_zero_without_gaps(self):
        progress = Progress(range(20000))
        for step in progress:
            progress.set_postfix(score=step, note="text")
            if step % 7 == 0:
                progress.set_postfix(loss=0.1, score=float("nan"))
        charts = {}
        cursor = 0
        while True:
            page = progress.history_since(cursor)
            self.assertLessEqual(page["next_update"] - cursor, 2000)
            for name, points in page["charts"].items():
                charts.setdefault(name, []).extend(points)
            cursor = page["next_update"]
            if not page["has_more"]:
                break
        self.assertEqual([point[1] for point in charts["score"]], list(range(20000)))
        self.assertEqual(len(charts["loss"]), len(range(0, 20000, 7)))
        self.assertNotIn("note", charts)
        self.assertEqual(progress.history_since(cursor)["charts"], {})
        progress.set_postfix(score=20000)
        self.assertEqual(progress.history_since(cursor)["charts"]["score"][0][1], 20000)
        self.assertEqual(progress.history_since(0)["charts"]["score"][0][1], 0)
        for after, limit in [(-1, 2000), (cursor + 100, 2000), (0, 2001), (True, 2000)]:
            with self.assertRaises(ValueError):
                progress.history_since(after, limit)

    def test_http_and_board_cache_keep_early_points_after_updates_and_exit(self):
        progress = Progress([])
        for i in range(3000):
            progress.set_postfix(score=i)
        dashboard = Dashboard(progress.snapshot, progress.control.request, progress.history_since)
        dashboard.start()
        self.addCleanup(dashboard.close)
        with urlopen(dashboard.url + "history?after=0", timeout=3) as response:
            first = json.load(response)
        self.assertEqual(first["charts"]["score"][0][1], 0)
        self.assertTrue(first["has_more"])
        with self.assertRaises(HTTPError) as error:
            urlopen(dashboard.url + "history?after=-1", timeout=3)
        self.assertEqual(error.exception.code, 400)
        runner = Runner(dashboard.url)
        bridge = TrainingBridge(runner)
        self.addCleanup(bridge.close)
        bridge.start()
        wait_until(lambda: bridge._history_cursor == 3000)
        for i in range(3000, 3500):
            progress.set_postfix(score=i)
        wait_until(lambda: bridge._history_cursor == 3500)
        runner.data["running"] = False
        dashboard.close()
        # A refreshed page starts at zero, even after the child server is gone.
        page = bridge.history_since(1, 0)
        self.assertEqual(page["charts"]["score"][0][1], 0)
        tail = bridge.history_since(1, page["next_update"])
        self.assertEqual(tail["charts"]["score"][-1][1], 3499)
        runner.data["job_id"] = 2
        with self.assertRaises(ValueError):
            bridge.history_since(1, 0)


if __name__ == "__main__":
    unittest.main()
