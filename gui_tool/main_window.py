import sys
import os
import shutil

from PyQt5 import QtCore
from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5 import QtWidgets
from PyQt5.QtWidgets import QAction, QFileDialog
from PyQt5 import QtGui
from gui_tool.main_window_ui import Ui_MainWindow

from gui_tool.gui_stdout_stream import EmittingStream
from gui_tool.gui_cpu_percent import get_cpu_freq, get_cpu_percent, get_cpu_core, get_cpu_thread
from gui_tool.gui_json_copy import auto_suggest_jsons_path, import_jsons, import_area_json, import_montecarlo_json
from gui_tool.gui_calc_trajectory import RunTrajectoryThread
from gui_tool.gui_calc_area import RunAreaThread
from gui_tool.gui_calc_montecarlo import RunMontecarloThread

from update_tool.update_get_version import print_latest_solver_version, update_solver

from runner_tool.solver_control import print_solver_version_string, copy_solver_binary
from runner import ver_runner_tool
from post import ver_post_tool
from path_define import workbench_work_directory


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        self.pos_x = 100
        self.pos_y = 100

        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.__set_ui()

        sys.stdout = EmittingStream(textWritten=self.stdout_write)

    def __del__(self):
        sys.stdout = sys.__stdout__

    def __set_ui(self):
        self.move(self.pos_x, self.pos_y)

        self.previous_file_path = os.path.expanduser('~') + '/Desktop'
        self.ui.pushButton_solver_config_json.clicked.connect(self.select_solver_config_json_dialog)
        self.ui.pushButton_area_config_json.clicked.connect(lambda: self.ui.label_area_config_json.setText(self.select_file_dialog()))
        self.ui.pushButton_montecarlo_config_json.clicked.connect(lambda: self.ui.label_montecarlo_config_json.setText(self.select_file_dialog()))

        self.ui.pushButton_trajectory_calc.clicked.connect(lambda: self.run_calc_trajectory())
        self.ui.pushButton_area_calc.clicked.connect(lambda: self.run_calc_area())
        self.ui.pushButton_montecarlo_calc.clicked.connect(lambda: self.run_calc_montecarlo())

        self.ui.pushButton_get_solver_version.clicked.connect(print_solver_version_string)
        self.ui.pushButton_check_solver_latest_version.clicked.connect(print_latest_solver_version)
        self.ui.pushButton_update_solver.clicked.connect(update_solver)

        self.ui.textEdit_console_view.clear()

        self.ui.label_cpu_usage.setText(str(get_cpu_percent()))
        self.ui.label_cpu_freq.setText(str(get_cpu_freq()))
        self.ui.label_cpu_core.setText(str(get_cpu_core()))
        self.ui.label_cpu_thread.setText(str(get_cpu_thread()))

        self.cpu_status_refresh_timer = QtCore.QTimer()
        self.cpu_status_refresh_timer.setInterval(1000)
        self.cpu_status_refresh_timer.timeout.connect(self.refresh_cpu_status)
        self.cpu_status_refresh_timer.start()

        self.license_action = QAction('ライセンス', self)
        self.license_action.triggered.connect(self.show_about)
        help_menu = self.ui.menubar.addMenu('ヘルプ')
        help_menu.addAction(self.license_action)

        self.show()

    def stdout_write(self, text):
        line_count = self.ui.textEdit_console_view.document().blockCount()
        if line_count > 1024:
            self.ui.textEdit_console_view.clear()

        cursor = self.ui.textEdit_console_view.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        cursor.insertText(text)
        self.ui.textEdit_console_view.setTextCursor(cursor)
        self.ui.textEdit_console_view.ensureCursorVisible()

    def show_about(self):
        msgBox = QtWidgets.QMessageBox()
        msgBox.setWindowTitle('Help')
        msgBox.setText('ForRocket Workbench v2.0.1 licensed GPL-v3                                                 ')
        msgBox.setStandardButtons(QtWidgets.QMessageBox.Ok)
        license_txt = open('LICENSE', 'r').read()
        msgBox.setDetailedText(license_txt)
        res = msgBox.exec_()

    def refresh_cpu_status(self):
        self.ui.label_cpu_usage.setText(str(get_cpu_percent()))
        self.ui.label_cpu_freq.setText(str(get_cpu_freq()))

    def select_file_dialog(self):
        fname = QtWidgets.QFileDialog.getOpenFileName(self, 'Select config file', self.previous_file_path)
        if fname[0]:
            self.previous_file_path = fname[0]
            return fname[0]

    def select_solver_config_json_dialog(self):
        solver_config_path = self.select_file_dialog()
        self.ui.label_solver_config_json.setText(solver_config_path)
        try:
            stage_config_path, rocket_param_path, engine_param_path, soe_path = auto_suggest_jsons_path(solver_config_path)
        except:
            return
        self.ui.label_stage_config_json.setText(stage_config_path)
        self.ui.label_rocket_param_json.setText(rocket_param_path)
        self.ui.label_engine_param_json.setText(engine_param_path)
        self.ui.label_soe_json.setText(soe_path)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _import_solver_files(self, work_dir):
        return import_jsons(work_dir,
            self.ui.label_solver_config_json.text(),
            self.ui.label_stage_config_json.text(),
            self.ui.label_rocket_param_json.text(),
            self.ui.label_engine_param_json.text(),
            self.ui.label_soe_json.text(),
        )

    def _launch_worker(self, worker):
        """Wire worker to a new QThread, disable all calc buttons until done."""
        self.thread = QThread()
        worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run)
        worker.finished.connect(self.thread.quit)
        worker.finished.connect(worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

        calc_buttons = [
            self.ui.pushButton_trajectory_calc,
            self.ui.pushButton_area_calc,
            self.ui.pushButton_montecarlo_calc,
        ]
        for btn in calc_buttons:
            btn.setEnabled(False)
            self.thread.finished.connect(lambda b=btn: b.setEnabled(True))
        self.thread.finished.connect(lambda: shutil.rmtree(workbench_work_directory))

    # ------------------------------------------------------------------
    # Calc launchers
    # ------------------------------------------------------------------

    def run_calc_trajectory(self):
        work_dir = workbench_work_directory
        shutil.rmtree(work_dir, ignore_errors=True)
        os.mkdir(work_dir)
        try:
            solver_json = self._import_solver_files(work_dir)
            copy_solver_binary(work_dir)
        except Exception:
            QtWidgets.QMessageBox.critical(None, "Error", "Failure json file copy.", QtWidgets.QMessageBox.Ok)
            shutil.rmtree(work_dir)
            return
        self._launch_worker(RunTrajectoryThread(work_dir, solver_json))

    def run_calc_area(self):
        work_dir = workbench_work_directory
        shutil.rmtree(work_dir, ignore_errors=True)
        os.mkdir(work_dir)
        try:
            solver_json = self._import_solver_files(work_dir)
            area_json = import_area_json(work_dir, self.ui.label_area_config_json.text())
            copy_solver_binary(work_dir)
        except Exception:
            QtWidgets.QMessageBox.critical(None, "Error", "Failure json file copy.", QtWidgets.QMessageBox.Ok)
            shutil.rmtree(work_dir)
            return
        use_max_thread = self.ui.checkBox_use_max_thread.isChecked()
        self._launch_worker(RunAreaThread(work_dir, solver_json, area_json, use_max_thread))

    def run_calc_montecarlo(self):
        work_dir = workbench_work_directory
        shutil.rmtree(work_dir, ignore_errors=True)
        os.mkdir(work_dir)
        try:
            solver_json = self._import_solver_files(work_dir)
            montecarlo_json = import_montecarlo_json(work_dir, self.ui.label_montecarlo_config_json.text())
            copy_solver_binary(work_dir)
        except Exception:
            QtWidgets.QMessageBox.critical(None, "Error", "Failure json file copy.", QtWidgets.QMessageBox.Ok)
            shutil.rmtree(work_dir)
            return
        use_max_thread = self.ui.checkBox_use_max_thread.isChecked()
        self._launch_worker(RunMontecarloThread(work_dir, solver_json, montecarlo_json, use_max_thread))
