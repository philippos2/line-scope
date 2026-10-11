"""Server-owned monotonic Graph analysis budget, independent of Rebuild.

Compatible with existing PG/Neo4j timeout helpers. Expiry never by itself
authorizes publication of a partial result: consistency checks still apply.
"""

from math import isfinite
from time import monotonic


class GraphAnalysisTimeout(TimeoutError):
    """No analysis time remains; the caller must stop work."""


class GraphAnalysisBudget:
    def __init__(self, timeout_ms, *, clock=monotonic):
        if type(timeout_ms) is not int or timeout_ms <= 0:
            raise ValueError("Server Graph timeout must be a positive integer")
        started = clock()
        if type(started) not in (int, float) or not isfinite(started):
            raise ValueError("Graph clock must be finite")
        self._clock = clock
        self._deadline = started + timeout_ms / 1000
        if not isfinite(self._deadline):
            raise ValueError("Graph deadline must be finite")

    def remaining(self):
        now = self._clock()
        if type(now) not in (int, float) or not isfinite(now):
            raise GraphAnalysisTimeout("Graph analysis clock is unavailable")
        remaining = self._deadline - now
        if remaining <= 0:
            raise GraphAnalysisTimeout("Graph analysis deadline expired")
        return remaining

    def require(self):
        self.remaining()
