from nicegui import ui

from web.db.database import get_session
from web.db.models import Calculation
from web.pages.shared import build_header
from web.services.project_service import scan_projects


def _load_history() -> list[dict]:
    session = get_session()
    try:
        calcs = (
            session.query(Calculation)
            .order_by(Calculation.started_at.desc())
            .limit(100)
            .all()
        )
        rows = []
        for c in calcs:
            rows.append({
                'id': c.id,
                'started_at': c.started_at.strftime('%Y-%m-%d %H:%M') if c.started_at else '',
                'mode': c.mode,
                'model': c.model_name or '',
                'project': c.project.name if c.project else '',
                'status': c.status,
                'memo': c.memo or '',
            })
        return rows
    finally:
        session.close()


@ui.page('/')
def dashboard():
    build_header('Dashboard')

    project_names = scan_projects()
    history = _load_history()

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

            if not history:
                ui.label('No calculations yet. Run your first calculation!').classes('text-grey q-mt-xl')
            else:
                columns = [
                    {'name': 'started_at', 'label': 'Date/Time', 'field': 'started_at', 'sortable': True},
                    {'name': 'mode', 'label': 'Mode', 'field': 'mode'},
                    {'name': 'model', 'label': 'Model ID', 'field': 'model', 'sortable': True},
                    {'name': 'project', 'label': 'Project', 'field': 'project', 'sortable': True},
                    {'name': 'status', 'label': 'Status', 'field': 'status'},
                    {'name': 'memo', 'label': 'Memo', 'field': 'memo'},
                ]
                table = ui.table(
                    columns=columns,
                    rows=history,
                    row_key='id',
                    selection='single',
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
