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

from web.service_ui import config, config_edit
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


@ui.page('/projects/{name}/edit')
def project_edit_page(name: str):
    service_header(active='Projects')
    with ui.column().classes('q-pa-md w-full'):
        with ui.row().classes('items-center q-gutter-sm'):
            ui.button('← Projects', on_click=lambda: ui.navigate.to('/projects')).props('flat')
            ui.label(f'Edit: {name}').classes('text-h6')

        try:
            cfg = _client().get_project_config(name)
        except Exception as exc:
            ui.label(f'Cannot load config: {exc}').classes('text-negative')
            return

        state = {'etag': cfg['etag']}
        inputs: dict = {}  # (filename, path) -> ui element

        for fname, content in cfg['files'].items():
            with ui.expansion(fname, icon='description').classes('w-full'):
                flat = config_edit.flatten_config(content)
                with ui.grid(columns=2).classes('w-full q-col-gutter-sm'):
                    for path, val in flat.items():
                        if isinstance(val, bool):
                            el = ui.checkbox(path, value=val)
                        elif isinstance(val, (int, float)):
                            el = ui.number(path, value=val).props('dense')
                        else:
                            el = ui.input(path, value='' if val is None else str(val)).props('dense')
                        inputs[(fname, path)] = el

        def _save():
            files_out = {}
            for fname, content in cfg['files'].items():
                edits = {path: inputs[(fname, path)].value
                         for (f, path) in inputs if f == fname}
                files_out[fname] = config_edit.apply_edits(content, edits)
            try:
                res = _client().put_project_config(name, files_out, if_match=state['etag'])
                state['etag'] = res['etag']
                ui.notify('Saved.', type='positive')
            except Exception as exc:
                ui.notify(f'Save failed (reload if it changed elsewhere): {exc}',
                          type='negative', multi_line=True)

        ui.button('Save', icon='save', on_click=_save).props('color=primary').classes('q-mt-md')
