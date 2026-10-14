"""Runner safety only; existing API tests cover the business invariants."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def script():
    path = Path(__file__).resolve().parents[3] / "scripts" / "verify_minimal_flow.py"
    spec = importlib.util.spec_from_file_location("minimal_flow", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_disposable_environment_is_removed_on_verification_failure(monkeypatch):
    module = script()
    commands = []
    monkeypatch.setattr(
        module.subprocess, "run", lambda command, **kwargs: commands.append(command)
    )
    with pytest.raises(RuntimeError, match="verification failed"):
        with module.disposable_fixture() as fixture:
            credentials = fixture.credentials_file
            project = fixture.project
            assert credentials.stat().st_mode & 0o777 == 0o600
            raise RuntimeError("verification failed")
    assert not credentials.exists() and not credentials.parent.exists()
    assert commands[-1][-3:] == ["down", "--volumes", "--remove-orphans"]
    assert commands[-1][commands[-1].index("-p") + 1] == project


def test_fixture_does_not_inherit_normal_demo_settings_or_expose_tokens(monkeypatch):
    module = script()
    monkeypatch.setenv("LINESCOPE_DSN", "normal-demo-secret")
    monkeypatch.setenv("LINESCOPE_USERS", "normal-demo-token")
    calls = []

    def capture(command, **options):
        calls.append((command, options))
        return SimpleNamespace(stdout='{"status":"ok"}\n200')

    monkeypatch.setattr(module.subprocess, "run", capture)
    with module.disposable_fixture() as fixture:
        fixture.docker("up", "-d", "api")
        fixture.request("/health/ready")
        owner, approver = fixture.owner, fixture.approver
        assert fixture.project.startswith("linescope-minimal-")
    for command, options in calls:
        if command[0] == "curl":
            assert command[1:4] == ["--disable", "--noproxy", "*"]
            assert owner in options["input"]
        else:
            assert not any(key.startswith("LINESCOPE_") for key in options["env"])
        assert owner not in str(command) and approver not in str(command)
        assert "normal-demo-secret" not in str(command)
