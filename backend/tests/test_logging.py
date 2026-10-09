import asyncio
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException

from linescope.api import create_app, response
from linescope.http_logging import RequestMiddleware
from linescope.logging import (
    EventLogger,
    configure_runtime_logging,
    current_request_id,
    request_context,
)
from linescope.settings import Settings

SECRET = "private-token-password-body-sql"
AUTH = {"Authorization": "Bearer " + SECRET}


def captured_app(level="DEBUG", database=None, stream=None):
    output = io.StringIO() if stream is None else stream
    events = EventLogger(level, output)
    app = create_app(
        Settings(users={SECRET: {"user_id": "floor1", "role": "floor"}}),
        database,
        event_logger=events,
    )
    return app, output, events


def rows(output):
    return [json.loads(line) for line in output.getvalue().splitlines()]


def completed(output):
    return [row for row in rows(output) if row["event"] == "http.request.completed"]


@pytest.mark.parametrize(
    "path,status,code,level",
    [
        ("/health", 200, "OK", "DEBUG"),
        ("/absent/" + SECRET + "?token=" + SECRET, 404, "HTTP_ERROR", "INFO"),
    ],
)
def test_http_completion_is_correlated_bounded_json_without_raw_url(path, status, code, level):
    app, output, _ = captured_app()
    with TestClient(app) as client:
        result = client.get(path, headers={**AUTH, "X-Request-ID": str(uuid4())})
    (entry,) = completed(output)
    assert (entry["http_status"], entry["result_code"], entry["level"]) == (status, code, level)
    assert entry["request_id"] == result.json()["request_id"]
    assert entry["actor_id"] == "floor1" and entry["role"] == "floor"
    assert entry["duration_ms"] >= 0 and type(entry["duration_ms"]) is int
    assert entry["timestamp"].endswith("Z") and entry["log_schema_version"] == 1
    assert entry["route"] == ("/health" if status == 200 else "UNMATCHED")
    assert SECRET not in output.getvalue()
    assert current_request_id() is None


@pytest.mark.parametrize("header", [None, "Basic " + SECRET, "Bearer invalid-" + SECRET])
def test_authentication_rejection_logged_without_actor_or_headers(header):
    app, output, _ = captured_app()
    with TestClient(app) as client:
        result = client.get("/health", headers={"Authorization": header} if header else {})
    (entry,) = completed(output)
    assert entry["level"] == "INFO" and entry["outcome"] == "rejected"
    assert entry["result_code"] == "AUTHENTICATION_REQUIRED"
    assert entry["request_id"] == result.json()["request_id"]
    assert "actor_id" not in entry and "role" not in entry
    assert SECRET not in output.getvalue()


@pytest.mark.parametrize("failure", [False, True])
def test_readiness_dependency_failure_is_warning_and_sanitized(failure):
    class Down:
        def check(self):
            if failure:
                raise psycopg.OperationalError("postgresql://user:" + SECRET + "@host/db")
            return False

    app, output, _ = captured_app(database=Down())
    with TestClient(app) as client:
        result = client.get("/health/ready", headers=AUTH)
    (entry,) = completed(output)
    assert result.status_code == 503
    assert entry["level"] == "WARNING" and entry["outcome"] == "failure"
    assert entry["result_code"] == "DEPENDENCY_UNAVAILABLE"
    assert SECRET not in output.getvalue()


def test_unexpected_exception_has_one_sanitized_stack_and_envelope():
    app, output, _ = captured_app()

    @app.get("/boom")
    def boom():
        raise RuntimeError(SECRET)

    with TestClient(app) as client:
        result = client.get("/boom", headers=AUTH)
    (entry,) = completed(output)
    assert result.status_code == 500 and entry["outcome"] == "failure"
    assert entry["level"] == "ERROR" and entry["exception_type"] == "RuntimeError"
    assert entry["request_id"] == result.json()["request_id"]
    assert entry["stack_frames"] and any(f["function"] == "boom" for f in entry["stack_frames"])
    assert len(entry["stack_frames"]) <= 20
    assert all(set(frame) == {"module", "function", "line"} for frame in entry["stack_frames"])
    assert SECRET not in output.getvalue() and SECRET not in result.text


