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

from web.service_ui.layout import notify, service_header
from web.service_ui import config, render
# Runs are submitted from the Projects page (projects_ui) now; this module has no dependency on
# the retired projects DB / legacy services.

_MODES = ['trajectory', 'area', 'montecarlo', 'sensitivity']
_STATUSES = ['queued', 'running', 'completed', 'failed', 'cancelled']
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


def filter_jobs(jobs: list, query: str = '', mode: str = 'all', status: str = 'all',
                sort: str = 'newest') -> list:
    """Filter the job list by mode, status and a free-text query (id/model_name/project/memo),
    then order it. `sort` is 'newest' (id desc) or 'oldest' (id asc). Pure/testable for the /jobs
    search + filters (design §6 / review R-O)."""
    out = jobs
    if mode and mode != 'all':
        out = [j for j in out if j.get('mode') == mode]
    if status and status != 'all':
        out = [j for j in out if j.get('status') == status]
    q = (query or '').strip().lower()
    if q:
        def _hay(j):
            return ' '.join(str(j.get(k, '')) for k in ('id', 'model_name', 'project', 'memo')).lower()
        out = [j for j in out if q in _hay(j)]
    return sorted(out, key=lambda j: j.get('id', 0), reverse=(sort != 'oldest'))


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

        # ── Submit: runs are submitted from the Projects page ─────────────────
        # Projects live server-side now (UI-refresh model); submission happens per project on
        # /projects (select + Submit). The old local-projects form / wb-only note are gone.
        with ui.card().classes('w-full q-mb-md'):
            ui.label('Submit a run').classes('text-subtitle2 q-mb-xs')
            with ui.row().classes('items-center q-gutter-sm'):
                ui.label('Runs are submitted from a stored project.').classes('text-caption text-grey q-my-auto')
                ui.button('Go to Projects', icon='folder',
                          on_click=lambda: ui.navigate.to('/projects')).props('dense flat color=primary')

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

        # ── Jobs list (search + mode/status filters + sort) ───────────────────
        flt = {'q': '', 'mode': 'all', 'status': 'all', 'sort': 'newest'}

        def _setter(key):
            def _apply(e):
                flt[key] = e.value if e.value is not None else ('all' if key != 'sort' else 'newest')
                jobs_list.refresh()
            return _apply

        with ui.row().classes('items-center q-gutter-sm q-mt-xs'):
            ui.input('Search', placeholder='model / project / memo') \
                .props('dense clearable').style('min-width:220px').on_value_change(_setter('q'))
            ui.select(['all'] + _MODES, value='all', label='Mode') \
                .props('dense').style('min-width:130px').on_value_change(_setter('mode'))
            ui.select(['all'] + _STATUSES, value='all', label='Status') \
                .props('dense').style('min-width:130px').on_value_change(_setter('status'))
            ui.select({'newest': 'Newest first', 'oldest': 'Oldest first'},
                      value='newest', label='Sort') \
                .props('dense').style('min-width:140px').on_value_change(_setter('sort'))

        # A single confirm dialog at PAGE scope (outside the refreshable list). Row buttons live
        # inside jobs_list, which the 2s timer rebuilds — a dialog created from a row would lose its
        # parent slot on refresh ("parent slot has been deleted"). This one persists; rows just set
        # its message + callback and open it.
        confirm = {'cb': None}
        with ui.dialog() as confirm_dlg, ui.card():
            confirm_msg = ui.label('').classes('q-mb-sm')
            with ui.row():
                def _confirm_yes():
                    confirm_dlg.close()
                    if confirm['cb']:
                        confirm['cb']()
                ui.button('Delete', on_click=_confirm_yes).props('color=negative')
                ui.button('Cancel', on_click=confirm_dlg.close).props('flat')

        def ask_confirm(message, cb):
            confirm_msg.set_text(message)
            confirm['cb'] = cb
            confirm_dlg.open()

        @ui.refreshable
        def jobs_list():
            try:
                jobs = filter_jobs(client().list_jobs(), flt['q'], flt['mode'],
                                   flt['status'], flt['sort'])
            except Exception as exc:
                ui.label(f'Cannot load jobs: {exc}').classes('text-negative')
                return
            if not jobs:
                ui.label('No jobs match.').classes('text-caption text-grey')
                return
            with ui.list().props('bordered separator').classes('w-full'):
                for job in jobs:
                    _job_row(job, jobs_list.refresh, ask_confirm)

        jobs_list()

        def _tick():
            health_strip.refresh()
            jobs_list.refresh()

        ui.timer(2.0, _tick)


