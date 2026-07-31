"""Server-side project management + generic parameter editor UI (docs/ui_refresh_design.md §4).

Pages (registered on both app.py and app_server.py):
- /projects            : list, create, upload (ZIP), copy, delete, download, submit, edit
- /projects/{name}/edit: generic typed-leaf editor over the project's JSON configs (etag-guarded)

Everything goes through the projects API via ServiceClient; the UI holds no project state. The
faithful typed-form port of the legacy calculate.py builders is a follow-up (review N-4); this v1
edits every scalar leaf of the config files, which is enough to iterate parameters without
re-uploading.
"""
from __future__ import annotations

import asyncio
import inspect
import io
import json
import re
import sys
import traceback

from nicegui import ui

from web.service_ui import config, config_edit, config_forms
from web.service_ui.layout import service_header

_MODES = ['trajectory', 'area', 'montecarlo', 'sensitivity']
# Modes where the -X "use all logical (SMT) threads" option applies (else default = physical
# cores). Mirror service.worker._MAX_THREAD_MODES; trajectory ignores the flag.
_PARALLEL_MODES = {'area', 'montecarlo', 'sensitivity'}

# Server-stored project names are constrained to this by service.projects (must mirror it). A
# browser upload named from a zip whose filename has spaces/Japanese/etc. would otherwise fail
# far away with a cryptic 422 — we sanitise to a valid name up front instead.
_NAME_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_NAME_BAD = re.compile(r"[^A-Za-z0-9_-]+")


def _client():
    return config.get_client()


def _log(msg: str):
    """Write to the process stderr so it lands in the service journal (journalctl -u
    forrocket-webui). NiceGUI/uvicorn does not surface arbitrary loggers by default, so a plain
    flushed print is the reliable record."""
    print(f"[projects_ui] {msg}", file=sys.stderr, flush=True)


def _fail(action: str, exc: Exception):
    """Surface a failed action in the browser (persistent — errors must not auto-dismiss and be
    missed) AND log it server-side, so an action that 'did nothing with no error' is never silent
    again."""
    _log(f"{action} failed: {exc!r}\n{traceback.format_exc()}")
    try:
        ui.notify(f'{action} failed: {exc}', type='negative', multi_line=True,
                  timeout=0, close_button='Dismiss')
    except Exception:  # notifying may itself fail outside a live client context
        pass


def _sanitize_name(raw: str) -> str:
    """Coerce a proposed project name into service.projects' allowed set (A-Za-z0-9_-, <=64)."""
    s = _NAME_BAD.sub("_", (raw or "").strip()).strip("_-")
    return s[:64] or "project"


def _upload_filename(e) -> str:
    """Filename from a NiceGUI upload event, tolerant of version differences: older releases expose
    `name`/`content` directly on the event; newer ones (e.g. the VM's) expose a single `file`
    attribute (a Starlette UploadFile with `.filename`). Never touch a fixed attribute."""
    for attr in ('name', 'file_name', 'filename'):
        v = getattr(e, attr, None)
        if v:
            return str(v)
    names = getattr(e, 'names', None)
    if names:
        return str(names[0])
    f = getattr(e, 'file', None)
    if f is not None:
        for attr in ('filename', 'name'):
            v = getattr(f, attr, None)
            if v:
                return str(v)
    return ''


def _as_bytes(data) -> bytes:
    if isinstance(data, str):
        return data.encode()
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    return b'' if data is None else bytes(data)


async def _read_upload(e) -> bytes:
    """Read an upload's bytes across NiceGUI majors.

    NiceGUI 3.x: `e.file` is a FileUpload whose `read()` is a *coroutine* (no sync accessor), so it
    must be awaited — which is why the upload handlers are async. NiceGUI 2.x: `e.content` (or
    `e.contents[0]`) is a sync file object, possibly already at EOF (the framework measured it), so
    we seek(0) first. Raw bytes/str are handled too. Never touch a fixed attribute (the event shape
    differs by version)."""
    f = getattr(e, 'file', None)                       # 3.x FileUpload
    if f is not None and hasattr(f, 'read'):
        res = f.read()
        return _as_bytes(await res if inspect.isawaitable(res) else res)
    c = getattr(e, 'content', None)                    # 2.x sync file object
    if c is None:
        contents = getattr(e, 'contents', None)
        c = contents[0] if contents else None
    if c is None:
        return b''
    if isinstance(c, (bytes, bytearray)):
        return bytes(c)
    try:
        c.seek(0)
    except Exception:
        pass
    return _as_bytes(c.read())