def test_expected_http_exception_does_not_log_its_detail():
    app, output, _ = captured_app()

    @app.get("/denied")
    def denied():
        raise HTTPException(403, detail=SECRET)

    with TestClient(app) as client:
        result = client.get("/denied", headers=AUTH)
    (entry,) = completed(output)
    assert result.status_code == 403 and entry["level"] == "INFO"
    assert entry["outcome"] == "rejected" and "stack_frames" not in entry
    assert SECRET not in output.getvalue()


def test_route_parameter_body_query_and_response_are_not_logged():
    app, output, _ = captured_app()

    @app.post("/objects/{object_id}")
    async def object_response(object_id: str, request: Request):
        return response(request, {"private": await request.json()})

    with TestClient(app) as client:
        result = client.post(
            "/objects/" + SECRET + "?secret=" + SECRET, headers=AUTH, json={"private": SECRET}
        )
    assert result.status_code == 200
    (entry,) = completed(output)
    assert entry["route"] == "/objects/{object_id}" and SECRET not in output.getvalue()


@pytest.mark.parametrize("level", ["INFO", "WARNING", "ERROR"])
def test_healthy_poll_is_suppressed_and_apps_do_not_change_each_others_level(level):
    app, output, _ = captured_app(level)
    debug_app, debug_output, _ = captured_app("DEBUG")
    with TestClient(app) as client:
        client.get("/health", headers=AUTH)
    with TestClient(debug_app) as client:
        client.get("/health", headers=AUTH)
    assert not completed(output) and len(completed(debug_output)) == 1


def test_parallel_async_and_threadpool_routes_share_only_their_request_context():
    app, output, _ = captured_app()

    @app.get("/async")
    async def async_route(request: Request):
        first = current_request_id()
        await asyncio.sleep(0)
        assert first == current_request_id() == request.state.request_id
        return response(request, {"context": first})

    @app.get("/thread")
    def thread_route(request: Request):
        assert current_request_id() == request.state.request_id
        return response(request, {"context": current_request_id()})

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            return await asyncio.gather(
                *(client.get(path, headers=AUTH) for path in ["/async", "/thread"] * 8)
            )

    results = asyncio.run(run())
    ids = {result.json()["request_id"] for result in results}
    assert len(ids) == 16
    assert {row["request_id"] for row in completed(output)} == ids
    assert all(r.json()["data"]["context"] == r.json()["request_id"] for r in results)
    assert current_request_id() is None


def test_context_resets_after_nested_error_and_thread_usage():
    parent = uuid4()
    with request_context(parent):
        with pytest.raises(RuntimeError), request_context(uuid4()):
            raise RuntimeError(SECRET)
        assert current_request_id() == str(parent)
        with ThreadPoolExecutor(1) as pool:
            assert pool.submit(current_request_id).result() is None
    assert current_request_id() is None


def test_allowlist_never_serializes_unknown_objects_and_rejects_invalid_fields():
    class Private:
        def __repr__(self):
            raise AssertionError("Must never stringify arbitrary values")

    output = io.StringIO()
    events = EventLogger("DEBUG", output)
    events.emit(
        "tool.call.completed",
        component="tool",
        outcome="success",
        result_code="OK",
        level="DEBUG",
        body=Private(),
        authorization=SECRET,
        sql=SECRET,
        prompt=SECRET,
        snapshot=SECRET,
        exception_type=SECRET,
        stack_frames=[SECRET],
        request_id="invalid-" + SECRET,
        context_id=True,
        duration_ms=True,
        role=SECRET,
        actor_id="x" * 257,
        snapshot_hash=SECRET,
        http_status=999,
        attempt_count=-1,
    )
    (entry,) = rows(output)
    assert set(entry) == {
        "log_schema_version",
        "timestamp",
        "level",
        "service",
        "event",
        "component",
        "outcome",
        "result_code",
        "request_id",
    }
    UUID(entry["request_id"])
    assert SECRET not in output.getvalue()