def _job_row(job: dict, refresh=None, ask_confirm=None):
    jid = job['id']
    status = job['status']
    color = _STATUS_COLOR.get(status, 'grey')
    prog = job.get('progress')
    frac = progress_fraction(prog)

    # Explicit action buttons (view / cancel) rather than a clickable row, so a Cancel click
    # cannot also trigger navigation via event bubbling.
    with ui.item():
        with ui.item_section().props('avatar'):
            # The id badge is a link to the job detail/result page (common UI: click id/name).
            ui.badge(str(jid)).props(f'color={color}') \
                .classes('cursor-pointer').on('click', lambda j=jid: ui.navigate.to(f'/jobs/{j}'))
        with ui.item_section():
            proj = job.get('project')
            head = f'{job["mode"]}  ·  {job.get("model_name") or "—"}'
            if proj:
                head += f'  ·  📁 {proj}'
            ui.link(head, f'/jobs/{jid}').classes('text-body1')
            sub = status
            if frac is not None and prog:
                sub = f'{status} · {prog["done"]:,}/{prog["total"]:,} ({frac:.0%})'
            elif job.get('error_message') and status == 'failed':
                sub = f'{status} · {job["error_message"].splitlines()[0][:80]}'
            ui.item_label(sub).props('caption')

            def _save_memo(e, j=jid):
                try:
                    client().set_memo(j, e.value or '')
                except Exception as exc:
                    notify(f'Memo save failed: {exc}', type='negative')
            ui.input('memo', value=job.get('memo') or '') \
                .props('dense borderless').classes('text-caption') \
                .on('blur', _save_memo).on('keydown.enter', _save_memo)
        with ui.item_section().props('side'):
            with ui.row().classes('q-gutter-xs'):
                ui.button(icon='open_in_new', on_click=lambda j=jid: ui.navigate.to(f'/jobs/{j}')) \
                    .props('flat dense color=primary').tooltip('Open')
                if status in _ACTIVE_STATUSES:
                    ui.button(icon='cancel', on_click=lambda j=jid: _cancel(j)) \
                        .props('flat dense color=negative').tooltip('Cancel')
                else:
                    # Delete is only offered for finished jobs; an active job must be cancelled
                    # first (the API also refuses with 409).
                    ui.button(icon='delete',
                              on_click=lambda j=jid: _delete_job(j, refresh, ask_confirm)) \
                        .props('flat dense color=negative').tooltip('Delete')


def _cancel(job_id: int):
    try:
        client().cancel(job_id)
        notify(f'Job #{job_id} cancel requested.', type='info')
    except Exception as exc:
        notify(f'Cancel failed: {exc}', type='negative')


def _delete_job(job_id: int, refresh=None, ask_confirm=None):
    def _do():
        try:
            client().delete_job(job_id)
            notify(f'Job #{job_id} deleted.', type='warning')
            if refresh:
                refresh()
        except Exception as exc:
            notify(f'Delete failed: {exc}', type='negative', multi_line=True)

    msg = (f'Delete job #{job_id}? Its results/work directory will be removed. '
           'This cannot be undone.')
    if ask_confirm:
        ask_confirm(msg, _do)
    else:  # no shared dialog available → act directly (kept for safety)
        _do()


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


