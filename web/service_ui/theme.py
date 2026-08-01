"""Shared visual theme for the service UI (single source of truth for colour/shape).

Every service-UI page gets its look from here rather than from per-element Quasar colour classes,
so a palette change is one edit. `apply_theme()` does two things:

1. `ui.colors(...)` rebinds Quasar's brand palette (`primary`/`positive`/`negative`/`warning`/…),
   which is what the existing code already asks for by name — e.g. `pages._STATUS_COLOR` maps a job
   status to 'primary'/'positive'/'negative'. Those call sites keep working and simply pick up the
   new hues.
2. A stylesheet of `--wb-*` custom properties plus a small set of Quasar overrides (card, list,
   header, field, button) that Quasar's own defaults don't let us reach through props.

Design direction: "modern SaaS" — a neutral near-black ground, one indigo accent, generous radius
and spacing, separation by gap rather than by rule. Semantic colours (running/ok/warning/error) are
deliberately distinct from the accent so state never competes with brand.

The UI runs `dark=True` (see app_server.main), so only the dark palette is defined; there is no
light theme to keep in sync.

Version note: the dev box runs NiceGUI 2.24.2 and the compute server 3.x. Everything here uses API
that exists in both (`ui.colors`, `ui.add_css`), with a signature probe for `dark_page` and a
`add_head_html` fallback for `add_css`, mirroring how `pages._render_viewer` guards `ui.html`.
"""
from __future__ import annotations

import inspect

from nicegui import ui

# ── Palette ──────────────────────────────────────────────────────────────────
# Named once here; the CSS below and the Quasar brand binding both read these.
BG          = '#0e0f13'   # page ground
SURFACE     = '#16181e'   # card / list panel
SURFACE_2   = '#1b1e26'   # raised: menus, dialogs, hovered rows
LINE        = '#262a34'   # borders
INK         = '#eceef3'   # primary text
INK_DIM     = '#878d9a'   # captions, secondary text

ACCENT      = '#7b8cf7'   # the one brand hue (Quasar `primary`)
ACCENT_SOFT = '#b9c2ff'   # hover / gradient end

OK          = '#46b881'   # completed          (Quasar `positive`)
WARN        = '#d69f3c'   # cancelled          (Quasar `warning`)
ERR         = '#e4635e'   # failed             (Quasar `negative`)
INFO        = '#5aa9d6'   # informational      (Quasar `info`)

RADIUS      = '12px'      # cards, list rows
RADIUS_SM   = '7px'       # fields, buttons, badges

