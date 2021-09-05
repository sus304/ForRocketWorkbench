import sys
import os
import shutil
import json

from PyQt5 import QtCore
from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5 import QtWidgets
from PyQt5.QtWidgets import QAction, QFileDialog
from PyQt5 import QtGui
# from PyQt5 import uic
from main_window_ui import Ui_MainWindow

from gui_tool.gui_stdout_stream import EmittingStream
from gui_tool.gui_cpu_percent import get_cpu_freq, get_cpu_percent, get_cpu_core, get_cpu_thread
from gui_tool.gui_json_copy import copy_jsons, copy_area_json, get_jsons_path
from gui_tool.gui_calc_trajectory import RunTrajectoryThread
from gui_tool.gui_calc_area import RunAreaThread

from runner_tool.runner_solver import print_solver_version_string
from runner import ver_runner_tool
from post import ver_post_tool

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
        # Restore sys.stdout
        sys.stdout = sys.__stdout__
    

    def __set_ui(self):
        self.move(self.pos_x, self.pos_y)

        # uic.loadUi('main_window.ui', self)


        ## Json UI ###############################
        # solver config
        self.previous_file_path = os.path.expanduser('~') + '/Desktop'
        self.ui.pushButton_solver_config_json.clicked.connect(self.select_solver_config_json_dialog)
        self.ui.pushButton_stage_config_json.clicked.connect(lambda: self.ui.label_stage_config_json.setText(self.select_file_dialog()))
        self.ui.pushButton_rocket_param_json.clicked.connect(lambda: self.ui.label_rocket_param_json.setText(self.select_file_dialog()))
        self.ui.pushButton_engine_param_json.clicked.connect(lambda: self.ui.label_engine_param_json.setText(self.select_file_dialog()))
        self.ui.pushButton_soe_json.clicked.connect(lambda: self.ui.label_soe_json.setText(self.select_file_dialog()))
        self.ui.pushButton_area_config_json.clicked.connect(lambda: self.ui.label_area_config_json.setText(self.select_file_dialog()))


        ## Calc run button #######################
        self.ui.pushButton_trajectory_calc.clicked.connect(lambda: self.run_calc_trajectory())
        self.ui.pushButton_area_calc.clicked.connect(lambda: self.run_calc_area())

        self.ui.pushButton_get_solver_version.clicked.connect(print_solver_version_string)
        self.ui.pushButton_get_runner_version.clicked.connect(lambda: print('Runner version:'+ver_runner_tool))
        self.ui.pushButton_get_post_version.clicked.connect(lambda: print('Post version:'+ver_post_tool))

        self.ui.textEdit_console_view.clear()

        ## CPU status ############################
        self.cpu_status_refresh_timer = QtCore.QTimer()
        self.cpu_status_refresh_timer.setInterval(1000)  # ms
        self.cpu_status_refresh_timer.timeout.connect(self.refresh_cpu_status)
        self.cpu_status_refresh_timer.start()

        self.ui.label_cpu_usage.setText(str(get_cpu_percent()))
        self.ui.label_cpu_freq.setText(str(get_cpu_freq()))
        self.ui.label_cpu_core.setText(str(get_cpu_core()))
        self.ui.label_cpu_thread.setText(str(get_cpu_thread()))
        
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
        msgBox.setText('ForRocket Workbench licensed GPL-v3                                                 ')
        # msgBox.setIcon(QMessageBox.Information)
        msgBox.setStandardButtons(QtWidgets.QMessageBox.Ok)
        license_txt = open('LICENSE', 'r').read()
        msgBox.setDetailedText(license_txt)
        res = msgBox.exec_()


    def refresh_cpu_status(self):
        self.ui.label_cpu_usage.setText(str(get_cpu_percent()))
        self.ui.label_cpu_freq.setText(str(get_cpu_freq()))


    def select_file_dialog(self):
        fname = QtWidgets.QFileDialog.getOpenFileName(self, 'Select config file', self.previous_file_path)
        # fname[0]は選択したファイルのパス（ファイル名を含む）
        if fname[0]:
            self.previous_file_path = fname[0]
            return fname[0]
    
    def select_solver_config_json_dialog(self):
        solver_config_path = self.select_file_dialog()
        self.ui.label_solver_config_json.setText(solver_config_path)
        try:
            stage_config_path, rocket_param_path, engine_param_path, soe_path = get_jsons_path(solver_config_path)
        except:
            return
        self.ui.label_stage_config_json.setText(stage_config_path)
        self.ui.label_rocket_param_json.setText(rocket_param_path)
        self.ui.label_engine_param_json.setText(engine_param_path)
        self.ui.label_soe_json.setText(soe_path)


    def run_calc_trajectory(self):
        work_dir_name = 'workspace'
        try:
            shutil.rmtree(work_dir_name)
        except:
            pass
        os.mkdir(work_dir_name)
        try:
            solver_json = copy_jsons(work_dir_name,
                    self.ui.label_solver_config_json.text(),
                    self.ui.label_stage_config_json.text(),
                    self.ui.label_rocket_param_json.text(),
                    self.ui.label_engine_param_json.text(),
                    self.ui.label_soe_json.text()
                )
        except:
            ret = QtWidgets.QMessageBox.critical(None, "Error", "Failure json file copy.", QtWidgets.QMessageBox.Ok)
            shutil.rmtree(work_dir_name)
            return

        self.thread = QThread()
        self.worker = RunTrajectoryThread(work_dir_name, solver_json)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        self.thread.start()

        self.ui.pushButton_trajectory_calc.setEnabled(False)
        self.ui.pushButton_area_calc.setEnabled(False)

        self.thread.finished.connect(
            lambda: self.ui.pushButton_trajectory_calc.setEnabled(True)
        )
        self.thread.finished.connect(
            lambda: self.ui.pushButton_area_calc.setEnabled(True)
        )
        self.thread.finished.connect(
            lambda: shutil.rmtree(work_dir_name)
        )

    def run_calc_area(self):
        work_dir_name = 'workspace'
        try:
            shutil.rmtree(work_dir_name)
        except:
            pass
        os.mkdir(work_dir_name)
        try:
            solver_json = copy_jsons(work_dir_name,
                    self.ui.label_solver_config_json.text(),
                    self.ui.label_stage_config_json.text(),
                    self.ui.label_rocket_param_json.text(),
                    self.ui.label_engine_param_json.text(),
                    self.ui.label_soe_json.text()
                )
            area_json = copy_area_json(work_dir_name,
                    self.ui.label_area_config_json.text()
                )
        except:
            ret = QtWidgets.QMessageBox.critical(None, "Error", "Failure json file copy.", QtWidgets.QMessageBox.Ok)
            shutil.rmtree(work_dir_name)
            return
        use_max_thread = self.ui.checkBox_use_max_thread.isChecked()

        self.thread = QThread()
        self.worker = RunAreaThread(work_dir_name, solver_json, area_json, use_max_thread)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        self.thread.start()

        self.ui.pushButton_trajectory_calc.setEnabled(False)
        self.ui.pushButton_area_calc.setEnabled(False)

        self.thread.finished.connect(
            lambda: self.ui.pushButton_trajectory_calc.setEnabled(True)
        )
        self.thread.finished.connect(
            lambda: self.ui.pushButton_area_calc.setEnabled(True)
        )
        self.thread.finished.connect(
            lambda: shutil.rmtree(work_dir_name)
        )