def _render_viewer(src: str, back_to: str) -> None:
    """Full-viewport embedded 3D viewer over a same-origin result manifest base `src`. Iframe-only
    so the viewer's Cesium/WebGL doesn't fight the NiceGUI runtime/layout (survey §10.8). `src`
    must be a same-origin /api/results/ path; the viewer bundle (WB_VIEWER_DIST) does the rest."""
    from urllib.parse import quote
    if config.viewer_enabled() and src.startswith('/api/results/'):
        iframe_src = f"{config.viewer_mount_path()}/index.html?src={quote(src, safe='/')}"
        iframe_html = (
            f'<iframe src="{iframe_src}" title="3D viewer" allow="fullscreen" '
            'style="position:fixed;inset:0;width:100vw;height:100vh;border:0"></iframe>'
        )
        # NiceGUI ≥3 sanitizes ui.html and strips <iframe> outright, so the viewer would silently
        # vanish under the default — pass sanitize=False to keep it. That param doesn't exist in the
        # 2.x on the local dev box (which doesn't sanitize at all), so only pass it where supported;
        # a bare sanitize=False would raise TypeError there and break startup. Safe to disable:
        # both interpolated values are under our control — job_id is an int route param, and `src`
        # is quote()'d (any `"` becomes %22, so it can't break out of the src attribute).
        import inspect
        if 'sanitize' in inspect.signature(ui.html.__init__).parameters:
            ui.html(iframe_html, sanitize=False)
        else:
            ui.html(iframe_html)
        ui.button(icon='arrow_back', on_click=lambda: ui.navigate.to(back_to)) \
            .props('round color=primary').style('position:fixed;top:8px;left:8px;z-index:10') \
            .tooltip('Back')
        return
    service_header()
    with ui.column().classes('q-pa-md q-gutter-sm'):
        ext = config.external_3d_url()
        if config.viewer_enabled():   # viewer on, but src rejected
            ui.label('無効なビューアソースです。').classes('text-negative')
        elif ext:
            ui.label('内蔵3Dビューアは未設定です（WB_VIEWER_DIST）。外部ビューアを開きます。') \
                .classes('text-caption text-grey')
            ui.button('Open external 3D', icon='open_in_new',
                      on_click=lambda u=ext: ui.navigate.to(u, new_tab=True)).props('color=primary')
        else:
            ui.label('3Dビューアは未設定です（WB_VIEWER_DIST / WB_EXTERNAL_3D_URL）。') \
                .classes('text-grey')
        ui.button('← Back', on_click=lambda: ui.navigate.to(back_to)).props('flat')


@ui.page('/jobs/{job_id}/view3d')
def view3d_page(job_id: int):
    """Embedded 3D viewer for a job's result manifest."""
    _render_viewer(f'/api/results/jobs/{job_id}/', back_to=f'/jobs/{job_id}')


@ui.page('/view3d')
def view3d_generic_page(src: str = ''):
    """Embedded 3D viewer for an arbitrary same-origin result manifest base (e.g. a filesystem
    result set). `src` is the manifest base under /api/results/..."""
    _render_viewer(src, back_to='/results')


@ui.page('/results')
def fs_results_page():
    """Browse filesystem result sets (WB_RESULT_ROOTS) and open each in the 3D viewer. The links
    live here in Workbench (not in the viewer) so no Workbench-specific URL is baked into the
    viewer (feedback #1)."""
    from web.service_ui.results_api import scan_result_sets
    service_header(active='Results')
    with ui.column().classes('q-pa-md w-full'):
        ui.label('Analysis outputs').classes('text-h6 q-mb-sm')
        roots = config.result_roots()
        if not roots:
            ui.label('結果ルートは未設定です（WB_RESULT_ROOTS）。').classes('text-grey')
            return
        for name, root_dir in sorted(roots.items()):
            with ui.card().classes('w-full q-mb-md'):
                ui.label(f'📂 {name}').classes('text-subtitle1')
                try:
                    sets = scan_result_sets(root_dir)
                except OSError as exc:
                    ui.label(f'走査できません: {exc}').classes('text-negative text-caption')
                    continue
                if not sets:
                    ui.label('（閲覧可能な成果物なし）').classes('text-caption text-grey')
                    continue
                with ui.list().props('bordered separator').classes('w-full'):
                    for rel in sets:
                        base = f'/api/results/fs/{name}/{rel}/' if rel else f'/api/results/fs/{name}/'
                        with ui.item():
                            with ui.item_section():
                                ui.link(rel or '(root)', f'/view3d?src={base}')
