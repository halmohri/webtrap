import math
import psutil


def _active_connections():
    """Return system-wide ESTABLISHED TCP connections. Requires sudo on macOS."""
    try:
        return sum(1 for c in psutil.net_connections() if c.status == "ESTABLISHED")
    except psutil.AccessDenied:
        return sum(1 for c in psutil.Process().net_connections() if c.status == "ESTABLISHED")


class System:

    def __init__(self):
        self._baseline_conns = _active_connections()

    def net_score(self):
        """
        Exponential model: score = 1 - exp(-k * delta)
        where delta = connections above baseline and k controls sensitivity.
        Returns a value in [0, 1]: 0 at baseline, approaching 1 as load grows.
        """
        k = 0.1
        delta = max(0, _active_connections() - self._baseline_conns)
        return 1.0 - math.exp(-k * delta)

    def snapshot(self):
        cpu = psutil.cpu_percent(interval=0.1) / 100.0
        mem = psutil.virtual_memory().percent / 100.0
        net = self.net_score()
        return {"cpu": cpu, "mem": mem, "net": net}

    @property
    def health(self):
        s = self.snapshot()
        return max(s["cpu"], s["mem"], s["net"])
