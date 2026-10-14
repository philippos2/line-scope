from linescope.application.browser_sessions import BrowserSessions


def test_session_is_opaque_and_resolves_server_token():
    store = BrowserSessions()
    key = store.create("private-token")
    assert key != "private-token"
    assert store.resolve(key) == "private-token"
    assert store.resolve("invented") is None


def test_expiry_boundary_does_not_slide():
    now = [0]
    store = BrowserSessions(clock=lambda: now[0], lifetime=10)
    key = store.create("secret")
    now[0] = 9
    assert store.resolve(key) == "secret"
    now[0] = 10
    assert store.resolve(key) is None


def test_capacity_rejects_then_reclaims_expired_entries():
    now = [0]
    store = BrowserSessions(clock=lambda: now[0], lifetime=10, capacity=1)
    store.create("one")
    assert store.create("two") is None
    now[0] = 10
    assert store.create("two") is not None


def test_switch_rotates_session_and_invalidates_old_cookie():
    store = BrowserSessions(capacity=1)
    old = store.create("one")
    new = store.create("two", old)
    assert new != old and store.resolve(new) == "two"
    assert store.resolve(old) is None


def test_logout_revokes_session():
    store = BrowserSessions()
    key = store.create("secret")
    store.revoke(key)
    assert store.resolve(key) is None
