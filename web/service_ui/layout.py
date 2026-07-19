"""Header for the service UI (use cases ②/③).

Minimal header linking only to routes this UI serves (Projects, Jobs, Tools). Replaces the
legacy build_header, which pointed at now-removed pages (Dashboard/Calculate); the service UI is
independent (design §3.1).
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
        with ui.dropdown_button("Tools", auto_close=True).props("flat") \
                .classes("text-white " +
                         ("text-weight-bold" if active == "Tools" else "text-weight-regular")):
            ui.item("🧮 Barrowman CP", on_click=lambda: ui.navigate.to("/tools/barrowman"))
            ui.item("⚖️ Mass & Inertia", on_click=lambda: ui.navigate.to("/tools/mass"))
            ui.item("🔥 Hybrid Engine", on_click=lambda: ui.navigate.to("/tools/engine"))
