"""Write every metric update to disk without retaining it in memory."""

import csv
from pathlib import Path


class CsvLog:
    def __init__(self, path):
        # Exclusive creation protects previous training results from overwriting.
        self.file = Path(path).open("x", newline="", encoding="utf-8-sig")
        self.writer = csv.writer(self.file)
        self.writer.writerow(["update", "elapsed_seconds", "item", "metric", "value"])
        self.file.flush()
        self.update = 0

    def write(self, elapsed, item, values):
        if self.file.closed:
            raise RuntimeError("The CSV log is closed; create a new progress object")
        self.update += 1
        for name, value in values.items():
            self.writer.writerow([self.update, elapsed, item, name, value])
        self.file.flush()

    def close(self):
        self.file.close()