def _describe_upload(e) -> str:
    """A compact description of an upload event for the server log, so a still-unsupported NiceGUI
    shape reveals exactly which attribute holds the file/bytes."""
    attrs = sorted(a for a in dir(e) if not a.startswith('_'))
    f = getattr(e, 'file', None)
    if f is None:
        return f"event attrs: {attrs}"
    fattrs = sorted(a for a in dir(f) if not a.startswith('_'))
    return f"event attrs: {attrs}; file type={type(f).__name__} attrs={fattrs}"


async def _upload_to_store(fn, *args) -> None:
    """Run a blocking ServiceClient upload off the event loop (the upload handlers are async so
    they can await the 3.x FileUpload read; the HTTP client call must not block the loop)."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: fn(*args))


@ui.page('/projects')
def projects_page():
    service_header(active='Projects')
    with ui.column().classes('q-pa-md w-full'):
        ui.label('Projects').classes('text-h6 q-mb-sm')

        with ui.card().classes('w-full q-mb-md'):
            ui.label('New / Upload').classes('text-subtitle2 q-mb-xs')
            with ui.row().classes('items-center q-gutter-sm'):
                new_name = ui.input('New project name').props('dense').style('min-width:200px')

                def _create():
                    raw = (new_name.value or '').strip()
                    if not raw:
                        ui.notify('Enter a project name first.', type='warning')
                        return
                    name = _sanitize_name(raw)
                    try:
                        _client().create_project(name)
                        msg = f'Created "{name}".'
                        if name != raw:
                            msg += ' (name adjusted to letters/digits/_/- only)'
                        ui.notify(msg, type='positive')
                        new_name.set_value('')
                        listing.refresh()
                    except Exception as exc:
                        _fail('Create', exc)

                ui.button('Create empty', on_click=_create).props('dense')

                async def _on_upload(e):
                    # Upload a project ZIP; the server safe-unzips and validates it. The name comes
                    # from the field or the file stem, sanitised to the store's allowed charset so
                    # a Japanese/spaced filename doesn't fail with a cryptic, easy-to-miss error.
                    fname = _upload_filename(e)
                    raw = (new_name.value or fname.rsplit('.', 1)[0])
                    name = _sanitize_name(raw)
                    _log(f"upload received: file={fname!r} raw_name={raw!r} -> name={name!r} "
                         f"({_describe_upload(e)})")
                    try:
                        data = await _read_upload(e)
                        if not data:
                            _fail('Upload', ValueError('uploaded file was empty or unreadable'))
                            return
                        await _upload_to_store(_client().upload_project, name, data)
                        _log(f"stored project {name!r} ({len(data)} bytes)")
                        msg = f'Uploaded as "{name}".'
                        if name != raw.strip():
                            msg += ' (name adjusted to letters/digits/_/- only)'
                        ui.notify(msg, type='positive')
                        new_name.set_value('')
                        listing.refresh()
                    except Exception as exc:
                        _fail('Upload', exc)

                ui.upload(label='Upload .zip', auto_upload=True, on_upload=_on_upload) \
                    .props('accept=.zip').classes('max-w-xs')

        @ui.refreshable
        def listing():
            try:
                projects = _client().list_projects()
            except Exception as exc:
                ui.label(f'Cannot load projects: {exc}').classes('text-negative')
                return
            if not projects:
                ui.label('No projects yet. Create or upload one.').classes('text-caption text-grey')
                return
            with ui.list().props('bordered separator').classes('w-full'):
                for p in projects:
                    _project_row(p['name'], listing)

        listing()


def _project_row(name: str, listing):
    with ui.item():
        with ui.item_section():
            # The project name is a link to its editor (common UI: click the name to open it),
            # alongside the explicit Edit button.
            ui.link(f'📁 {name}', f'/projects/{name}/edit').classes('text-subtitle1')
        with ui.item_section().props('side'):
            with ui.row().classes('items-center q-gutter-xs'):
                mode_sel = ui.select(_MODES, value='trajectory').props('dense').style('min-width:130px')
                # SMT-threads toggle, shown only for the parallel modes (default = physical cores).
                mt_switch = ui.switch('SMT').props('dense') \
                    .bind_visibility_from(mode_sel, 'value', backward=lambda v: v in _PARALLEL_MODES)
                mt_switch.tooltip('全論理スレッド使用（SMT/HT）。既定は物理コア数。area/MC/sensitivity のみ')

                def _submit(n=name):
                    mode = mode_sel.value
                    use_max = bool(mt_switch.value) and mode in _PARALLEL_MODES
                    try:
                        res = _client().submit_project(n, mode, use_max_thread=use_max)
                        thr = 'all SMT threads' if use_max else 'physical cores'
                        ui.notify(f'Job #{res["id"]} queued ({mode}, {thr}).', type='positive')
                    except Exception as exc:
                        _fail('Submit', exc)

                ui.button('Submit', icon='send', on_click=lambda n=name: _submit(n)) \
                    .props('dense color=primary')
                ui.button('Edit', icon='edit',
                          on_click=lambda n=name: ui.navigate.to(f'/projects/{n}/edit')).props('dense flat')
                ui.button('Download', icon='download',
                          on_click=lambda n=name: _download(n)).props('dense flat')
                ui.button('Copy', icon='content_copy',
                          on_click=lambda n=name: _copy_dialog(n, listing)).props('dense flat')
                ui.button('Delete', icon='delete',
                          on_click=lambda n=name: _delete(n, listing)).props('dense flat color=negative')


def _download(name: str):
    try:
        data = _client().download_project(name)
        ui.download(data, f'{name}.zip')
    except Exception as exc:
        _fail('Download', exc)


def _copy_dialog(name: str, listing):
    with ui.dialog() as dlg, ui.card():
        ui.label(f'Copy "{name}" to:')
        dst = ui.input('New name').props('dense')

        def _do():
            try:
                _client().copy_project(name, (dst.value or '').strip())
                ui.notify('Copied.', type='positive')
                dlg.close()
                listing.refresh()
            except Exception as exc:
                _fail('Copy', exc)

        with ui.row():
            ui.button('Copy', on_click=_do).props('color=primary')
            ui.button('Cancel', on_click=dlg.close).props('flat')
    dlg.open()


def _delete(name: str, listing):
    with ui.dialog() as dlg, ui.card():
        ui.label(f'Delete project "{name}"? This cannot be undone.')
        with ui.row():
            def _do():
                try:
                    _client().delete_project(name)
                    ui.notify('Deleted.', type='warning')
                    dlg.close()
                    listing.refresh()
                except Exception as exc:
                    _fail('Delete', exc)
            ui.button('Delete', on_click=_do).props('color=negative')
            ui.button('Cancel', on_click=dlg.close).props('flat')
    dlg.open()


# Show the typed-form files in the runner's natural order first, then anything else.
_FILE_ORDER = ['config_solver.json', 'param_list_stage1.json', 'param_rocket.json',
               'param_engine.json', 'sequence_of_event.json', 'config_area.json',
               'config_montecarlo.json', 'config_sensitivity.json']

_FILE_LABELS = {
    'config_solver.json':      'Solver',
    'param_list_stage1.json':  'Stage-1',
    'param_rocket.json':       'Rocket',
    'param_engine.json':       'Engine',
    'sequence_of_event.json':  'Sequence of Events',
    'config_area.json':        'Area',
    'config_montecarlo.json':  'MonteCarlo',
    'config_sensitivity.json': 'Sensitivity',
}


def _ordered_files(files: dict) -> list:
    known = [f for f in _FILE_ORDER if f in files]
    extra = [f for f in files if f not in _FILE_ORDER]
    return known + extra


def _generic_form(content, container) -> 'callable':
    """Fallback editor for files without a typed form: one typed leaf per scalar. Returns a
    collect() closure so the save path is uniform with the typed forms."""
    inputs: dict = {}
    with container:
        flat = config_edit.flatten_config(content)
        if not flat:
            ui.label('(empty file)').classes('text-caption text-grey')
        with ui.grid(columns=2).classes('w-full q-col-gutter-sm'):
            for path, val in flat.items():
                if isinstance(val, bool):
                    el = ui.checkbox(path, value=val)
                elif isinstance(val, (int, float)):
                    el = ui.number(path, value=val).props('dense')
                else:
                    el = ui.input(path, value='' if val is None else str(val)).props('dense')
                inputs[path] = el

    def collect() -> dict:
        return config_edit.apply_edits(content, {p: el.value for p, el in inputs.items()})

    return collect


def _human_size(n: int) -> str:
    f = float(n)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if f < 1024 or unit == 'GB':
            return f'{f:.0f} {unit}' if unit == 'B' else f'{f:.1f} {unit}'
        f /= 1024
    return f'{f:.1f} GB'


def _csv_to_table(text: str, max_rows: int = 1000):
    """Parse CSV text into (columns, rows) for preview, or (None, None) if it isn't tabular.
    A fully-numeric first line is treated as data (synthesised column names)."""
    import csv as _csv
    text = (text or '').replace('\r\n', '\n').strip()
    if not text:
        return None, None
    rows = [r for r in _csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if len(rows) < 2 or len(rows[0]) < 2:   # need ≥2 rows and ≥2 columns to be worth a table
        return None, None

    def _isnum(s):
        try:
            float(s)
            return True
        except (TypeError, ValueError):
            return False

    if all(_isnum(c) for c in rows[0]):
        cols = [f'col{i}' for i in range(len(rows[0]))]
        data = rows
    else:
        cols, data = rows[0], rows[1:]
    return cols, data[:max_rows]


def _file_chart_opts(cols, rows):
    """echart line-chart options plotting column0 (x) vs each other numeric column, or None if the
    data isn't numeric enough to plot. Lets the user judge a thrust/CA/MOI curve before replacing."""
    def col_vals(j):
        out = []
        for r in rows:
            try:
                out.append(float(r[j]) if j < len(r) else None)
            except (TypeError, ValueError):
                out.append(None)
        return out

    xs = col_vals(0)
    if not any(v is not None for v in xs):
        return None
    palette = ['#42a5f5', '#ff9800', '#66bb6a', '#ab47bc', '#ff6b9d', '#00bcd4', '#ffca28']
    series = []
    for j in range(1, len(cols)):
        ys = col_vals(j)
        data = [[xs[i], ys[i]] for i in range(len(rows)) if xs[i] is not None and ys[i] is not None]
        if not data:
            continue
        series.append({'type': 'line', 'name': cols[j], 'data': data, 'showSymbol': False,
                       'lineStyle': {'color': palette[len(series) % len(palette)], 'width': 2}})
    if not series:
        return None
    ax = '#90a4ae'
    return {
        'backgroundColor': '#121212', 'animation': False,
        'tooltip': {'trigger': 'axis'},
        'legend': {'top': 2, 'textStyle': {'color': ax, 'fontSize': 10}, 'type': 'scroll'},
        'grid': {'top': 30, 'left': '10%', 'right': '4%', 'bottom': 40},
        'xAxis': {'type': 'value', 'name': cols[0], 'nameLocation': 'middle', 'nameGap': 26,
                  'nameTextStyle': {'color': ax}, 'axisLabel': {'color': ax},
                  'splitLine': {'lineStyle': {'color': '#2a2a2a', 'type': 'dashed'}}},
        'yAxis': {'type': 'value', 'axisLabel': {'color': ax},
                  'splitLine': {'lineStyle': {'color': '#2a2a2a', 'type': 'dashed'}}},
        'series': series,
    }


