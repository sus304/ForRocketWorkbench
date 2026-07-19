"""Service-native GUI routes (design §5, §11.5, Phase 9).

Two NiceGUI pages over the compute service HTTP API, coexisting with the legacy single-job
pages:

- `/jobs`      — submit a run (packs the local project's input closure and uploads it) and a
                 live-polling job queue with per-job status, MC progress and cancel.
- `/jobs/{id}` — one job's detail: live status/progress, cancel, and — once completed — the
                 full result render read straight off the service work_dir (use case ②).

The GUI holds no calculation state: everything comes from the service via ServiceClient, so a
job survives a browser reload or a GUI restart. Pure helpers (time/ETA formatting, row shaping)
live at module top and are unit-tested; the page bodies are covered by manual/e2e verification.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

from nicegui import ui

from web.service_ui.layout import service_header
from web.service_ui import config, render
# NOTE: web.services.project_service (which pulls in web.db) is imported lazily inside the
# submit-form branch only. The VM-resident server disables that form (config.submit_enabled()
# is False), so app_server never imports the DB layer or opens workbench.db (design §3.1.2).

_MODES = ['trajectory', 'area', 'montecarlo', 'sensitivity']
_ACTIVE_STATUSES = {'preparing', 'queued', 'running'}
_STATUS_COLOR = {
    'preparing': 'grey', 'queued': 'grey', 'running': 'primary',
    'completed': 'positive', 'failed': 'negative', 'cancelled': 'warning',
}


# ── Pure helpers (unit-tested) ────────────────────────────────────────────────

def fmt_hms(seconds: float) -> str:
    """Format a duration as H:MM:SS (or M:SS under an hour)."""
    if seconds is None or seconds < 0:
        return '—'
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f'{h}:{m:02d}:{sec:02d}' if h else f'{m}:{sec:02d}'


def parse_iso(value: Optional[str]) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None


def elapsed_seconds(started_at: Optional[str], now: Optional[datetime.datetime] = None) -> Optional[float]:
    start = parse_iso(started_at)
    if start is None:
        return None
    now = now or datetime.datetime.now()
    return max(0.0, (now - start).total_seconds())


def eta_seconds(done: int, total: int, elapsed: Optional[float]) -> Optional[float]:
    """Linear-rate estimate of remaining seconds, or None if not yet estimable."""
    if not elapsed or elapsed <= 0 or done <= 0 or total <= 0 or done >= total:
        return None
    return (total - done) * (elapsed / done)


def progress_fraction(progress: Optional[dict]) -> Optional[float]:
    if not progress:
        return None
    total = progress.get('total') or 0
    if total <= 0:
        return None
    return min(1.0, (progress.get('done') or 0) / total)


# ── Client access ─────────────────────────────────────────────────────────────

_client = None


def client():
    global _client
    if _client is None:
        _client = config.get_client()
    return _client


# ── /jobs ─────────────────────────────────────────────────────────────────────

@ui.page('/jobs')
def jobs_page():
    service_header(active='Jobs')

    with ui.column().classes('q-pa-md w-full'):
        ui.label('Compute Jobs').classes('text-h6 q-mb-sm')

        # ── Submit form ───────────────────────────────────────────────────────
        # On the VM-resident server the form is disabled: the browser cannot reach the operator's
        # local projects/, so ③ submits via `wb submit` (design §3.3 / review Y12). Skipping it
        # also avoids the projects-DB dependency on the server, which never runs init_db.
        if not config.submit_enabled():
            with ui.card().classes('w-full q-mb-md'):
                ui.label('Submit a run').classes('text-subtitle2 q-mb-xs')
                ui.label('Submit from the CLI: `wb submit <project> <mode>`. '
                         'Browser upload arrives with the UI refresh.') \
                    .classes('text-caption text-grey')
        else:
            from web.services.project_service import scan_projects, projects_dir, get_model_id
            projects = scan_projects()
            with ui.card().classes('w-full q-mb-md'):
                ui.label('Submit a run').classes('text-subtitle2 q-mb-sm')
                with ui.row().classes('items-center q-gutter-md w-full'):
                    project_select = ui.select(projects, label='Project',
                                               value=projects[0] if projects else None) \
                        .props('dense outlined').style('min-width:220px')
                    mode_select = ui.select(_MODES, label='Mode', value='trajectory') \
                        .props('dense outlined').style('min-width:160px')
                    max_thread = ui.checkbox('Max threads (-X)')
                    submit_btn = ui.button('Submit', icon='send').props('color=primary')

                def _submit():
                    proj = project_select.value
                    mode = mode_select.value
                    if not proj:
                        ui.notify('Select a project first.', type='warning')
                        return
                    project_dir = projects_dir() / proj
                    try:
                        res = client().submit(project_dir, mode,
                                              model_name=get_model_id(proj),
                                              use_max_thread=max_thread.value)
                    except Exception as exc:  # service unreachable / upload rejected
                        ui.notify(f'Submit failed: {exc}', type='negative', multi_line=True)
                        return
                    ui.notify(f'Job #{res["id"]} queued ({mode}).', type='positive')
                    jobs_list.refresh()

                submit_btn.on_click(lambda: _submit())

        # ── Health strip ──────────────────────────────────────────────────────
        @ui.refreshable
        def health_strip():
            try:
                h = client().health()
            except Exception:
                ui.label('⚠ Service unreachable').classes('text-negative text-caption')
                return
            free = h.get('disk_free_bytes')
            free_gb = f'{free / 1e9:.1f} GB free' if free else '—'
            running = h.get('running_job')
            worker = 'alive' if h.get('worker_alive') else 'down'
            run_txt = f'running #{running}' if running else 'idle'
            stall = h.get('running_stall_seconds')
            stall_txt = f' · stalled {fmt_hms(stall)}' if stall and stall > 300 else ''
            with ui.row().classes('items-center q-gutter-sm text-caption text-grey'):
                ui.label(f'Worker: {worker} · {run_txt} · disk {free_gb}{stall_txt}')

        health_strip()

        # ── Jobs list ─────────────────────────────────────────────────────────
        @ui.refreshable
        def jobs_list():
            try:
                jobs = client().list_jobs()
            except Exception as exc:
                ui.label(f'Cannot load jobs: {exc}').classes('text-negative')
                return
            if not jobs:
                ui.label('No jobs yet.').classes('text-caption text-grey')
                return
            with ui.list().props('bordered separator').classes('w-full'):
                for job in jobs:
                    _job_row(job)

        jobs_list()

        def _tick():
            health_strip.refresh()
            jobs_list.refresh()

        ui.timer(2.0, _tick)


def _job_row(job: dict):
    jid = job['id']
    status = job['status']
    color = _STATUS_COLOR.get(status, 'grey')
    prog = job.get('progress')
    frac = progress_fraction(prog)

    # Explicit action buttons (view / cancel) rather than a clickable row, so a Cancel click
    # cannot also trigger navigation via event bubbling.
    with ui.item():
        with ui.item_section().props('avatar'):
            ui.badge(str(jid)).props(f'color={color}')
        with ui.item_section():
            ui.item_label(f'{job["mode"]}  ·  {job.get("model_name") or "—"}')
            sub = status
            if frac is not None and prog:
                sub = f'{status} · {prog["done"]:,}/{prog["total"]:,} ({frac:.0%})'
            elif job.get('error_message') and status == 'failed':
                sub = f'{status} · {job["error_message"].splitlines()[0][:80]}'
            ui.item_label(sub).props('caption')
        with ui.item_section().props('side'):
            with ui.row().classes('q-gutter-xs'):
                ui.button(icon='open_in_new', on_click=lambda j=jid: ui.navigate.to(f'/jobs/{j}')) \
                    .props('flat dense color=primary').tooltip('Open')
                if status in _ACTIVE_STATUSES:
                    ui.button(icon='cancel', on_click=lambda j=jid: _cancel(j)) \
                        .props('flat dense color=negative').tooltip('Cancel')


def _cancel(job_id: int):
    try:
        client().cancel(job_id)
        ui.notify(f'Job #{job_id} cancel requested.', type='info')
    except Exception as exc:
        ui.notify(f'Cancel failed: {exc}', type='negative')


# ── /jobs/{job_id} ──────────────────────────────────────────────────────────

@ui.page('/jobs/{job_id}')
def job_detail_page(job_id: int):
    service_header(active='Jobs')

    with ui.column().classes('q-pa-md w-full'):
        with ui.row().classes('items-center q-mb-md'):
            ui.button('← Jobs', on_click=lambda: ui.navigate.to('/jobs')).props('flat')
            ui.label(f'Job #{job_id}').classes('text-h6 q-ml-sm')

        status_area = ui.column().classes('w-full')
        result_area = ui.column().classes('w-full q-mt-md')

        # rendered_for guards the (one-shot) result render against the polling timer.
        state = {'rendered_for': None, 'stop': False}

        def _refresh():
            if state['stop']:
                return
            try:
                job = client().status(job_id)
            except Exception as exc:
                status_area.clear()
                with status_area:
                    ui.label(f'Cannot reach service: {exc}').classes('text-negative')
                return

            status_area.clear()
            with status_area:
                _render_status(job)

            terminal = job['status'] in ('completed', 'failed', 'cancelled')
            if job['status'] == 'completed' and state['rendered_for'] != job_id:
                state['rendered_for'] = job_id
                result_area.clear()
                with result_area:
                    render.render_result(client(), job_id, job['mode'], job_id)
            if terminal:
                state['stop'] = True  # stop polling; page is static now

        _refresh()
        ui.timer(1.5, _refresh)


def _render_status(job: dict):
    status = job['status']
    color = _STATUS_COLOR.get(status, 'grey')

    with ui.card().classes('w-full'):
        with ui.row().classes('items-center q-gutter-sm'):
            ui.badge(status).props(f'color={color}')
            ui.label(f'{job["mode"]}  ·  {job.get("model_name") or "—"}').classes('text-body2')
            ui.space()
            if job.get('capability', {}).get('can_cancel'):
                ui.button('Cancel', icon='cancel',
                          on_click=lambda: _cancel(job['id'])).props('flat dense color=negative')

        with ui.grid(columns=3).classes('w-full q-mt-sm'):
            for label, value in [
                ('Enqueued', job.get('enqueued_at') or '—'),
                ('Started', job.get('started_at') or '—'),
                ('Finished', job.get('finished_at') or '—'),
            ]:
                with ui.column().classes('q-pa-xs'):
                    ui.label(label).classes('text-caption text-grey')
                    ui.label(str(value)).classes('text-body2')

        prog = job.get('progress')
        frac = progress_fraction(prog)
        if frac is not None and prog:
            elapsed = elapsed_seconds(job.get('started_at'))
            eta = eta_seconds(prog['done'], prog['total'], elapsed)
            txt = (f'{prog["done"]:,} / {prog["total"]:,} cases ({frac:.1%})'
                   f' · elapsed {fmt_hms(elapsed)}')
            if eta is not None:
                txt += f' · remaining ~{fmt_hms(eta)}'
            ui.label(txt).classes('text-caption text-grey q-mt-sm')
            ui.linear_progress(value=frac).props('instant-feedback color=primary')
        elif status == 'running':
            ui.label('Running…').classes('text-caption text-grey q-mt-sm')
            ui.linear_progress(value=None).props('instant-feedback color=primary')

        if status == 'failed' and job.get('error_message'):
            ui.separator().classes('q-my-sm')
            ui.label(job['error_message']).classes('text-caption').style(
                'white-space:pre-wrap;word-break:break-all;font-family:monospace')

        if job.get('work_dir'):
            ui.label(job['work_dir']).classes('text-caption text-grey q-mt-xs')
