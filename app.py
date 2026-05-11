from nicegui import ui

from web.db.database import init_db
import web.pages.dashboard  # noqa: F401 — registers @ui.page('/')
import web.pages.calculate  # noqa: F401 — registers @ui.page('/calculate')
import web.pages.result     # noqa: F401 — registers @ui.page('/result/{calc_id}')
import web.pages.editor     # noqa: F401 — registers @ui.page('/editor')
import web.pages.tools          # noqa: F401 — registers @ui.page('/tools')
import web.pages.tools_barrowman  # noqa: F401 — registers @ui.page('/tools/barrowman')
import web.pages.tools_mass       # noqa: F401 — registers @ui.page('/tools/mass')
import web.pages.tools_engine     # noqa: F401 — registers @ui.page('/tools/engine')

if __name__ in {'__main__', '__mp_main__'}:
    init_db()
    ui.run(
        title='ForRocket Workbench',
        port=8080,
        reload=False,
        dark=True,
        favicon='pic/forrocket_icon.ico',
    )