def test_context_identity_cannot_be_overridden_and_values_are_json_escaped():
    output = io.StringIO()
    events = EventLogger("DEBUG", output)
    identity = uuid4()
    with request_context(identity, actor_id="trusted\nactor", role="manager"):
        events.emit(
            "tool.call.completed",
            component="tool",
            outcome="success",
            result_code="OK",
            request_id=uuid4(),
            actor_id="spoofed",
            role="floor",
            update_request_id=str(uuid4()).upper(),
            duration_ms=0,
        )
    assert len(output.getvalue().splitlines()) == 1
    (entry,) = rows(output)
    assert entry["request_id"] == str(identity) and entry["actor_id"] == "trusted\nactor"
    assert entry["role"] == "manager" and entry["update_request_id"].islower()


@pytest.mark.parametrize("invalid", ["secret-value", "info", "CRITICAL", "", True, None])
def test_invalid_logging_configuration_rejected(invalid):
    with pytest.raises(ValueError):
        Settings(log_level=invalid)
    with pytest.raises(ValueError):
        EventLogger(invalid)


def test_log_level_environment(monkeypatch):
    monkeypatch.setenv("LINESCOPE_LOG_LEVEL", "DEBUG")
    assert Settings.env().log_level == "DEBUG"


@pytest.mark.parametrize("stage", ["write", "flush"])
def test_stdout_failure_does_not_change_http_result_or_leak_stderr(stage, capsys):
    class Broken(io.StringIO):
        def write(self, value):
            if stage == "write":
                raise RuntimeError(SECRET)
            return super().write(value)

        def flush(self):
            if stage == "flush":
                raise RuntimeError(SECRET)

    app, _, _ = captured_app(stream=Broken())
    with TestClient(app) as client:
        result = client.get("/health", headers=AUTH)
    assert result.status_code == 200
    captured = capsys.readouterr()
    assert SECRET not in captured.err and SECRET not in captured.out
    assert "LineScope logging output failed" in captured.err


@contextmanager
def preserved_global_logging():
    names = ["", "uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "httpcore", "psycopg"]
    saved = [
        (
            logging.getLogger(n),
            logging.getLogger(n).handlers[:],
            logging.getLogger(n).level,
            logging.getLogger(n).propagate,
            logging.getLogger(n).disabled,
        )
        for n in names
    ]
    try:
        yield
    finally:
        for logger, handlers, level, propagate, disabled in saved:
            logger.handlers, logger.propagate, logger.disabled = handlers, propagate, disabled
            logger.setLevel(level)


def test_runtime_configuration_is_idempotent_and_drops_third_party_message_and_exception():
    output = io.StringIO()
    events = EventLogger("DEBUG", output)
    with preserved_global_logging():
        configure_runtime_logging(events)
        configure_runtime_logging(events)
        assert len(logging.getLogger().handlers) == 1
        try:
            raise RuntimeError(SECRET)
        except RuntimeError:
            logging.getLogger("uvicorn.error").exception("query secret %s", SECRET)
        logging.getLogger("uvicorn.error").log(35, SECRET)
        logging.getLogger("httpx").debug("private URL %s", SECRET)
        logging.getLogger("uvicorn.access").error(SECRET)
    entries = rows(output)
    assert len(entries) == 2
    assert [entry["level"] for entry in entries] == ["ERROR", "WARNING"]
    assert all(
        entry["event"] == "runtime.diagnostic" and "stack_frames" not in entry for entry in entries
    )
    assert SECRET not in output.getvalue()


def test_cancelled_request_is_unknown_and_context_is_reset():
    output = io.StringIO()

    async def cancelled(scope, receive, send):
        raise asyncio.CancelledError()

    middleware = RequestMiddleware(
        cancelled,
        settings=Settings(users={SECRET: {"user_id": "u", "role": "floor"}}),
        events=EventLogger("DEBUG", output),
        response=response,
    )
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/cancelled",
        "headers": [(b"authorization", ("Bearer " + SECRET).encode())],
    }

    async def run():
        with pytest.raises(asyncio.CancelledError):
            await middleware(scope, None, None)
        assert current_request_id() is None

    asyncio.run(run())
    (entry,) = completed(output)
    assert entry["outcome"] == "unknown" and entry["result_code"] == "REQUEST_ABORTED"


