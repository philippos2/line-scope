import logging
from uuid import UUID, uuid4

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .database import Database
from .execution import ExecutionContext
from .reads import ReadTools
from .settings import Settings

logger = logging.getLogger(__name__)


def response(request, data=None, code=None, status_code=200):
    return JSONResponse(
        {
            "request_id": request.state.request_id,
            "context_id": None,
            "status": "error" if code else "ok",
            "answer": None,
            "data": data or {},
            "evidence": {},
            "warnings": [],
            "errors": [{"code": code, "message": code, "details": {}}] if code else [],
        },
        status_code=status_code,
    )


def create_app(settings=None, database=None):
    settings = settings or Settings.env()
    database = database or Database(settings)
    app = FastAPI(title="LineScope", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.database = database
    app.state.read_tools = ReadTools(database)

    @app.middleware("http")
    async def authenticate(request, call_next):
        request.state.request_id = str(uuid4())
        header = request.headers.get("authorization", "")
        token = header[7:] if header.startswith("Bearer ") else None
        user = settings.users.get(token)
        if not user:
            return response(request, code="AUTHENTICATION_REQUIRED", status_code=401)
        request.state.user = user
        request.state.execution_context = ExecutionContext(
            authenticated_user_id=user["user_id"],
            role=user["role"],
            request_id=UUID(request.state.request_id),
        )
        try:
            return await call_next(request)
        except Exception:
            logger.error("Unexpected request failure request_id=%s", request.state.request_id)
            return response(request, code="INTERNAL_ERROR", status_code=500)

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
