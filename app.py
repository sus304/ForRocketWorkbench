import os
import subprocess

from nicegui import app, ui

from service.serve import validate_bind_host
from web.db.database import init_db
from web.services import calc_service
import web.pages.dashboard  # noqa: F401 — registers @ui.page('/')
import web.pages.calculate  # noqa: F401 — registers @ui.page('/calculate')
import web.pages.result     # noqa: F401 — registers @ui.page('/result/{calc_id}')
import web.pages.editor     # noqa: F401 — registers @ui.page('/editor')
import web.pages.tools          # noqa: F401 — registers @ui.page('/tools')
import web.pages.tools_barrowman  # noqa: F401 — registers @ui.page('/tools/barrowman')
import web.pages.tools_mass       # noqa: F401 — registers @ui.page('/tools/mass')
import web.pages.tools_engine     # noqa: F401 — registers @ui.page('/tools/engine')
import web.service_ui.pages        # noqa: F401 — registers @ui.page('/jobs') + @ui.page('/jobs/{job_id}')

from web.service_ui import config as _service_config

def _find_free_port(start: int, attempts: int = 10) -> int:
    import socket
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port
    raise OSError(f'No free port found in range {start}–{start + attempts - 1}')


@app.on_shutdown
def _terminate_child_processes():
    proc = calc_service._current_proc
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


def _ui_host() -> str:
    """Host for the NiceGUI frontend, restricted to loopback or the tailnet (design §13-3).

    NiceGUI defaults to 0.0.0.0, which exposed the GUI on the university LAN. Default to loopback
    (use case ②); set WB_UI_HOST to the tailscale0 address to serve the tailnet (use case ③).
    Anything else (0.0.0.0, a LAN address) is refused rather than silently exposed — same policy
    as the compute service (service.serve.validate_bind_host)."""
    return validate_bind_host(os.environ.get("WB_UI_HOST", "127.0.0.1"))


def _start_compute_service():
    """Spawn+supervise the local compute service for the new /jobs UI (use case ②).

    The service is a separate, detached process so a GUI crash never kills a running job
    (design §4.3); we deliberately do NOT terminate it on GUI shutdown. A remote WB_SERVICE_URL
    (③) is owned by systemd and this is a no-op. Failure here is non-fatal: the /jobs page will
    surface 'service unreachable' rather than blocking the rest of the GUI."""
    try:
        _service_config.ensure_service()
    except Exception as exc:  # noqa: BLE001
        print(f'Compute service not started ({exc}); the Jobs page will be unavailable.')


if __name__ in {'__main__', '__mp_main__'}:
    init_db()
    _start_compute_service()
    port = _find_free_port(8080)
    if port != 8080:
        print(f'Port 8080 is in use, using port {port} instead.')
    ui.run(
        title='ForRocket Workbench',
        host=_ui_host(),
        port=port,
        reload=False,
        dark=True,
        favicon='pic/forrocket_icon.ico',
    )
