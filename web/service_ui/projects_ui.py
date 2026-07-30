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

import json

from nicegui import ui

from web.service_ui import config, config_edit, config_forms
from web.service_ui.layout import service_header

_MODES = ['trajectory', 'area', 'montecarlo', 'sensitivity']


def _client():
    return config.get_client()


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
                    try:
                        _client().create_project((new_name.value or '').strip())
                        ui.notify('Created.', type='positive')
                        listing.refresh()
                    except Exception as exc:
                        ui.notify(f'Create failed: {exc}', type='negative')

                ui.button('Create empty', on_click=_create).props('dense')

                def _on_upload(e):
                    # Upload a project ZIP; the server safe-unzips and validates it. Name comes
                    # from the field (or the file stem).
                    name = (new_name.value or e.name.rsplit('.', 1)[0]).strip()
                    try:
                        _client().upload_project(name, e.content.read())
                        ui.notify(f'Uploaded {name}.', type='positive')
                        listing.refresh()
                    except Exception as exc:
                        ui.notify(f'Upload failed: {exc}', type='negative', multi_line=True)

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
            ui.item_label(f'📁 {name}')
        with ui.item_section().props('side'):
            with ui.row().classes('items-center q-gutter-xs'):
                mode_sel = ui.select(_MODES, value='trajectory').props('dense').style('min-width:130px')

                def _submit(n=name, ms=None):
                    ms = ms or mode_sel
                    try:
                        res = _client().submit_project(n, ms.value)
                        ui.notify(f'Job #{res["id"]} queued ({ms.value}).', type='positive')
                    except Exception as exc:
                        ui.notify(f'Submit failed: {exc}', type='negative', multi_line=True)

                ui.button('Submit', icon='send', on_click=lambda n=name, m=mode_sel: _submit(n, m)) \
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
        ui.notify(f'Download failed: {exc}', type='negative')


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
                ui.notify(f'Copy failed: {exc}', type='negative')

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
                    ui.notify(f'Delete failed: {exc}', type='negative')
            ui.button('Delete', on_click=_do).props('color=negative')
            ui.button('Cancel', on_click=dlg.close).props('flat')
    dlg.open()


# Show the typed-form files in the runner's natural order first, then anything else.
_FILE_ORDER = ['config_solver.json', 'param_list_stage1.json', 'param_rocket.json',
               'param_engine.json', 'sequence_of_event.json', 'config_area.json',
               'config_montecarlo.json', 'config_sensitivity.json']


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


def _file_manager(name: str):
    """Upload/replace/download/delete the input files a config references (thrust/wind/aero CSVs),
    so a stored project can be iterated without re-uploading the whole ZIP."""
    with ui.card().classes('w-full q-mb-md'):
        with ui.row().classes('items-center q-gutter-sm'):
            ui.label('Input Files').classes('text-subtitle2')
            ui.label('config が参照する推力/風/空力テーブル等。差し替えても config 内の値（パス）は変わりません。') \
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
            if not files:
                ui.label('No files.').classes('text-caption text-grey')
                return
            with ui.list().props('bordered separator').classes('w-full'):
                for f in files:
                    _file_row(name, f, referenced, listing)

        def _on_upload(e):
            target = (target_in.value or e.name).strip()
            try:
                _client().upload_project_file(name, target, e.content.read())
                ui.notify(f'Uploaded {target}.', type='positive')
                target_in.set_value('')
                listing.refresh()
            except Exception as exc:
                ui.notify(f'Upload failed: {exc}', type='negative', multi_line=True)

        with ui.row().classes('items-center q-gutter-sm q-mt-xs'):
            target_in = ui.input('Save as（空欄=ファイル名／既存名を入力で差し替え）') \
                .props('dense').style('min-width:340px')
            ui.upload(label='Upload / Replace', auto_upload=True, on_upload=_on_upload) \
                .classes('max-w-xs')

        listing()


def _file_row(name: str, f: dict, referenced: set, listing):
    path, size = f['path'], f['size']
    badge = '⚙ config' if f.get('is_config') else ('🔗 referenced' if path in referenced else '· data')
    with ui.item():
        with ui.item_section():
            ui.item_label(path)
            ui.item_label(f'{_human_size(size)}   {badge}').props('caption')
        with ui.item_section().props('side'):
            with ui.row().classes('q-gutter-xs'):
                ui.button(icon='download', on_click=lambda p=path: _dl_file(name, p)) \
                    .props('dense flat').tooltip('Download')
                ui.button(icon='delete', on_click=lambda p=path: _del_file(name, p, listing)) \
                    .props('dense flat color=negative').tooltip('Delete')


def _dl_file(name: str, path: str):
    try:
        data = _client().download_project_file(name, path)
        ui.download(data, path.rsplit('/', 1)[-1])
    except Exception as exc:
        ui.notify(f'Download failed: {exc}', type='negative')


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
                    ui.notify(f'Delete failed: {exc}', type='negative')
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

        state = {'etag': cfg['etag']}
        files = cfg['files']
        # Per file: {'tabs', 'form_collect', 'json_area', 'content'}. On save, the active tab is
        # the source of truth — Form uses the typed/generic collect(), JSON parses the textarea.
        panels: dict = {}

        for fname in _ordered_files(files):
            content = files[fname]
            typed = config_forms.has_form(fname)
            icon = 'tune' if typed else 'description'
            with ui.expansion(fname, icon=icon, value=typed).classes('w-full'):
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
                panels[fname] = {'tabs': tabs, 'form_collect': collect, 'json_area': area,
                                 'content': content}

        def _save():
            files_out = {}
            for fname, panel in panels.items():
                if panel['tabs'].value == 'JSON':
                    try:
                        files_out[fname] = json.loads(panel['json_area'].value)
                    except json.JSONDecodeError as exc:
                        ui.notify(f'{fname}: JSON parse error — {exc}', type='negative', multi_line=True)
                        return
                else:
                    files_out[fname] = panel['form_collect']()
            try:
                res = _client().put_project_config(name, files_out, if_match=state['etag'])
                state['etag'] = res['etag']
                # Reflect the saved state into the JSON tabs so a subsequent JSON-tab save is clean.
                for fname, panel in panels.items():
                    panel['json_area'].set_value(
                        json.dumps(files_out[fname], indent=4, ensure_ascii=False))
                ui.notify('Saved.', type='positive')
            except Exception as exc:
                ui.notify(f'Save failed (reload if it changed elsewhere): {exc}',
                          type='negative', multi_line=True)

        with ui.row().classes('q-mt-md q-gutter-sm items-center'):
            ui.button('Save', icon='save', on_click=_save).props('color=primary')
            ui.label('Edit in Form or JSON per file; the tab you leave open is what gets saved.') \
                .classes('text-caption text-grey')
