"""ASGI request boundary: correlation spans streaming and threadpool work."""

from time import monotonic_ns
from uuid import UUID, uuid4

from starlette.requests import Request

from ..application.browser_sessions import COOKIE
from ..execution import ExecutionContext
from ..logging import request_context
from .browser_session import same_origin_browser


class RequestMiddleware:
    def __init__(self, app, *, settings, events, response, sessions=None):
        self.app, self.settings, self.events, self.response = app, settings, events, response
        self.sessions = sessions

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = monotonic_ns()
        request = Request(scope)
        request.state.request_id = str(uuid4())
        status, response_started, finished, error = None, False, False, None
        code = "REQUEST_ABORTED"

        async def observed_send(message):
            nonlocal status, response_started, finished
            if message["type"] == "http.response.start":
                status, response_started = message["status"], True
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                finished = True

        with request_context(request.state.request_id):
            try:
                header = request.headers.get("authorization", "")
                token = header[7:] if header.startswith("Bearer ") else None
                cookie_auth = not header and self.sessions is not None
                if cookie_auth:
                    token = self.sessions.resolve(request.cookies.get(COOKIE))
                user = self.settings.users.get(token)
                csrf_denied = (
                    cookie_auth
                    and scope["method"] not in {"GET", "HEAD", "OPTIONS"}
                    and not same_origin_browser(request)
                )
                if user and csrf_denied:
                    code = "AUTHORIZATION_DENIED"
                    await self.response(request, code=code, status_code=403)(
                        scope, receive, observed_send
                    )
                elif not user:
                    code = "AUTHENTICATION_REQUIRED"
                    await self.response(request, code=code, status_code=401)(
                        scope, receive, observed_send
                    )
                else:
                    request.state.user = user
                    request.state.execution_context = ExecutionContext(
                        user["user_id"], user["role"], UUID(request.state.request_id)
                    )
                    with request_context(
                        request.state.request_id, actor_id=user["user_id"], role=user["role"]
                    ):
                        await self.app(scope, receive, observed_send)
                    code = getattr(
                        request.state,
                        "result_code",
                        "HTTP_ERROR" if status and status >= 400 else "OK",
                    )
            except Exception as caught:
                error, code = caught, "INTERNAL_ERROR"
                if not response_started:
                    await self.response(request, code=code, status_code=500)(
                        scope, receive, observed_send
                    )
                else:
                    # A streamed/background failure cannot replace an already sent
                    # response. Keep its status and propagate only a fixed message.
                    raise RuntimeError("Request failed after response started") from None
            finally:
                route = scope.get("route")
                route = getattr(route, "path", "UNMATCHED")
                outcome = (
                    "failure"
                    if error or (status and status >= 500)
                    else "rejected"
                    if status and status >= 400
                    else "success"
                )
                level = (
                    "ERROR"
                    if error or (status and status >= 500 and status != 503)
                    else "WARNING"
                    if status == 503
                    else "INFO"
                )
                if not finished and error is None:
                    code, outcome, level = "REQUEST_ABORTED", "unknown", "WARNING"
                elif (
                    outcome == "success"
                    and getattr(request.state, "response_status", None) == "partial"
                ):
                    outcome = "partial"
                elif outcome == "success" and route in {"/health", "/health/ready"}:
                    level = "DEBUG"
                user = getattr(request.state, "user", None)
                identity = {"actor_id": user["user_id"], "role": user["role"]} if user else {}
                self.events.emit(
                    "http.request.completed",
                    component="api",
                    outcome=outcome,
                    result_code=code,
                    level=level,
                    error=error,
                    duration_ms=(monotonic_ns() - started) // 1_000_000,
                    http_method=scope["method"]
                    if scope["method"]
                    in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
                    else "OTHER",
                    route=route,
                    http_status=status,
                    **identity,
                )
