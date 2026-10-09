from contextlib import asynccontextmanager
from uuid import uuid4

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .database import Database
from .http_logging import RequestMiddleware
from .logging import EventLogger, request_context
from .reads import ReadTools
from .settings import Settings


def response(request, data=None, code=None, status_code=200, *, partial=False):
    request.state.result_code = code or "OK"
    request.state.response_status = "error" if code else "partial" if partial else "ok"
    return JSONResponse(
        {
            "request_id": request.state.request_id,
            "context_id": None,
            "status": request.state.response_status,
            "answer": None,
            "data": data or {},
            "evidence": {},
            "warnings": [],
            "errors": [{"code": code, "message": code, "details": {}}] if code else [],
        },
        status_code=status_code,
    )


def create_app(settings=None, database=None, event_logger=None):
    settings = settings or Settings.env()
    database = database or Database(settings)
    events = event_logger or EventLogger(settings.log_level)

    @asynccontextmanager
    async def lifespan(app):
        with request_context(uuid4()):
            events.emit("service.started", component="api", outcome="success", result_code="OK")
        try:
            yield
        finally:
            with request_context(uuid4()):
                events.emit("service.stopped", component="api", outcome="success", result_code="OK")

    app = FastAPI(
        title="LineScope", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.database = database
    app.state.read_tools = ReadTools(database)

    app.state.events = events
    app.add_middleware(RequestMiddleware, settings=settings, events=events, response=response)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        return response(request, code="HTTP_ERROR", status_code=error.status_code)

    @app.get("/health")
    def health(request: Request):
        return response(request, {"service": "linescope", "alive": True})

    @app.get("/health/ready")
    def ready(request: Request):
        try:
            if not database.check():
                return response(request, code="DEPENDENCY_UNAVAILABLE", status_code=503)
        except psycopg.Error:
            return response(request, code="DEPENDENCY_UNAVAILABLE", status_code=503)
        return response(request, {"service": "linescope", "postgresql": "available"})

    return app
