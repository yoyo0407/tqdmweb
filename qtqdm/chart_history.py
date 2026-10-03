"""Complete metric history, bounded overview and incremental transport."""

from bisect import bisect_right


def history_page(series, after, last_update, limit=2000):
    """Return an incremental page without repeatedly sending the whole run."""
    if type(after) is not int or not 0 <= after <= last_update:
        raise ValueError("Invalid history cursor")
    if type(limit) is not int or not 1 <= limit <= 2000:
        raise ValueError("History page size must be between 1 and 2000")
    end = min(last_update, after + limit)
    charts = {}
    for name, points in series.items():
        start_index = bisect_right(points, after, key=lambda point: point[3])
        end_index = bisect_right(points, end, key=lambda point: point[3])
        if end_index > start_index:
            charts[name] = points[start_index:end_index]
    return {"charts": charts, "next_update": end, "has_more": end < last_update}


class ChartHistory:
    def __init__(self):
        self.full = []
        self.overview = []
        self.updates = 0
        self.stride = 1

    def append(self, point):
        # Point: [elapsed seconds, metric value, item number, update number].
        self.full.append(point)
        self.updates += 1
        if (self.updates - 1) % self.stride == 0:
            self.overview.append(point)
        if len(self.overview) >= 600:
            self.overview = self.overview[::2]
            self.stride *= 2

    def snapshot(self):
        overview = list(self.overview)
        if self.full and overview[-1] is not self.full[-1]:
            overview.append(self.full[-1])
        return {"overview": overview}
