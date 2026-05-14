import subprocess

from nicegui import app, ui

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


if __name__ in {'__main__', '__mp_main__'}:
    init_db()
    port = _find_free_port(8080)
    if port != 8080:
        print(f'Port 8080 is in use, using port {port} instead.')
    ui.run(
        title='ForRocket Workbench',
        port=port,
        reload=False,
        dark=True,
        favicon='pic/forrocket_icon.ico',
    )