def _file_manager(name: str):
    """Upload/replace/download/delete/view the DATA files a config references (thrust/wind/aero
    CSVs), so a stored project can be iterated without re-uploading the whole ZIP. Collapsed by
    default and showing only data files (the .json configs are edited in the pane below)."""
    with ui.expansion('Input data files', icon='folder').classes('w-full q-mb-md') as exp:
        exp.props('dense')
        ui.label('config が参照する推力/風/空力テーブル等（CSV）。差し替えても config 内の値（パス）は変わりません。') \
            .classes('text-caption text-grey')

        @ui.refreshable
        def listing():
            try:
                data = _client().list_project_files(name)
            except Exception as exc:
                ui.label(f'Cannot load files: {exc}').classes('text-negative')
                return
            files = data.get('files', [])
            present = {f['path'] for f in files}
            referenced = set(data.get('referenced', []))
            missing = sorted(referenced - present)
            if missing:
                ui.label('⚠ config が参照しているが見つからないファイル: ' + ', '.join(missing)) \
                    .classes('text-negative text-caption')
            data_files = [f for f in files if not f.get('is_config')]   # hide the .json configs
            if not data_files:
                ui.label('データファイルはありません。').classes('text-caption text-grey')
                return
            with ui.list().props('bordered separator').classes('w-full'):
                for f in data_files:
                    _file_row(name, f, referenced, listing)

        async def _on_upload(e):
            fname = _upload_filename(e)
            target = (target_in.value or fname).strip()
            _log(f"file upload received: project={name!r} file={fname!r} target={target!r} "
                 f"({_describe_upload(e)})")
            try:
                data = await _read_upload(e)
                if not data:
                    _fail('Upload', ValueError('uploaded file was empty or unreadable'))
                    return
                await _upload_to_store(_client().upload_project_file, name, target, data)
                _log(f"stored file {target!r} in project {name!r} ({len(data)} bytes)")
                ui.notify(f'Uploaded {target}.', type='positive')
                target_in.set_value('')
                listing.refresh()
            except Exception as exc:
                _fail('Upload', exc)

        with ui.row().classes('items-center q-gutter-sm q-mt-xs'):
            target_in = ui.input('Save as（空欄=ファイル名／既存名を入力で差し替え）') \
                .props('dense').style('min-width:340px')
            ui.upload(label='Upload / Replace', auto_upload=True, on_upload=_on_upload) \
                .classes('max-w-xs')

        listing()


