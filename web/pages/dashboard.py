import asyncio
import os

from nicegui import app, ui

from web.db.database import get_session
from web.db.models import Calculation
from web.pages.shared import build_header
from web.services.history_service import delete_calculations, filter_rows
from web.services.project_service import scan_projects


_MODE_OPTIONS = ['All', 'trajectory', 'area', 'montecarlo', 'sensitivity']


def _load_history() -> list[dict]:
    session = get_session()
    try:
        calcs = (
            session.query(Calculation)
            .order_by(Calculation.started_at.desc())
            .limit(500)
            .all()
        )
        rows = []
        for c in calcs:
            rdir = c.result_dir or ''
            rows.append({
                'id': c.id,
                'started_at': c.started_at.strftime('%Y-%m-%d %H:%M') if c.started_at else '',
                'mode': c.mode,
                'model': c.model_name or '',
                'project': c.project.name if c.project else '',
                'status': c.status,
                'memo': c.memo or '',
                'missing': bool(rdir) and not os.path.isdir(rdir),
            })
        return rows
    finally:
        session.close()


@ui.page('/')
def dashboard():
    build_header('Dashboard')

    project_names = scan_projects()
    all_history = _load_history()

    state = {
        'mode': 'All',
        'project': 'All',
        'search': '',
        'rows': list(all_history),
    }

    def apply_filters():
        out = filter_rows(all_history, state['mode'], state['project'], state['search'])
        state['rows'] = out
        if table is not None:
            table.rows = out
            table.selected = []
            table.update()

    def refresh_all():
        nonlocal all_history
        all_history = _load_history()
        apply_filters()

    def cleanup_missing():
        missing_ids = [r['id'] for r in all_history if r.get('missing')]
        if not missing_ids:
            ui.notify('No missing entries.', type='info')
            return

        with ui.dialog() as dialog, ui.card():
            ui.label(f'Remove {len(missing_ids)} orphaned record(s)?').classes('text-h6')
            ui.label('These entries reference result directories that no longer exist on disk.').classes('text-caption text-grey')
            ui.label('Only DB rows will be deleted.').classes('q-mt-sm')
            with ui.row().classes('q-mt-md justify-end full-width'):
                ui.button('Cancel', on_click=dialog.close).props('flat')
                def do_cleanup():
                    dialog.close()
                    n, errs = delete_calculations(missing_ids)
                    if errs:
                        ui.notify(f'Cleaned {n} record(s) with {len(errs)} error(s).',
                                  type='warning', multi_line=True)
                    else:
                        ui.notify(f'Cleaned {n} orphaned record(s).', type='positive')
                    refresh_all()
                ui.button('Clean up', on_click=do_cleanup).props('color=warning')
        dialog.open()

    def confirm_delete():
        sel = list(table.selected) if table is not None else []
        if not sel:
            ui.notify('No rows selected.', type='warning')
            return
        ids = [r['id'] for r in sel if isinstance(r, dict) and 'id' in r]
        if not ids:
            return

        with ui.dialog() as dialog, ui.card():
            ui.label(f'Delete {len(ids)} calculation(s)?').classes('text-h6')
            ui.label('DB records AND result directories on disk will be removed.').classes('text-caption text-grey')
            ui.label('This cannot be undone.').classes('text-negative q-mt-sm')
            with ui.row().classes('q-mt-md justify-end full-width'):
                ui.button('Cancel', on_click=dialog.close).props('flat')
                def do_delete():
                    dialog.close()
                    n, errs = delete_calculations(ids)
                    if errs:
                        ui.notify(
                            f'Deleted {n} record(s) with {len(errs)} error(s). First: {errs[0]}',
                            type='warning', multi_line=True,
                        )
                    else:
                        ui.notify(f'Deleted {n} record(s).', type='positive')
                    refresh_all()
                ui.button('Delete', on_click=do_delete).props('color=negative')
        dialog.open()

    def confirm_stop_server():
        job = calc_service.current_job()
        running = job.status in ('running', 'cancelling')

        with ui.dialog() as dialog, ui.card():
            ui.label('Stop ForRocket Workbench server?').classes('text-h6')
            if running:
                ui.label(f'A calculation is still {job.status} (calc #{job.calc_id}). '
                         'It will be terminated.').classes('text-negative q-mt-sm')
            else:
                ui.label('The browser tab will disconnect. You will need to relaunch the app to continue.') \
                    .classes('text-caption text-grey')
            with ui.row().classes('q-mt-md justify-end full-width'):
                ui.button('Cancel', on_click=dialog.close).props('flat')

                async def do_stop():
                    dialog.close()
                    ui.notify('Stopping server...', type='warning')
                    await asyncio.sleep(0.5)
                    app.shutdown()

                ui.button('Stop server', on_click=do_stop).props('color=negative')
        dialog.open()

    table = None

    with ui.row().classes('w-full h-full no-wrap'):
        # --- Sidebar ---
        with ui.column().classes('q-pa-md bg-blue-grey-9').style('width:220px; min-height:calc(100vh - 56px)'):
            ui.label('Projects').classes('text-subtitle2 text-white text-weight-bold q-mb-sm')
            if project_names:
                for name in project_names:
                    (ui.button(name, on_click=lambda n=name: ui.navigate.to(f'/calculate?project={n}'))
                     .props('flat align=left')
                     .classes('text-white full-width'))
            else:
                ui.label('No projects found').classes('text-caption text-grey-5')
            ui.space()
            (ui.button('+ New Project', on_click=lambda: ui.navigate.to('/calculate?new=1'))
             .props('outline')
             .classes('text-white full-width q-mt-md'))

        # --- Main content ---
        with ui.column().classes('q-pa-md flex-grow'):
            with ui.row().classes('items-center q-mb-md'):
                ui.label('Calculation History').classes('text-h6')
                ui.space()
                (ui.button('+ New Calculation', on_click=lambda: ui.navigate.to('/calculate'))
                 .props('color=primary'))
                (ui.button('Stop Server', icon='power_settings_new', on_click=confirm_stop_server)
                 .props('color=negative outline')
                 .tooltip('Shut down the Workbench server process'))

            # --- Filter / search bar ---
            with ui.row().classes('items-center q-gutter-sm q-mb-sm'):
                def on_mode(e):
                    state['mode'] = e.value
                    apply_filters()
                def on_proj(e):
                    state['project'] = e.value
                    apply_filters()
                def on_search(e):
                    state['search'] = e.value or ''
                    apply_filters()

                ui.select(_MODE_OPTIONS, value='All', label='Mode',
                          on_change=on_mode).props('dense outlined').style('min-width:140px')
                ui.select(['All'] + project_names, value='All', label='Project',
                          on_change=on_proj).props('dense outlined').style('min-width:160px')
                (ui.input(placeholder='Search model / memo / project / status',
                          on_change=on_search)
                 .props('dense outlined clearable')
                 .style('min-width:280px')
                 .on('keyup', lambda e: None))  # placeholder for keystroke updates
                ui.button(icon='refresh', on_click=refresh_all).props('flat round dense').tooltip('Reload (also re-scans for missing result directories)')
                ui.space()
                ui.button('Clean up missing', icon='cleaning_services',
                          on_click=cleanup_missing).props('color=warning outline') \
                    .tooltip('Remove DB entries whose result directory no longer exists on disk')
                ui.button('Delete selected', icon='delete',
                          on_click=confirm_delete).props('color=negative outline')

            if not all_history:
                ui.label('No calculations yet. Run your first calculation!').classes('text-grey q-mt-xl')
            else:
                columns = [
                    {'name': 'started_at', 'label': 'Date/Time', 'field': 'started_at', 'sortable': True, 'align': 'left'},
                    {'name': 'mode', 'label': 'Mode', 'field': 'mode', 'sortable': True, 'align': 'left'},
                    {'name': 'model', 'label': 'Model ID', 'field': 'model', 'sortable': True, 'align': 'left'},
                    {'name': 'project', 'label': 'Project', 'field': 'project', 'sortable': True, 'align': 'left'},
                    {'name': 'status', 'label': 'Status', 'field': 'status', 'sortable': True, 'align': 'left'},
                    {'name': 'memo', 'label': 'Memo', 'field': 'memo', 'align': 'left'},
                ]
                table = ui.table(
                    columns=columns,
                    rows=state['rows'],
                    row_key='id',
                    selection='multiple',
                ).classes('w-full')

                table.add_slot('body-cell-mode', '''
                    <q-td :props="props">
                        <q-badge :color="{'trajectory':'blue','area':'green','montecarlo':'purple','sensitivity':'orange'}[props.value] || 'grey'">
                            {{ props.value }}
                        </q-badge>
                    </q-td>
                ''')
                table.add_slot('body-cell-status', '''
                    <q-td :props="props">
                        <q-badge :color="{'completed':'positive','running':'primary','failed':'negative','cancelled':'warning','cancelling':'warning'}[props.value] || 'grey'">
                            {{ props.value }}
                        </q-badge>
                        <q-badge v-if="props.row.missing" color="grey-7" class="q-ml-xs" title="Result directory not found on disk">
                            missing
                        </q-badge>
                    </q-td>
                ''')

                def on_row_click(e):
                    # NiceGUI 3.x passes rowClick args as [event, row, index]
                    args = e.args
                    try:
                        if isinstance(args, list) and len(args) >= 2:
                            row = args[1]
                        elif isinstance(args, dict):
                            row = args.get('row', args)
                        else:
                            return
                        calc_id = row.get('id') if isinstance(row, dict) else None
                        if calc_id is not None:
                            ui.navigate.to(f'/result/{calc_id}')
                    except Exception:
                        pass

                table.on('rowClick', on_row_click)
