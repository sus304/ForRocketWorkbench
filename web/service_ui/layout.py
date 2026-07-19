"""Header for the service UI (use cases ②/③).

Separate from web.pages.shared.build_header, which links to the legacy pages (Dashboard `/`,
Calculate `/calculate`, Tools `/tools/*`). Those routes are not registered by app_server (③),
so the legacy header's links 404 there. The service UI is independent (design §3.1), so it gets
its own minimal header that only points at routes this UI actually serves.
"""
from __future__ import annotations

from nicegui import ui


def service_header(active: str = "") -> None:
    with ui.header(elevated=True).classes("bg-blue-grey-10 text-white q-px-md items-center"):
        ui.button("ForRocket Workbench", on_click=lambda: ui.navigate.to("/jobs")) \
            .props("flat no-caps").classes("text-h6 text-weight-bold text-white")
        ui.space()
        for label, path in (("Projects", "/projects"), ("Jobs", "/jobs")):
            ui.button(label, on_click=lambda p=path: ui.navigate.to(p)).props("flat") \
                .classes("text-white " +
                         ("text-weight-bold" if active == label else "text-weight-regular"))
