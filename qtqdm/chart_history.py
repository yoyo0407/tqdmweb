"""Bounded chart samples for one numeric metric."""

from collections import deque


class ChartHistory:
    def __init__(self):
        self.recent = deque(maxlen=300)
        self.overview = []
        self.updates = 0
        self.stride = 1

    def append(self, point):
        # Point: [elapsed seconds, metric value, item number, update number].
        self.recent.append(point)
        self.updates += 1
        if (self.updates - 1) % self.stride == 0:
            self.overview.append(point)
        if len(self.overview) >= 600:
            self.overview = self.overview[::2]
            self.stride *= 2

    def snapshot(self):
        overview = list(self.overview)
        if self.recent and overview[-1] is not self.recent[-1]:
            overview.append(self.recent[-1])
        return {"recent": list(self.recent), "overview": overview}
