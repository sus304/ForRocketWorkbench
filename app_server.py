"""Server-resident UI launcher (use case ③; docs/result_retrieval_design.md §3.1.1-§3.3).

Distinct from app.py by construction: it registers ONLY the new service UI (`/jobs` + result
API client) and never imports the legacy UI, `calc_service`, or `init_db()` — so the reboot-
fragile legacy paths and the `workbench.db` are never opened on the server (§3.1.2). It binds the
tailnet interface, uses a fixed port, runs headless (show=False), and puts a NiceGUI session
login in front of every page (R1). The compute service itself is owned by systemd here; this
process only connects to it via WB_SERVICE_URL (no local spawn/supervise).

Run (systemd, design §3.2):
    WB_UI_HOST=<tailscale0 ip> WB_UI_PASSWORD=... WB_SERVICE_URL=http://<jobsvc>:8760 \
    WB_API_TOKEN=... python app_server.py
"""
import os

from nicegui import app, ui
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse

from service.serve import validate_bind_host
from web.service_ui import auth
import web.service_ui.pages        # noqa: F401 — registers @ui.page('/jobs') + @ui.page('/jobs/{id}')
import web.service_ui.projects_ui   # noqa: F401 — registers @ui.page('/projects') + edit
import web.pages.tools             # noqa: F401 — /tools menu (service_header, DB-free calculators)
import web.pages.tools_barrowman   # noqa: F401 — /tools/barrowman
import web.pages.tools_mass        # noqa: F401 — /tools/mass
import web.pages.tools_engine      # noqa: F401 — /tools/engine

DEFAULT_PORT = 8081


def _ui_host() -> str:
    """Bind loopback by default, or the tailscale0 address via WB_UI_HOST (③). 0.0.0.0/LAN is
    refused by validate_bind_host — same policy as the compute service (design §7/§13-3)."""
    return validate_bind_host(os.environ.get("WB_UI_HOST", "127.0.0.1"))


class AuthMiddleware(BaseHTTPMiddleware):
    """Redirect unauthenticated requests to /login. app.storage.user is per-browser-session and
    signed with storage_secret, so the flag cannot be forged client-side."""

    async def dispatch(self, request, call_next):
        if not app.storage.user.get("authenticated", False):
            if not auth.is_public_path(request.url.path):
                app.storage.user["referrer_path"] = request.url.path
                return RedirectResponse("/login")
        return await call_next(request)


@ui.page("/")
def _root():
    # The service UI has no landing page of its own; the jobs list is the home. Registering "/"
    # here also gives the post-login redirect a valid target when the user opened the root URL
    # (referrer_path == "/"), instead of a 404.
    ui.navigate.to("/jobs")


@ui.page("/login")
def login_page():
    if app.storage.user.get("authenticated", False):
        ui.navigate.to("/jobs")
        return
    expected = os.environ.get("WB_UI_PASSWORD", "")

    def _try():
        if auth.check_password(pw.value, expected):
            app.storage.user.update({"authenticated": True})
            dest = app.storage.user.get("referrer_path") or "/jobs"
            if dest in ("/", "/login"):
                dest = "/jobs"
            ui.navigate.to(dest)
        else:
            ui.notify("Wrong password", color="negative")

    with ui.card().classes("absolute-center"):
        ui.label("ForRocket Workbench").classes("text-h6")
        ui.label("Sign in").classes("text-caption text-grey q-mb-sm")
        pw = ui.input("Password", password=True, password_toggle_button=True) \
            .on("keydown.enter", _try)
        ui.button("Sign in", on_click=_try)


def main():
    password = os.environ.get("WB_UI_PASSWORD", "")
    if not password:
        raise SystemExit("WB_UI_PASSWORD is not set; refusing to start the UI without login")
    storage_secret = os.environ.get("WB_UI_STORAGE_SECRET") or password
    app.add_middleware(AuthMiddleware)
    ui.run(
        title="ForRocket Workbench",
        host=_ui_host(),
        port=int(os.environ.get("WB_UI_PORT", str(DEFAULT_PORT))),
        reload=False,
        dark=True,
        show=False,
        storage_secret=storage_secret,
        favicon="pic/forrocket_icon.ico",
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