def test_exception_stack_is_bounded_without_source_or_local_values():
    output = io.StringIO()
    events = EventLogger("DEBUG", output)

    def deep(depth):
        if depth:
            return deep(depth - 1)
        raise RuntimeError(SECRET)

    try:
        deep(40)
    except RuntimeError as error:
        events.emit(
            "http.request.completed",
            component="api",
            outcome="failure",
            result_code="INTERNAL_ERROR",
            level="ERROR",
            error=error,
            duration_ms=1,
        )
    (entry,) = rows(output)
    assert len(entry["stack_frames"]) == 20
    assert SECRET not in output.getvalue()


@pytest.mark.parametrize("body_finished", [False, True])
def test_response_started_failure_does_not_send_replacement_status_or_leak_exception(body_finished):
    output = io.StringIO()
    sent = []

    async def broken(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        if body_finished:
            await send({"type": "http.response.body", "body": b"ok"})
        raise RuntimeError(SECRET)

    async def send(message):
        sent.append(message)

    middleware = RequestMiddleware(
        broken,
        settings=Settings(users={SECRET: {"user_id": "u", "role": "floor"}}),
        events=EventLogger("DEBUG", output),
        response=response,
    )
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/broken",
        "headers": [(b"authorization", ("Bearer " + SECRET).encode())],
    }

    async def run():
        with pytest.raises(RuntimeError, match="^Request failed after response started$"):
            await middleware(scope, None, send)
        assert current_request_id() is None

    asyncio.run(run())
    assert [m["status"] for m in sent if m["type"] == "http.response.start"] == [200]
    (entry,) = completed(output)
    assert entry["outcome"] == "failure" and entry["http_status"] == 200
    assert entry["exception_type"] == "RuntimeError" and SECRET not in output.getvalue()


def test_formatter_rechecks_allowlist_even_for_direct_logging_calls():
    output = io.StringIO()
    events = EventLogger("DEBUG", output)
    events.logger.info(
        SECRET,
        extra={
            "safe_event": {
                "event": "service.started",
                "component": "api",
                "outcome": "success",
                "result_code": "OK",
                "request_id": str(uuid4()),
                "body": SECRET,
                "exception_type": SECRET,
                "duration_ms": False,
            }
        },
    )
    (entry,) = rows(output)
    assert "body" not in entry and "exception_type" not in entry and "duration_ms" not in entry
    assert SECRET not in output.getvalue()


def test_serve_disables_raw_access_logging(monkeypatch):
    import sys

    import uvicorn

    from linescope.cli import main

    captured = {}
    monkeypatch.setattr(sys, "argv", ["linescope", "serve"])
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.update(kwargs))
    with preserved_global_logging():
        main()
    assert captured["access_log"] is False and captured["log_config"] is None


def test_partial_envelope_is_not_logged_as_complete_success():
    app, output, _ = captured_app()

    @app.get("/partial")
    def partial_result(request: Request):
        return response(request, {"complete": False}, partial=True)

    with TestClient(app) as client:
        result = client.get("/partial", headers=AUTH)
    (entry,) = completed(output)
    assert result.status_code == 200 and result.json()["status"] == "partial"
    assert entry["outcome"] == "partial" and entry["level"] == "INFO"
    assert entry["request_id"] == result.json()["request_id"]
