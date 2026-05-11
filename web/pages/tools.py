"""Tools hub page."""
from nicegui import ui

from web.pages.shared import build_header


@ui.page('/tools')
def tools_page():
    build_header('Tools')

    with ui.column().classes('q-pa-xl items-center w-full'):
        ui.label('Engineering Tools').classes('text-h5 q-mb-xs')
        ui.label('補助計算ツール — プロジェクトとは独立して使用できます').classes('text-grey q-mb-xl')

        with ui.row().classes('q-gutter-lg justify-center'):
            _tool_card(
                icon='calculate',
                title='Barrowman CP Calculator',
                desc='BarrowmanメソッドによるCP位置・CNα・静安定マージン計算\n（ノーズ、フィン、ボートテール対応）',
                path='/tools/barrowman',
                color='blue',
            )
            _tool_card(
                icon='balance',
                title='Mass Budget & Inertia',
                desc='コンポーネント別の質量・重心・慣性モーメント計算\n（平行軸定理による全体値導出）',
                path='/tools/mass',
                color='green',
            )
            _tool_card(
                icon='local_fire_department',
                title='Hybrid Engine Performance',
                desc='ハイブリッドロケットエンジンの推力・比推力・燃焼時間計算\n（定常点解析＋バーンシミュレーション）',
                path='/tools/engine',
                color='orange',
            )


def _tool_card(icon: str, title: str, desc: str, path: str, color: str):
    with (ui.card()
          .classes('cursor-pointer q-hoverable')
          .style('width:280px; min-height:200px')
          .on('click', lambda p=path: ui.navigate.to(p))):
        with ui.column().classes('q-pa-sm q-gutter-sm items-start'):
            ui.icon(icon, size='2.5rem').classes(f'text-{color}')
            ui.label(title).classes('text-subtitle1 text-weight-bold')
            for line in desc.split('\n'):
                ui.label(line).classes('text-caption text-grey')
            ui.space()
            ui.button('Open →', on_click=lambda p=path: ui.navigate.to(p)).props(f'flat color={color} dense')
