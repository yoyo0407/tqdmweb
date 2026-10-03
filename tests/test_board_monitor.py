import os
import subprocess
from time import monotonic
from unittest.mock import patch
import unittest

from qtqdm.board_monitor import ResourceMonitor, parse_gpus, windows_resources


class ResourceMonitorTests(unittest.TestCase):
    def test_gpu_multiple_devices_and_unavailable_values(self):
        devices = parse_gpus("0, NVIDIA GeForce RTX 5060, 71, 1024, 8151\n1, Other GPU, [N/A], [N/A], 16384\n")
        self.assertEqual(devices[0]["utilization_percent"], 71)
        self.assertEqual(devices[0]["memory_used_mib"], 1024)
        self.assertIsNone(devices[1]["utilization_percent"])
        with self.assertRaises(ValueError):
            parse_gpus("unexpected")

    def test_gpu_timeout_keeps_cpu_ram_and_clears_previous_gpu(self):
        monitor = ResourceMonitor()
        monitor._nvidia = "nvidia-smi"
        monitor._sample["gpus"] = [{"name": "old"}]
        with patch("qtqdm.board_monitor.windows_resources", return_value=({"cpu_percent": 35,
                  "ram_used_bytes": 100, "ram_total_bytes": 200}, (1, 2))), \
             patch("qtqdm.board_monitor.subprocess.run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 1.2)):
            monitor._sample_once()
        data = monitor.snapshot()
        self.assertEqual(data["cpu_percent"], 35)
        self.assertEqual(data["ram_used_bytes"], 100)
        self.assertEqual(data["gpus"], [])
        self.assertIn("GPU unavailable", data["errors"][0])

    @unittest.skipUnless(os.name == "nt", "Windows API")
    def test_actual_windows_memory_and_cpu_counters(self):
        data, previous = windows_resources()
        second, current = windows_resources(previous)
        self.assertGreater(data["ram_total_bytes"], 0)
        self.assertLessEqual(data["ram_used_bytes"], data["ram_total_bytes"])
        self.assertGreaterEqual(current[1], previous[1])
        if second["cpu_percent"] is not None:
            self.assertTrue(0 <= second["cpu_percent"] <= 100)

    def test_snapshot_is_responsive_while_sample_is_busy_and_close_joins(self):
        from threading import Event
        entered, release = Event(), Event()
        monitor = ResourceMonitor()
        def slow_sample():
            entered.set()
            release.wait(timeout=2)
        with patch.object(monitor, "_sample_once", side_effect=slow_sample):
            monitor.start()
            try:
                self.assertTrue(entered.wait(timeout=2))
                started = monotonic()
                monitor.snapshot()
                self.assertLess(monotonic() - started, 0.1)
            finally:
                release.set()
                monitor.close()
        self.assertFalse(monitor._thread.is_alive())
