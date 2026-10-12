"""Process scheduling around the existing fenced, atomic worker iteration."""

from math import isfinite

from .graph_leadership import GraphLeaderBusy, graph_leadership


def projection_step(database, worker):
    # Release leadership between iterations so Rebuild can acquire it.
    # Never reconnect inside an iteration after leadership is lost.
    try:
        with graph_leadership(database) as leader:
            return worker.run_once(leader).status
    except GraphLeaderBusy:
        return "BUSY"


def run_projection_loop(database, worker, stop, *, interval_seconds=1):
    if (
        type(interval_seconds) not in (int, float)
        or not isfinite(interval_seconds)
        or interval_seconds <= 0
    ):
        raise ValueError("Projection polling interval must be positive")
    while not stop.is_set():
        status = projection_step(database, worker)
        if status != "APPLIED":
            stop.wait(interval_seconds)
