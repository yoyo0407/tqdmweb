"""Sample system resources off the HTTP thread, without Python dependencies."""

import ctypes
import os
from pathlib import Path
import shutil
import subprocess
from threading import Event, Lock, Thread
from time import monotonic, time


class MemoryStatus(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
        (name, ctypes.c_uint64) for name in
        ("total", "available", "page_total", "page_available", "virtual_total", "virtual_available", "extended")]


def windows_resources(previous=None):
    if os.name != "nt":
        raise OSError("CPU / RAM sampling currently supports Windows")
    idle, kernel, user = ctypes.c_uint64(), ctypes.c_uint64(), ctypes.c_uint64()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        raise OSError("GetSystemTimes failed")
    current = (idle.value, kernel.value + user.value)
    cpu = None
    if previous is not None:
        elapsed = current[1] - previous[1]
        if elapsed > 0:
            cpu = max(0, min(100, 100 * (1 - (current[0] - previous[0]) / elapsed)))
    memory = MemoryStatus()
    memory.length = ctypes.sizeof(memory)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        raise OSError("GlobalMemoryStatusEx failed")
    return {"cpu_percent": cpu, "ram_used_bytes": memory.total - memory.available,
            "ram_total_bytes": memory.total}, current


def parse_gpus(text):
    devices = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 5:
            raise ValueError("Unexpected nvidia-smi output")
        index, name, utilization, used, total = parts
        def number(value):
            try:
                return float(value)
            except ValueError:
                return None  # Drivers can report [N/A].
        devices.append({"index": int(index), "name": name, "utilization_percent": number(utilization),
                        "memory_used_mib": number(used), "memory_total_mib": number(total)})
    return devices


class ResourceMonitor:
    def __init__(self):
        self._lock = Lock()
        self._stop = Event()
        self._thread = None
        self._previous_cpu = None
        self._sample = {"sampled_at": None, "cpu_percent": None, "ram_used_bytes": None,
                        "ram_total_bytes": None, "gpus": [], "errors": []}
        fallback = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/nvidia-smi.exe"
        self._nvidia = shutil.which("nvidia-smi") or (str(fallback) if fallback.is_file() else None)

    def start(self):
        if self._thread is None:
            self._thread = Thread(target=self._run, daemon=True)
            self._thread.start()

    def _sample_once(self):
        sampled_at = time()
        sample = {"cpu_percent": None, "ram_used_bytes": None, "ram_total_bytes": None,
                  "gpus": [], "errors": []}
        try:
            resources, self._previous_cpu = windows_resources(self._previous_cpu)
            sample.update(resources)
        except OSError as error:
            sample["errors"].append(str(error))
        if self._nvidia is None:
            sample["errors"].append("GPU unavailable: nvidia-smi not found")
        else:
            try:
                result = subprocess.run([self._nvidia, "--query-gpu=index,name,utilization.gpu,memory.used,memory.total",
                                         "--format=csv,noheader,nounits"], capture_output=True, text=True,
                                        timeout=1.2, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                if result.returncode:
                    raise OSError(result.stderr.strip() or "nvidia-smi failed")
                sample["gpus"] = parse_gpus(result.stdout)
            except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                sample["errors"].append(f"GPU unavailable: {error}")
        sample["sampled_at"] = sampled_at
        with self._lock:
            self._sample = sample

    def _run(self):
        while not self._stop.is_set():
            started = monotonic()
            self._sample_once()
            self._stop.wait(max(0.05, 1 - (monotonic() - started)))

    def snapshot(self):
        with self._lock:
            return dict(self._sample)

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
