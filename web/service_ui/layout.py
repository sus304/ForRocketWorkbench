"""Header for the service UI (use cases ②/③).

Minimal header linking only to routes this UI serves (Projects, Jobs, Tools). Replaces the
legacy build_header, which pointed at now-removed pages (Dashboard/Calculate); the service UI is
independent (design §3.1).

`service_header()` is also the hook that applies the shared theme (`theme.apply_theme()`): every
service-UI page calls it first, so a page picks up the palette by virtue of having a header. The
one page without a header — the login screen — applies the theme itself.
"""
from __future__ import annotations

from nicegui import ui

from web.service_ui import theme

# Quasar groups identical toasts and shows a count badge when they stack (e.g. Save pressed
# repeatedly). Its default badge is red, which reads as an error even on a positive "Saved." — so
# tint the badge to match the toast type. Passed straight through to Quasar's Notify (badgeColor).
_BADGE_COLOR = {'positive': 'green-6', 'warning': 'orange-8', 'info': 'blue-7', 'negative': 'red-7'}


def notify(message, *, type=None, **kwargs):  # noqa: A002 - mirrors ui.notify's `type` param
    """ui.notify with a stacked-count badge colour matching the notification type."""
    kwargs.setdefault('badgeColor', _BADGE_COLOR.get(type, 'grey-7'))
    ui.notify(message, type=type, **kwargs)


# Tools menu entries: (material icon, label, route). Icons replace the former emoji so the menu
# matches the icon set used everywhere else in the UI (Quasar material icons).
_TOOLS = (
    ("straighten", "Barrowman CP", "/tools/barrowman"),
    ("scale", "Mass & Inertia", "/tools/mass"),
    ("local_fire_department", "Hybrid Engine", "/tools/engine"),
)


def _nav_classes(active: str, label: str) -> str:
    """Pill nav item; the active route gets the filled variant (see theme `.wb-nav-active`)."""
    return "wb-nav-active" if active == label else ""


def service_header(active: str = "") -> None:
    """Top navigation, and the one place the theme is applied for a service-UI page."""
    theme.apply_theme()

    # Flat rather than elevated: the theme separates the header with a hairline instead of a
    # shadow, and an elevation shadow over the near-black ground reads as a smudge.
    with ui.header(elevated=False).classes("wb-header q-px-lg items-center"):
        # color=None on every header button: NiceGUI defaults to `primary`, which makes Quasar add
        # `.text-primary` — and Quasar's colour utilities carry !important, so the theme's calmer
        # nav colours would lose the cascade and the whole header would render in the accent hue.
        # Without a colour prop the label simply inherits, and `.wb-brand` / `.wb-nav` decide.
        ui.button("ForRocket Workbench", on_click=lambda: ui.navigate.to("/jobs"), color=None) \
            .props("flat no-caps dense").classes("wb-brand q-mr-md")
        with ui.row().classes("wb-nav items-center q-gutter-xs"):
            for label, path in (("Projects", "/projects"), ("Jobs", "/jobs")):
                ui.button(label, on_click=lambda p=path: ui.navigate.to(p), color=None) \
                    .props("flat dense").classes(_nav_classes(active, label))
            # Filesystem results browser — only when result roots are configured (WB_RESULT_ROOTS).
            from web.service_ui import config as _cfg
            if _cfg.result_roots():
                ui.button("Results", on_click=lambda: ui.navigate.to("/results"), color=None) \
                    .props("flat dense").classes(_nav_classes(active, "Results"))
            with ui.dropdown_button("Tools", auto_close=True, color=None).props("flat dense") \
                    .classes(_nav_classes(active, "Tools")):
                for icon, label, path in _TOOLS:
                    with ui.item(on_click=lambda p=path: ui.navigate.to(p)):
                        with ui.item_section().props("avatar"):
                            ui.icon(icon).classes("text-grey-5")
                        with ui.item_section():
                            ui.label(label)
        ui.space()
