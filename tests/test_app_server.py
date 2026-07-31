"""app_server (③ UI launcher) — auth helpers and construction guarantees (design §3.1-§3.3).

The NiceGUI login flow is browser-verified; here we lock the pure helpers and the structural
promise that the server launcher never imports the legacy UI / calc_service / init_db, so the
reboot-fragile paths and workbench.db never open on the server (§3.1.2).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from web.service_ui import auth


def test_check_password_constant_time_and_fail_closed():
    assert auth.check_password("hunter2", "hunter2") is True
    assert auth.check_password("wrong", "hunter2") is False
    assert auth.check_password("", "hunter2") is False
    assert auth.check_password("anything", "") is False  # no password configured -> deny


def test_public_paths():
    # legitimately public: the login page, NiceGUI assets/ws, health, favicon
    assert auth.is_public_path("/login")
    assert auth.is_public_path("/login/")
    assert auth.is_public_path("/_nicegui/anything")
    assert auth.is_public_path("/static/x.js")
    assert auth.is_public_path("/health")
    assert auth.is_public_path("/favicon.ico")
    # protected app routes stay protected
    assert not auth.is_public_path("/jobs")
    assert not auth.is_public_path("/jobs/3")
    assert not auth.is_public_path("/projects")


def test_public_path_requires_separator_boundary():
    """A prefix must match at a '/' boundary (or exact); a bare startswith would leak look-alike
    paths onto the tailnet (review §10.4)."""
    assert not auth.is_public_path("/static3d/index.html")   # not /static/...
    assert not auth.is_public_path("/staticassets")
    assert not auth.is_public_path("/healthz-secret")
    assert not auth.is_public_path("/login-backdoor")
    assert not auth.is_public_path("/_nicegui-evil")
    assert not auth.is_public_path("/favicon.ico.evil")      # only exact /favicon.ico is public


def test_app_server_does_not_import_legacy_ui_or_db():
    """Importing app_server must not pull in the legacy pages, calc_service, or the DB layer
    (design §3.1.2). Checked in a subprocess so this test's own imports don't mask it."""
    forbidden = ("web.pages.calculate", "web.pages.dashboard", "web.pages.result",
                 "web.services.calc_service", "web.services.project_service",
                 "web.db.database", "web.db.models")
    code = (
        "import app_server, sys;"
        f"forbidden={forbidden!r};"
        "bad=[m for m in forbidden if m in sys.modules];"
        "sys.exit(1 if bad else 0)"
    )
    root = str(Path(__file__).parent.parent)
    # WB_UI_PASSWORD unset is fine: importing does not call main(), so no SystemExit.
    assert subprocess.call([sys.executable, "-c", code], cwd=root) == 0


def test_app_server_main_refuses_without_password(monkeypatch):
    import app_server
    monkeypatch.delenv("WB_UI_PASSWORD", raising=False)
    try:
        app_server.main()
    except SystemExit as e:
        assert "WB_UI_PASSWORD" in str(e)
    else:
        raise AssertionError("main() should refuse to start without WB_UI_PASSWORD")
