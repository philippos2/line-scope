"""Browser-only session endpoints. No DB access or business authority changes."""

from fastapi import Request

from ..application.browser_sessions import COOKIE


def same_origin_browser(request):
    return (
        request.headers.get("x-linescope-browser") == "1"
        and request.headers.get("origin") == f"{request.url.scheme}://{request.url.netloc}"
    )


def install_session_routes(app, sessions, response):
    @app.get("/session")
    def session(request: Request):
        result = response(request, request.state.user)
        result.headers["Cache-Control"] = "no-store"
        return result

    @app.post("/session/login")
    async def login(request: Request):
        if not same_origin_browser(request) or await request.body():
            return response(request, code="AUTHORIZATION_DENIED", status_code=403)
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            return response(request, code="AUTHENTICATION_REQUIRED", status_code=401)
        identifier = sessions.create(header[7:], request.cookies.get(COOKIE))
        if identifier is None:
            return response(request, code="RESOURCE_BUSY", status_code=503)
        result = response(request, request.state.user)
        result.set_cookie(
            COOKIE,
            identifier,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
        )
        result.headers["Cache-Control"] = "no-store"
        return result

    @app.post("/session/logout")
    async def logout(request: Request):
        if not same_origin_browser(request) or await request.body():
            return response(request, code="AUTHORIZATION_DENIED", status_code=403)
        sessions.revoke(request.cookies.get(COOKIE))
        result = response(request, {"disconnected": True})
        result.delete_cookie(COOKIE, httponly=True, samesite="strict")
        result.headers["Cache-Control"] = "no-store"
        return result
