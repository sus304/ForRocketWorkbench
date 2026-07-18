from __future__ import annotations

from nicegui import ui

_MODE_COLORS = {
    'trajectory': 'blue',
    'area': 'green',
    'montecarlo': 'purple',
    'sensitivity': 'orange',
}
_STATUS_COLORS = {
    'completed': 'positive',
    'running': 'primary',
    'cancelling': 'warning',
    'cancelled': 'warning',
    'failed': 'negative',
    'idle': 'grey',
}


def build_header(active: str = ''):
    with ui.header(elevated=True).classes('bg-blue-grey-10 text-white q-px-md items-center'):
        ui.label('ForRocket Workbench').classes('text-h6 text-weight-bold')
        ui.space()
        pages = [('Dashboard', '/'), ('Calculate', '/calculate'), ('Jobs', '/jobs')]
        for label, path in pages:
            is_active = active == label
            (ui.button(label, on_click=lambda p=path: ui.navigate.to(p))
             .props('flat')
             .classes('text-white text-weight-bold' if is_active else 'text-white text-weight-regular'))
        is_tools = active == 'Tools'
        with (ui.dropdown_button('Tools', auto_close=True)
              .props('flat')
              .classes('text-white text-weight-bold' if is_tools else 'text-white text-weight-regular')):
            ui.item('🧮  Barrowman CP',       on_click=lambda: ui.navigate.to('/tools/barrowman'))
            ui.item('⚖️  Mass & Inertia',     on_click=lambda: ui.navigate.to('/tools/mass'))
            ui.item('🔥  Hybrid Engine',      on_click=lambda: ui.navigate.to('/tools/engine'))


def mode_badge(mode: str) -> str:
    color = _MODE_COLORS.get(mode, 'grey')
    return f'<span class="q-badge bg-{color}">{mode.upper()}</span>'


def status_badge(status: str) -> str:
    color = _STATUS_COLORS.get(status, 'grey')
    icons = {
        'completed': '✓', 'running': '⟳', 'cancelling': '⟳',
        'cancelled': '⊘', 'failed': '✗', 'idle': '–',
    }
    icon = icons.get(status, '–')
    return f'<span class="q-badge bg-{color}">{icon} {status}</span>'
