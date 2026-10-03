import json
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from qtqdm import Qtqdm, tqdm, trange
from qtqdm.progress import Progress


def quiet(*args, **kwargs):
    return Qtqdm(*args, open_browser=False, capture_console=False, **kwargs)


class ManualUpdateTests(unittest.TestCase):
    def test_update_counts_and_finishes(self):
        progress = Progress(total=10)
        self.assertTrue(progress.manual)
        progress.update(4)
        self.assertEqual((progress.n, progress.started, progress.state), (4, 4, "running"))
        progress.update(6)
        progress._finalize_manual()
        self.assertEqual((progress.n, progress.state), (10, "finished"))
        self.assertTrue(progress.snapshot()["control"]["finished"])

    def test_update_validation_and_iteration_rules(self):
        with self.assertRaises(TypeError):
            iter(Progress(total=3)).__next__()
        with self.assertRaises(RuntimeError):
            Progress(range(3)).update()
        for invalid in (-1, 1.5, True):
            with self.assertRaises(ValueError):
                Progress(total=3).update(invalid)

    def test_close_before_total_is_stopped(self):
        progress = Progress(total=10)
        progress.update(3)
        progress._finalize_manual()
        self.assertEqual(progress.state, "stopped")
        unknown = Progress()
        unknown.update(5)
        unknown._finalize_manual()
        self.assertEqual(unknown.state, "finished")

    def test_stop_request_reaches_manual_loop(self):
        progress = Progress(total=100)
        progress.update()
        progress.control.request("stop")
        progress.update()
        self.assertTrue(progress.stopped)
        self.assertEqual(progress.state, "stopped")
        progress._finalize_manual()
        self.assertEqual(progress.state, "stopped")

    def test_pause_blocks_update_until_resume(self):
        progress = Progress(total=5)
        progress.control.request("pause")
        done = threading.Event()
        worker = threading.Thread(target=lambda: (progress.update(), done.set()))
        worker.start()
        self.assertFalse(done.wait(0.2))
        self.assertTrue(progress.control.snapshot()["paused"])
        progress.control.request("resume")
        self.assertTrue(done.wait(2))
        worker.join()

    def test_qtqdm_manual_with_block_and_server(self):
        with quiet(total=3, desc="manual", unit="batch") as progress:
            for _ in range(3):
                progress.update()
            state = json.load(urlopen(progress.url + "state"))
            self.assertEqual((state["started"], state["unit"]), (3, "batch"))
        self.assertEqual(progress.state, "finished")
        progress.close()

    def test_set_description(self):
        progress = Progress(total=1)
        progress.set_description("epoch 2")
        self.assertEqual(progress.description, "epoch 2")


class TqdmArgumentTests(unittest.TestCase):
    def test_trange_and_alias(self):
        progress = trange(2, 5, open_browser=False, capture_console=False)
        try:
            self.assertEqual(list(progress), [2, 3, 4])
            self.assertIs(tqdm, Qtqdm)
        finally:
            progress.close()

    def test_display_options_are_accepted_and_unknown_rejected(self):
        progress = quiet(range(2), ncols=80, leave=False, mininterval=0.5, position=0,
                         dynamic_ncols=True, bar_format="{l_bar}", postfix={"loss": 1.5})
        try:
            self.assertEqual(progress.metrics, {"loss": "1.5"})
        finally:
            progress.close()
        with self.assertRaises(TypeError):
            quiet(range(2), not_a_tqdm_option=1)

    def test_disable_runs_without_page(self):
        progress = Qtqdm(range(3), disable=True)
        self.assertEqual(list(progress), [0, 1, 2])
        self.assertIsNone(progress.server)
        self.assertIsNone(progress.show())
        progress.close()


class NestedBarTests(unittest.TestCase):
    def test_inner_bars_report_on_outer_page(self):
        outer = quiet(range(2), desc="epochs")
        try:
            snapshots = []
            for _ in outer:
                inner = Qtqdm(range(3), desc="batches", leave=True)
                self.assertTrue(inner.is_child)
                self.assertIsNone(inner.server)
                for step in inner:
                    inner.set_postfix(loss=1 / (step + 1))
                    snapshots.append(json.load(urlopen(outer.url + "state")))
            bars = snapshots[-1]["bars"]
            self.assertEqual(len(bars), 1)
            self.assertEqual((bars[0]["description"], bars[0]["depth"], bars[0]["started"]), ("batches", 1, 3))
            # Inner metrics land on the outer chart history.
            self.assertEqual(len(outer.history_since()["charts"]["loss"]), 6)
            final = outer.snapshot()["bars"]
            self.assertEqual([bar["state"] for bar in final], ["finished"])
        finally:
            outer.close()

    def test_leave_false_removes_finished_inner_bar(self):
        outer = quiet(range(1))
        try:
            for _ in outer:
                for _ in Qtqdm(range(2), leave=False):
                    self.assertEqual(len(outer.snapshot()["bars"]), 1)
                self.assertEqual(outer.snapshot()["bars"], [])
        finally:
            outer.close()

    def test_unused_bar_does_not_capture_later_bars(self):
        unused = quiet(range(3))
        later = quiet(range(1))
        try:
            self.assertFalse(later.is_child)
            self.assertEqual(list(later), [0])
        finally:
            unused.close()
            later.close()

    def test_closing_an_unused_manual_bar_does_not_capture_later_bars(self):
        first = quiet(total=3)
        first.close()
        later = quiet(range(1))
        try:
            self.assertFalse(later.is_child)
            self.assertEqual(list(later), [0])
        finally:
            first.close()
            later.close()

    def test_sequential_bars_are_independent(self):
        first = quiet(range(1))
        list(first)
        second = quiet(range(1))
        try:
            self.assertFalse(second.is_child)
        finally:
            first.close()
            second.close()

    def test_stop_from_outer_page_ends_inner_loop(self):
        outer = quiet(range(5))
        try:
            seen = []
            for epoch in outer:
                inner = Qtqdm(range(100))
                for step in inner:
                    seen.append((epoch, step))
                    if step == 2:
                        request = Request(outer.url + "control", data=b'{"action": "stop"}',
                                          headers={"Content-Type": "application/json"})
                        urlopen(request)
                self.assertEqual(inner.state, "stopped")
            self.assertEqual(seen, [(0, 0), (0, 1), (0, 2)])
            self.assertEqual(outer.state, "stopped")
        finally:
            outer.close()

    def test_controls_belong_to_outer_bar(self):
        outer = quiet(range(1))
        try:
            for _ in outer:
                inner = Qtqdm(total=2)
                with self.assertRaises(RuntimeError):
                    inner.register_controls(save_checkpoint=lambda: "x")
                inner.update(2)
                inner.close()
                self.assertEqual(inner.state, "finished")
        finally:
            outer.close()

    def test_manual_inner_under_manual_outer(self):
        with quiet(total=2, desc="outer") as outer:
            for _ in range(2):
                with Qtqdm(total=4, desc="inner") as inner:
                    self.assertTrue(inner.is_child)
                    inner.update(4)
                outer.update()
        self.assertEqual(outer.state, "finished")
        self.assertEqual(outer.snapshot()["bars"][0]["state"], "finished")
        outer.close()


if __name__ == "__main__":
    unittest.main()