def _file_row(name: str, f: dict, referenced: set, listing):
    path, size = f['path'], f['size']
    badge = '🔗 referenced' if path in referenced else '· data (unused)'
    with ui.item():
        with ui.item_section():
            ui.item_label(path)
            ui.item_label(f'{_human_size(size)}   {badge}').props('caption')
        with ui.item_section().props('side'):
            with ui.row().classes('q-gutter-xs'):
                ui.button(icon='visibility', on_click=lambda p=path: _view_file(name, p)) \
                    .props('dense flat').tooltip('View contents')
                ui.button(icon='download', on_click=lambda p=path: _dl_file(name, p)) \
                    .props('dense flat').tooltip('Download')
                ui.button(icon='delete', on_click=lambda p=path: _del_file(name, p, listing)) \
                    .props('dense flat color=negative').tooltip('Delete')


def _view_file(name: str, path: str):
    """Preview a referenced file's current contents so the user can judge whether to replace it:
    a line chart (column0 vs each numeric column) plus a scrollable table for CSVs, or raw text."""
    with ui.dialog() as dlg, ui.card().style('min-width:680px; max-width:92vw'):
        ui.label(f'View: {path}').classes('text-subtitle1 q-mb-xs')
        try:
            text = _client().download_project_file(name, path).decode('utf-8', 'replace')
        except Exception as exc:
            ui.label(f'Cannot read file: {exc}').classes('text-negative')
            ui.button('Close', on_click=dlg.close).props('flat')
            dlg.open()
            return

        cols, rows = _csv_to_table(text)
        if cols:
            opts = _file_chart_opts(cols, rows)
            if opts:
                ui.echart(opts).style('width:100%;height:300px')
            t_cols = [{'name': f'c{i}', 'label': c, 'field': f'c{i}', 'align': 'left'}
                      for i, c in enumerate(cols)]
            t_rows = [{f'c{i}': (r[i] if i < len(r) else '') for i in range(len(cols))} for r in rows]
            ui.table(columns=t_cols, rows=t_rows, row_key='c0') \
                .props('dense flat bordered').classes('w-full').style('max-height:300px')
            ui.label(f'{len(rows)} rows × {len(cols)} cols'
                     + ('  (先頭1000行まで表示)' if len(rows) >= 1000 else '')) \
                .classes('text-caption text-grey')
        else:
            ui.textarea(value=text).props('readonly autogrow') \
                .classes('w-full').style('font-family:monospace; max-height:360px; overflow:auto')

        ui.button('Close', on_click=dlg.close).props('flat').classes('q-mt-sm')
    dlg.open()


