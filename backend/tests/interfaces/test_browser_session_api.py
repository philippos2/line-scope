import io

from fastapi.testclient import TestClient

from linescope.interfaces.api import create_app
from linescope.logging import EventLogger
from linescope.settings import Settings

BROWSER = {"Origin": "http://testserver", "X-LineScope-Browser": "1"}


def client_and_settings():
    settings = Settings(users={"private-token": {"user_id": "one", "role": "manager"}})
    client = TestClient(create_app(settings, object(), EventLogger(stream=io.StringIO())))
    return client, settings


def login(client):
    return client.post(
        "/session/login", headers={**BROWSER, "Authorization": "Bearer private-token"}
    )


def test_login_cookie_and_restore_identity_without_exposing_token():
    client, _ = client_and_settings()
    result = login(client)
    assert result.status_code == 200
    cookie = result.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "private-token" not in cookie and "private-token" not in result.text
    assert client.get("/session").json()["data"] == {"user_id": "one", "role": "manager"}


def test_logout_revokes_restore():
    client, _ = client_and_settings()
    login(client)
    old = client.cookies.get("linescope_session")
    assert client.post("/session/logout", headers=BROWSER).status_code == 200
    assert client.get("/session", headers={"Cookie": "linescope_session=" + old}).status_code == 401


def test_unknown_cookie_fails_closed():
    client, _ = client_and_settings()
    assert (
        client.get("/session", headers={"Cookie": "linescope_session=unknown"}).status_code == 401
    )


def test_cross_origin_mutation_is_rejected():
    client, _ = client_and_settings()
    login(client)
    assert (
        client.post(
            "/session/logout", headers={**BROWSER, "Origin": "https://foreign.example"}
        ).status_code
        == 403
    )
    assert client.get("/session").status_code == 200


def test_missing_browser_header_is_rejected():
    client, _ = client_and_settings()
    login(client)
    assert (
        client.post("/session/logout", headers={"Origin": "http://testserver"}).status_code == 403
    )


def test_existing_bearer_api_still_works_without_browser_headers():
    client, _ = client_and_settings()
    assert (
        client.get("/health", headers={"Authorization": "Bearer private-token"}).status_code == 200
    )


def test_invalid_explicit_bearer_does_not_fall_back_to_cookie():
    client, _ = client_and_settings()
    login(client)
    assert client.get("/session", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_removed_identity_is_rechecked_on_every_request():
    client, settings = client_and_settings()
    login(client)
    settings.users.clear()
    assert client.get("/session").status_code == 401
