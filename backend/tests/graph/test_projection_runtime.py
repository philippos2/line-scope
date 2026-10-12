from threading import Event

import pytest

from linescope.graph.graph_leadership import GraphLeadershipLost, graph_leadership
from linescope.graph.projection_runtime import projection_step, run_projection_loop
from linescope.graph.projection_worker import ProjectionStep


class Worker:
    def __init__(self, *, error=None):
        self.leaders = []
        self.error = error

    def run_once(self, leader):
        leader.require()
        self.leaders.append(leader)
        if self.error:
            raise self.error
        return ProjectionStep("IDLE")


def test_step_releases_dedicated_leadership_connection(db):
    worker = Worker()
    assert projection_step(db, worker) == "IDLE"
    with pytest.raises(GraphLeadershipLost):
        worker.leaders[0].require()
    with graph_leadership(db) as leader:
        leader.require()


def test_busy_leader_does_not_invoke_worker(db):
    worker = Worker()
    with graph_leadership(db):
        assert projection_step(db, worker) == "BUSY"
    assert not worker.leaders


def test_unexpected_failure_stops_caller_and_releases_leader(db):
    worker = Worker(error=RuntimeError("failure"))
    with pytest.raises(RuntimeError):
        projection_step(db, worker)
    with graph_leadership(db) as leader:
        leader.require()


def test_shutdown_wait_is_interruptible_and_prevents_next_step(db):
    class Stop:
        stopped = False
        waits = []

        def is_set(self):
            return self.stopped

        def wait(self, seconds):
            self.waits.append(seconds)
            self.stopped = True

    stop = Stop()
    worker = Worker()
    run_projection_loop(db, worker, stop)
    assert stop.waits == [1] and len(worker.leaders) == 1


def test_shutdown_requested_before_start_does_not_touch_storage():
    stop = Event()
    stop.set()
    run_projection_loop(None, None, stop)


@pytest.mark.parametrize("interval", [0, -1, True, float("inf"), float("nan")])
def test_invalid_polling_interval_rejected(interval):
    with pytest.raises(ValueError):
        run_projection_loop(None, None, Event(), interval_seconds=interval)


@pytest.mark.parametrize("signum", [15, 2])
def test_cli_process_exits_cleanly_on_termination_signal(db, signum):
    import json
    import os
    import subprocess
    import sys
    from selectors import EVENT_READ, DefaultSelector

    db.migrate()
    environment = {
        **os.environ,
        "LINESCOPE_DSN": db.settings.dsn,
        "LINESCOPE_NEO4J_URI": os.environ["LINESCOPE_TEST_NEO4J_URI"],
        "LINESCOPE_NEO4J_USER": "neo4j",
        "LINESCOPE_NEO4J_PASSWORD": "disposable-graph-password",
    }
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "linescope.cli", "project-graph"],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        with DefaultSelector() as selector:
            selector.register(process.stdout, EVENT_READ)
            assert selector.select(timeout=10), "CLI did not report startup"
        started = process.stdout.readline()
        assert json.loads(started)["event"] == "service.started"
        process.send_signal(signum)
        output, errors = process.communicate(timeout=10)
        assert process.returncode == 0
        assert "service.stopped" in output
        assert "disposable-graph-password" not in started + output + errors
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