def _dl_file(name: str, path: str):
    try:
        data = _client().download_project_file(name, path)
        ui.download(data, path.rsplit('/', 1)[-1])
    except Exception as exc:
        _fail('Download', exc)


def _del_file(name: str, path: str, listing):
    with ui.dialog() as dlg, ui.card():
        ui.label(f'Delete "{path}"? This cannot be undone.')
        with ui.row():
            def _do():
                try:
                    _client().delete_project_file(name, path)
                    ui.notify('Deleted.', type='warning')
                    dlg.close()
                    listing.refresh()
                except Exception as exc:
                    _fail('Delete', exc)
            ui.button('Delete', on_click=_do).props('color=negative')
            ui.button('Cancel', on_click=dlg.close).props('flat')
    dlg.open()


@ui.page('/projects/{name}/edit')
def project_edit_page(name: str):
    service_header(active='Projects')
    with ui.column().classes('q-pa-md w-full'):
        with ui.row().classes('items-center q-gutter-sm'):
            ui.button('← Projects', on_click=lambda: ui.navigate.to('/projects')).props('flat')
            ui.label(f'Edit: {name}').classes('text-h6')

        _file_manager(name)

        try:
            cfg = _client().get_project_config(name)
        except Exception as exc:
            ui.label(f'Cannot load config: {exc}').classes('text-negative')
            return

        files = cfg['files']
        ordered = _ordered_files(files)
        # IDE-style layout: a file list on the left, one file's editor on the right. Every file's
        # editor is BUILT (so its collect() exists), but only the active one is visible — the save
        # still gathers all files into one etag-guarded PUT (unchanged), so switching files never
        # loses edits. Per file: {'tabs', 'form_collect', 'json_area', 'content'}; on save the tab
        # left open is the source of truth (Form → collect(), JSON → parse the textarea).
        state = {'etag': cfg['etag'], 'active': ordered[0] if ordered else None}
        panels: dict = {}
        containers: dict = {}

        def _select(f):
            state['active'] = f
            for nm, col in containers.items():
                col.set_visibility(nm == f)
            nav.refresh()

        def _do_save() -> bool:
            """Collect every file (active tab wins) and PUT once with the etag. Returns True on
            success; notifies on failure. No success toast — callers add their own."""
            files_out = {}
            for fname, panel in panels.items():
                if panel['tabs'].value == 'JSON':
                    try:
                        files_out[fname] = json.loads(panel['json_area'].value)
                    except json.JSONDecodeError as exc:
                        ui.notify(f'{fname}: JSON parse error — {exc}', type='negative', multi_line=True)
                        return False
                else:
                    files_out[fname] = panel['form_collect']()
            try:
                res = _client().put_project_config(name, files_out, if_match=state['etag'])
                state['etag'] = res['etag']
                # Reflect the saved state into the JSON tabs so a subsequent JSON-tab save is clean.
                for fname, panel in panels.items():
                    panel['json_area'].set_value(
                        json.dumps(files_out[fname], indent=4, ensure_ascii=False))
                return True
            except Exception as exc:
                _fail('Save (reload if it changed elsewhere)', exc)
                return False

        def _save():
            if _do_save():
                ui.notify('Saved.', type='positive')

        def _submit():
            # Save first so the run reflects what's on screen, then queue by project reference.
            if not _do_save():
                return
            mode = mode_sel.value
            use_max = bool(mt_switch.value) and mode in _PARALLEL_MODES
            try:
                res = _client().submit_project(name, mode, use_max_thread=use_max)
                thr = 'all SMT threads' if use_max else 'physical cores'
                ui.notify(f'Saved & job #{res["id"]} queued ({mode}, {thr}). See Jobs to track it.',
                          type='positive')
            except Exception as exc:
                _fail('Submit', exc)

        with ui.row().classes('w-full no-wrap').style('gap:16px; align-items:flex-start'):
            # ── left: file nav (sticky) ──
            with ui.column().classes('q-gutter-xs') \
                    .style('min-width:200px; position:sticky; top:64px'):
                ui.label('Config files').classes('text-caption text-grey')

                @ui.refreshable
                def nav():
                    for f in ordered:
                        active = (f == state['active'])
                        ui.button(_FILE_LABELS.get(f, f),
                                  icon=('tune' if config_forms.has_form(f) else 'description'),
                                  on_click=lambda f=f: _select(f)) \
                            .props('flat no-caps align=left ' +
                                   ('color=primary' if active else 'color=grey-8')) \
                            .classes('w-full justify-start' + (' bg-blue-1' if active else ''))

                nav()
                ui.separator().classes('q-my-sm')
                ui.button('Save all', icon='save', on_click=lambda: _save()) \
                    .props('color=primary').classes('w-full')
                ui.label('全 config をまとめて保存（開いているタブが対象）') \
                    .classes('text-caption text-grey')

                # Submit straight from the editor (no need to go back to the list). Saves first so
                # the run matches what's on screen.
                ui.separator().classes('q-my-sm')
                ui.label('Run').classes('text-caption text-grey')
                mode_sel = ui.select(_MODES, value='trajectory', label='Mode') \
                    .props('dense').classes('w-full')
                # Thread option applies to area/MC/sensitivity only (default = physical cores).
                mt_switch = ui.switch('全論理スレッド使用 (SMT)', value=False).props('dense') \
                    .bind_visibility_from(mode_sel, 'value', backward=lambda v: v in _PARALLEL_MODES)
                ui.button('Save & Submit', icon='send', on_click=lambda: _submit()) \
                    .props('color=positive').classes('w-full')
                ui.label('保存してから投入します（既定は物理コア数）').classes('text-caption text-grey')

            # ── right: editor pane (every file built; only the active one visible) ──
            with ui.column().classes('flex-grow').style('min-width:0'):
                for fname in ordered:
                    content = files[fname]
                    typed = config_forms.has_form(fname)
                    col = ui.column().classes('w-full')
                    col.set_visibility(fname == state['active'])
                    with col:
                        ui.label(_FILE_LABELS.get(fname, fname)).classes('text-subtitle1 q-mb-xs')
                        with ui.tabs() as tabs:
                            ui.tab('Form')
                            ui.tab('JSON')
                        tabs.value = 'Form'
                        with ui.tab_panels(tabs, value='Form').classes('w-full'):
                            with ui.tab_panel('Form'):
                                form_con = ui.column().classes('w-full q-gutter-sm')
                                if typed:
                                    collect = config_forms.build_form(fname, content, form_con, siblings=files)
                                else:
                                    collect = _generic_form(content, form_con)
                            with ui.tab_panel('JSON'):
                                area = ui.textarea(value=json.dumps(content, indent=4, ensure_ascii=False)) \
                                    .classes('w-full').style('font-family:monospace; min-height:320px;')
                        panels[fname] = {'tabs': tabs, 'form_collect': collect,
                                         'json_area': area, 'content': content}
                    containers[fname] = col
