"""Header for the service UI (use cases ②/③).

Minimal header linking only to routes this UI serves (Projects, Jobs, Tools). Replaces the
legacy build_header, which pointed at now-removed pages (Dashboard/Calculate); the service UI is
independent (design §3.1).
"""
from __future__ import annotations

from nicegui import ui

# Quasar groups identical toasts and shows a count badge when they stack (e.g. Save pressed
# repeatedly). Its default badge is red, which reads as an error even on a positive "Saved." — so
# tint the badge to match the toast type. Passed straight through to Quasar's Notify (badgeColor).
_BADGE_COLOR = {'positive': 'green-6', 'warning': 'orange-8', 'info': 'blue-7', 'negative': 'red-7'}


def notify(message, *, type=None, **kwargs):  # noqa: A002 - mirrors ui.notify's `type` param
    """ui.notify with a stacked-count badge colour matching the notification type."""
    kwargs.setdefault('badgeColor', _BADGE_COLOR.get(type, 'grey-7'))
    ui.notify(message, type=type, **kwargs)


def service_header(active: str = "") -> None:
    with ui.header(elevated=True).classes("bg-blue-grey-10 text-white q-px-md items-center"):
        ui.button("ForRocket Workbench", on_click=lambda: ui.navigate.to("/jobs")) \
            .props("flat no-caps").classes("text-h6 text-weight-bold text-white")
        ui.space()
        for label, path in (("Projects", "/projects"), ("Jobs", "/jobs")):
            ui.button(label, on_click=lambda p=path: ui.navigate.to(p)).props("flat") \
                .classes("text-white " +
                         ("text-weight-bold" if active == label else "text-weight-regular"))
        # Filesystem results browser — only when result roots are configured (WB_RESULT_ROOTS).
        from web.service_ui import config as _cfg
        if _cfg.result_roots():
            ui.button("Results", on_click=lambda: ui.navigate.to("/results")).props("flat") \
                .classes("text-white " +
                         ("text-weight-bold" if active == "Results" else "text-weight-regular"))
        with ui.dropdown_button("Tools", auto_close=True).props("flat") \
                .classes("text-white " +
                         ("text-weight-bold" if active == "Tools" else "text-weight-regular")):
            ui.item("🧮 Barrowman CP", on_click=lambda: ui.navigate.to("/tools/barrowman"))
            ui.item("⚖️ Mass & Inertia", on_click=lambda: ui.navigate.to("/tools/mass"))
            ui.item("🔥 Hybrid Engine", on_click=lambda: ui.navigate.to("/tools/engine"))