_CSS = f"""
:root {{
  --wb-bg: {BG};
  --wb-surface: {SURFACE};
  --wb-surface-2: {SURFACE_2};
  --wb-line: {LINE};
  --wb-ink: {INK};
  --wb-ink-dim: {INK_DIM};
  --wb-accent: {ACCENT};
  --wb-accent-soft: {ACCENT_SOFT};
  --wb-ok: {OK};
  --wb-warn: {WARN};
  --wb-err: {ERR};
  --wb-radius: {RADIUS};
  --wb-radius-sm: {RADIUS_SM};
}}

/* Ground and base type. Quasar paints the page from `dark_page`, set via ui.colors below; this
   only fixes the text colour and smoothing. */
body.body--dark {{
  color: var(--wb-ink);
  -webkit-font-smoothing: antialiased;
}}

/* Digits that sit in columns (progress counts, elapsed/ETA, sizes) must line up across the 2 s
   refresh, or the row visibly jitters as the numbers change width. */
.body--dark .text-caption,
.body--dark .q-item__label--caption,
.body--dark .q-badge {{
  font-variant-numeric: tabular-nums;
}}

/* ── Card ───────────────────────────────────────────────────────────────────
   Quasar's dark card is a drop-shadowed box with a bright 28%-white border. Replace both with a
   flat surface and a hairline, and open up the radius. `body.body--dark` (0,2,1) outranks
   Quasar's own `.q-card--dark` (0,1,0), so no !important is needed. */
body.body--dark .q-card {{
  background: var(--wb-surface);
  border: 1px solid var(--wb-line);
  border-radius: var(--wb-radius);
  box-shadow: 0 1px 2px rgba(0, 0, 0, .4);
}}

/* ── List ───────────────────────────────────────────────────────────────────
   `ui.list().props('bordered separator')` renders hairline-separated rows; keep the separators but
   round the container and give rows a hover affordance (they are clickable links). */
body.body--dark .q-list--bordered {{
  border: 1px solid var(--wb-line);
  border-radius: var(--wb-radius);
  overflow: hidden;
  background: var(--wb-surface);
}}
body.body--dark .q-list--separator > .q-item-type + .q-item-type {{
  border-top-color: var(--wb-line);
}}
body.body--dark .q-item {{
  transition: background-color 120ms ease;
}}
body.body--dark .q-item:hover {{
  background: var(--wb-surface-2);
}}

/* A card nested inside another card, for a recessed sub-panel (e.g. the sensitivity editor's
   coupled-effects group). Reads as slightly inset rather than as a second floating card. */
body.body--dark .q-card.wb-subpanel {{
  background: var(--wb-bg);
  border: 1px solid var(--wb-line);
  border-radius: var(--wb-radius-sm);
  box-shadow: none;
}}

/* ── Header ─────────────────────────────────────────────────────────────────
   Flat, same ground as the page, separated by a hairline instead of an elevation shadow. */
body.body--dark .q-header.wb-header {{
  background: var(--wb-bg);
  border-bottom: 1px solid var(--wb-line);
  box-shadow: none;
}}
.wb-brand {{
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -.01em;
  color: var(--wb-ink);
}}
/* Nav items are pills: quiet by default, filled when active. */
.wb-nav .q-btn {{
  border-radius: var(--wb-radius-sm);
  color: var(--wb-ink-dim);
  font-weight: 500;
}}
.wb-nav .q-btn:hover {{
  color: var(--wb-ink);
}}
.wb-nav .wb-nav-active {{
  color: var(--wb-ink);
  font-weight: 650;
  background: var(--wb-surface-2);
}}

/* Vertical nav entries (the config editor's file list). Quiet by default, and the selected file
   gets a filled row — the same "quiet / filled" language as the header nav. */
body.body--dark .q-btn.wb-side-item {{
  color: var(--wb-ink-dim);
}}
body.body--dark .q-btn.wb-side-item:hover {{
  color: var(--wb-ink);
}}
body.body--dark .q-btn.wb-selected {{
  background: var(--wb-surface-2);
}}

/* ── Buttons ────────────────────────────────────────────────────────────────
   Quasar shouts button labels in uppercase; sentence case is the modern-SaaS default. Applied
   globally so individual call sites don't each need `no-caps`. */
.body--dark .q-btn {{
  text-transform: none;
  letter-spacing: 0;
  border-radius: var(--wb-radius-sm);
}}

/* ── Fields ─────────────────────────────────────────────────────────────────
   Calm the borders of the filter row and the config editor's many inputs. */
body.body--dark .q-field--outlined .q-field__control:before {{
  border-color: var(--wb-line);
}}
/* The filter row (`props('dense clearable')`) uses Quasar's underline variant, whose default rule
   is a faint white that all but disappears on this ground. Give it the border token, and the
   accent on focus. */
body.body--dark .q-field--standard .q-field__control:before {{
  border-bottom-color: var(--wb-line);
}}
body.body--dark .q-field--standard .q-field__control:hover:before {{
  border-bottom-color: var(--wb-ink-dim);
}}
body.body--dark .q-field__label {{
  color: var(--wb-ink-dim);
}}
body.body--dark .q-field__native,
body.body--dark .q-field__prefix,
body.body--dark .q-field__suffix {{
  color: var(--wb-ink);
}}

/* ── Menus and dialogs ──────────────────────────────────────────────────── */
body.body--dark .q-menu,
body.body--dark .q-dialog__inner > .q-card {{
  background: var(--wb-surface-2);
  border: 1px solid var(--wb-line);
  border-radius: var(--wb-radius);
}}

/* ── Progress ───────────────────────────────────────────────────────────────
   A pill track with a gradient fill, so a bar at 3 % is still visible. */
body.body--dark .q-linear-progress {{
  border-radius: 999px;
  overflow: hidden;
  height: 8px;
}}
body.body--dark .q-linear-progress__track {{
  background: var(--wb-line);
  opacity: 1;
}}
body.body--dark .q-linear-progress__model {{
  background: linear-gradient(90deg, var(--wb-accent), var(--wb-accent-soft));
}}

/* ── Focus ──────────────────────────────────────────────────────────────────
   Keyboard focus must stay visible once the default outline is restyled away. */
body.body--dark :focus-visible {{
  outline: 2px solid var(--wb-accent);
  outline-offset: 2px;
}}

/* ── Scrollbar ──────────────────────────────────────────────────────────── */
body.body--dark ::-webkit-scrollbar {{
  width: 10px;
  height: 10px;
}}
body.body--dark ::-webkit-scrollbar-thumb {{
  background: var(--wb-line);
  border-radius: 999px;
}}
body.body--dark ::-webkit-scrollbar-thumb:hover {{
  background: var(--wb-ink-dim);
}}
body.body--dark ::-webkit-scrollbar-track {{
  background: transparent;
}}

@media (prefers-reduced-motion: reduce) {{
  body.body--dark .q-item {{ transition: none; }}
}}
"""


def apply_theme() -> None:
    """Bind the Quasar brand palette and inject the theme stylesheet.

    Call once per page, before building the page body — `service_header()` does this for every
    service-UI route, and `app_server.login_page` calls it directly (it has no header).
    """
    colors = {
        'primary': ACCENT,
        'secondary': INK_DIM,
        'accent': ACCENT_SOFT,
        'positive': OK,
        'negative': ERR,
        'warning': WARN,
        'info': INFO,
        'dark': SURFACE,
    }
    # `dark_page` paints the page ground. It exists in both NiceGUI generations we run on, but
    # probe rather than assume: an unexpected kwarg raises and would break startup outright.
    if 'dark_page' in inspect.signature(ui.colors.__init__).parameters:
        colors['dark_page'] = BG
    ui.colors(**colors)

    if hasattr(ui, 'add_css'):
        ui.add_css(_CSS)
    else:  # pragma: no cover - older NiceGUI without ui.add_css
        ui.add_head_html(f'<style>{_CSS}</style>')
