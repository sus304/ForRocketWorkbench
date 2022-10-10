# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'main_window.ui'
#
# Created by: PyQt5 UI code generator 5.15.7
#
# WARNING: Any manual changes made to this file will be lost when pyuic5 is
# run again.  Do not edit this file unless you know what you are doing.


from PyQt5 import QtCore, QtGui, QtWidgets


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.resize(1125, 645)
        icon = QtGui.QIcon()
        icon.addPixmap(QtGui.QPixmap(":/icon/forrocket_icon.ico"), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        MainWindow.setWindowIcon(icon)
        MainWindow.setStyleSheet("background-color: rgb(45, 45, 45);\n"
"color: rgb(230, 230, 230);")
        self.centralwidget = QtWidgets.QWidget(MainWindow)
        self.centralwidget.setObjectName("centralwidget")
        self.label_solver_config_json = QtWidgets.QLabel(self.centralwidget)
        self.label_solver_config_json.setGeometry(QtCore.QRect(50, 50, 501, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(9)
        self.label_solver_config_json.setFont(font)
        self.label_solver_config_json.setStyleSheet("border-color: rgba(255, 255, 255, 0);\n"
"border-bottom-color: rgb(255, 255, 255);\n"
"border-style: solid;\n"
"border-width: 1px;")
        self.label_solver_config_json.setObjectName("label_solver_config_json")
        self.label_stage_config_json = QtWidgets.QLabel(self.centralwidget)
        self.label_stage_config_json.setGeometry(QtCore.QRect(90, 130, 501, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(9)
        self.label_stage_config_json.setFont(font)
        self.label_stage_config_json.setStyleSheet("border-color: rgba(255, 255, 255, 0);\n"
"border-bottom-color: rgb(255, 255, 255);\n"
"border-style: solid;\n"
"border-width: 1px;")
        self.label_stage_config_json.setObjectName("label_stage_config_json")
        self.label_rocket_param_json = QtWidgets.QLabel(self.centralwidget)
        self.label_rocket_param_json.setGeometry(QtCore.QRect(90, 210, 501, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(9)
        self.label_rocket_param_json.setFont(font)
        self.label_rocket_param_json.setStyleSheet("border-color: rgba(255, 255, 255, 0);\n"
"border-bottom-color: rgb(255, 255, 255);\n"
"border-style: solid;\n"
"border-width: 1px;")
        self.label_rocket_param_json.setObjectName("label_rocket_param_json")
        self.label_engine_param_json = QtWidgets.QLabel(self.centralwidget)
        self.label_engine_param_json.setGeometry(QtCore.QRect(90, 290, 501, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(9)
        self.label_engine_param_json.setFont(font)
        self.label_engine_param_json.setStyleSheet("border-color: rgba(255, 255, 255, 0);\n"
"border-bottom-color: rgb(255, 255, 255);\n"
"border-style: solid;\n"
"border-width: 1px;")
        self.label_engine_param_json.setObjectName("label_engine_param_json")
        self.label_soe_json = QtWidgets.QLabel(self.centralwidget)
        self.label_soe_json.setGeometry(QtCore.QRect(90, 370, 501, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(9)
        self.label_soe_json.setFont(font)
        self.label_soe_json.setStyleSheet("border-color: rgba(255, 255, 255, 0);\n"
"border-bottom-color: rgb(255, 255, 255);\n"
"border-style: solid;\n"
"border-width: 1px;")
        self.label_soe_json.setObjectName("label_soe_json")
        self.label_7 = QtWidgets.QLabel(self.centralwidget)
        self.label_7.setGeometry(QtCore.QRect(70, 260, 191, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.label_7.setFont(font)
        self.label_7.setObjectName("label_7")
        self.label_8 = QtWidgets.QLabel(self.centralwidget)
        self.label_8.setGeometry(QtCore.QRect(70, 180, 191, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.label_8.setFont(font)
        self.label_8.setObjectName("label_8")
        self.label_9 = QtWidgets.QLabel(self.centralwidget)
        self.label_9.setGeometry(QtCore.QRect(70, 100, 191, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.label_9.setFont(font)
        self.label_9.setObjectName("label_9")
        self.label_10 = QtWidgets.QLabel(self.centralwidget)
        self.label_10.setGeometry(QtCore.QRect(70, 340, 191, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.label_10.setFont(font)
        self.label_10.setObjectName("label_10")
        self.label_11 = QtWidgets.QLabel(self.centralwidget)
        self.label_11.setGeometry(QtCore.QRect(30, 20, 191, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.label_11.setFont(font)
        self.label_11.setObjectName("label_11")
        self.label_12 = QtWidgets.QLabel(self.centralwidget)
        self.label_12.setGeometry(QtCore.QRect(30, 440, 191, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.label_12.setFont(font)
        self.label_12.setObjectName("label_12")
        self.label_area_config_json = QtWidgets.QLabel(self.centralwidget)
        self.label_area_config_json.setGeometry(QtCore.QRect(50, 470, 501, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(9)
        self.label_area_config_json.setFont(font)
        self.label_area_config_json.setStyleSheet("border-color: rgba(255, 255, 255, 0);\n"
"border-bottom-color: rgb(255, 255, 255);\n"
"border-style: solid;\n"
"border-width: 1px;")
        self.label_area_config_json.setObjectName("label_area_config_json")
        self.pushButton_solver_config_json = QtWidgets.QPushButton(self.centralwidget)
        self.pushButton_solver_config_json.setGeometry(QtCore.QRect(550, 40, 41, 31))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.pushButton_solver_config_json.setFont(font)
        self.pushButton_solver_config_json.setStyleSheet("background-color: rgba(80, 80, 80, 0);")
        self.pushButton_solver_config_json.setText("")
        icon1 = QtGui.QIcon()
        icon1.addPixmap(QtGui.QPixmap(":/icon/pic/outline_more_horiz_white_24dp.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.pushButton_solver_config_json.setIcon(icon1)
        self.pushButton_solver_config_json.setIconSize(QtCore.QSize(32, 32))
        self.pushButton_solver_config_json.setObjectName("pushButton_solver_config_json")
        self.pushButton_area_config_json = QtWidgets.QPushButton(self.centralwidget)
        self.pushButton_area_config_json.setGeometry(QtCore.QRect(550, 460, 41, 31))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.pushButton_area_config_json.setFont(font)
        self.pushButton_area_config_json.setStyleSheet("background-color: rgba(80, 80, 80, 0);")
        self.pushButton_area_config_json.setText("")
        self.pushButton_area_config_json.setIcon(icon1)
        self.pushButton_area_config_json.setIconSize(QtCore.QSize(32, 32))
        self.pushButton_area_config_json.setObjectName("pushButton_area_config_json")
        self.textEdit_console_view = QtWidgets.QTextEdit(self.centralwidget)
        self.textEdit_console_view.setGeometry(QtCore.QRect(630, 280, 461, 321))
        font = QtGui.QFont()
        font.setFamily("Cascadia Mono")
        self.textEdit_console_view.setFont(font)
        self.textEdit_console_view.setUndoRedoEnabled(False)
        self.textEdit_console_view.setReadOnly(True)
        self.textEdit_console_view.setObjectName("textEdit_console_view")
        self.groupBox = QtWidgets.QGroupBox(self.centralwidget)
        self.groupBox.setGeometry(QtCore.QRect(630, 10, 461, 51))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.groupBox.setFont(font)
        self.groupBox.setObjectName("groupBox")
        self.label_18 = QtWidgets.QLabel(self.groupBox)
        self.label_18.setGeometry(QtCore.QRect(110, 20, 31, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.label_18.setFont(font)
        self.label_18.setObjectName("label_18")
        self.label_13 = QtWidgets.QLabel(self.groupBox)
        self.label_13.setGeometry(QtCore.QRect(160, 20, 51, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.label_13.setFont(font)
        self.label_13.setObjectName("label_13")
        self.label_cpu_freq = QtWidgets.QLabel(self.groupBox)
        self.label_cpu_freq.setGeometry(QtCore.QRect(60, 20, 41, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.label_cpu_freq.setFont(font)
        self.label_cpu_freq.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.label_cpu_freq.setObjectName("label_cpu_freq")
        self.label_16 = QtWidgets.QLabel(self.groupBox)
        self.label_16.setGeometry(QtCore.QRect(10, 20, 41, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.label_16.setFont(font)
        self.label_16.setObjectName("label_16")
        self.label_cpu_usage = QtWidgets.QLabel(self.groupBox)
        self.label_cpu_usage.setGeometry(QtCore.QRect(210, 20, 41, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.label_cpu_usage.setFont(font)
        self.label_cpu_usage.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.label_cpu_usage.setObjectName("label_cpu_usage")
        self.label_15 = QtWidgets.QLabel(self.groupBox)
        self.label_15.setGeometry(QtCore.QRect(260, 20, 16, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.label_15.setFont(font)
        self.label_15.setObjectName("label_15")
        self.label_19 = QtWidgets.QLabel(self.groupBox)
        self.label_19.setGeometry(QtCore.QRect(320, 20, 41, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.label_19.setFont(font)
        self.label_19.setObjectName("label_19")
        self.label_cpu_thread = QtWidgets.QLabel(self.groupBox)
        self.label_cpu_thread.setGeometry(QtCore.QRect(360, 20, 31, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.label_cpu_thread.setFont(font)
        self.label_cpu_thread.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.label_cpu_thread.setObjectName("label_cpu_thread")
        self.label_cpu_core = QtWidgets.QLabel(self.groupBox)
        self.label_cpu_core.setGeometry(QtCore.QRect(290, 20, 21, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.label_cpu_core.setFont(font)
        self.label_cpu_core.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.label_cpu_core.setObjectName("label_cpu_core")
        self.label_17 = QtWidgets.QLabel(self.groupBox)
        self.label_17.setGeometry(QtCore.QRect(400, 20, 51, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.label_17.setFont(font)
        self.label_17.setObjectName("label_17")
        self.line = QtWidgets.QFrame(self.centralwidget)
        self.line.setGeometry(QtCore.QRect(30, 50, 16, 301))
        self.line.setFrameShape(QtWidgets.QFrame.VLine)
        self.line.setFrameShadow(QtWidgets.QFrame.Sunken)
        self.line.setObjectName("line")
        self.line_2 = QtWidgets.QFrame(self.centralwidget)
        self.line_2.setGeometry(QtCore.QRect(40, 100, 21, 31))
        self.line_2.setFrameShape(QtWidgets.QFrame.HLine)
        self.line_2.setFrameShadow(QtWidgets.QFrame.Sunken)
        self.line_2.setObjectName("line_2")
        self.line_3 = QtWidgets.QFrame(self.centralwidget)
        self.line_3.setGeometry(QtCore.QRect(40, 180, 21, 31))
        self.line_3.setFrameShape(QtWidgets.QFrame.HLine)
        self.line_3.setFrameShadow(QtWidgets.QFrame.Sunken)
        self.line_3.setObjectName("line_3")
        self.line_4 = QtWidgets.QFrame(self.centralwidget)
        self.line_4.setGeometry(QtCore.QRect(40, 260, 21, 31))
        self.line_4.setFrameShape(QtWidgets.QFrame.HLine)
        self.line_4.setFrameShadow(QtWidgets.QFrame.Sunken)
        self.line_4.setObjectName("line_4")
        self.line_5 = QtWidgets.QFrame(self.centralwidget)
        self.line_5.setGeometry(QtCore.QRect(40, 340, 21, 31))
        self.line_5.setFrameShape(QtWidgets.QFrame.HLine)
        self.line_5.setFrameShadow(QtWidgets.QFrame.Sunken)
        self.line_5.setObjectName("line_5")
        self.groupBox_2 = QtWidgets.QGroupBox(self.centralwidget)
        self.groupBox_2.setGeometry(QtCore.QRect(630, 160, 461, 101))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.groupBox_2.setFont(font)
        self.groupBox_2.setObjectName("groupBox_2")
        self.pushButton_trajectory_calc = QtWidgets.QPushButton(self.groupBox_2)
        self.pushButton_trajectory_calc.setGeometry(QtCore.QRect(20, 30, 131, 51))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.pushButton_trajectory_calc.setFont(font)
        self.pushButton_trajectory_calc.setStyleSheet("background-color: rgb(80, 80, 80);")
        icon2 = QtGui.QIcon()
        icon2.addPixmap(QtGui.QPixmap(":/icon/pic/outline_where_to_vote_white_24dp.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.pushButton_trajectory_calc.setIcon(icon2)
        self.pushButton_trajectory_calc.setIconSize(QtCore.QSize(32, 32))
        self.pushButton_trajectory_calc.setObjectName("pushButton_trajectory_calc")
        self.pushButton_area_calc = QtWidgets.QPushButton(self.groupBox_2)
        self.pushButton_area_calc.setGeometry(QtCore.QRect(170, 30, 131, 51))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.pushButton_area_calc.setFont(font)
        self.pushButton_area_calc.setStyleSheet("background-color: rgb(80, 80, 80);")
        icon3 = QtGui.QIcon()
        icon3.addPixmap(QtGui.QPixmap(":/icon/pic/outline_wifi_tethering_white_24dp.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.pushButton_area_calc.setIcon(icon3)
        self.pushButton_area_calc.setIconSize(QtCore.QSize(32, 32))
        self.pushButton_area_calc.setObjectName("pushButton_area_calc")
        self.pushButton_montecarlo_calc = QtWidgets.QPushButton(self.groupBox_2)
        self.pushButton_montecarlo_calc.setGeometry(QtCore.QRect(320, 30, 131, 51))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.pushButton_montecarlo_calc.setFont(font)
        self.pushButton_montecarlo_calc.setStyleSheet("background-color: rgb(80, 80, 80);")
        icon4 = QtGui.QIcon()
        icon4.addPixmap(QtGui.QPixmap(":/icon/pic/outline_lens_blur_white_24dp.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.pushButton_montecarlo_calc.setIcon(icon4)
        self.pushButton_montecarlo_calc.setIconSize(QtCore.QSize(32, 32))
        self.pushButton_montecarlo_calc.setObjectName("pushButton_montecarlo_calc")
        self.checkBox_use_max_thread = QtWidgets.QCheckBox(self.groupBox_2)
        self.checkBox_use_max_thread.setGeometry(QtCore.QRect(220, 0, 181, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.checkBox_use_max_thread.setFont(font)
        self.checkBox_use_max_thread.setObjectName("checkBox_use_max_thread")
        self.label_montecarlo_config_json = QtWidgets.QLabel(self.centralwidget)
        self.label_montecarlo_config_json.setGeometry(QtCore.QRect(50, 550, 501, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(9)
        self.label_montecarlo_config_json.setFont(font)
        self.label_montecarlo_config_json.setStyleSheet("border-color: rgba(255, 255, 255, 0);\n"
"border-bottom-color: rgb(255, 255, 255);\n"
"border-style: solid;\n"
"border-width: 1px;")
        self.label_montecarlo_config_json.setObjectName("label_montecarlo_config_json")
        self.pushButton_montecarlo_config_json = QtWidgets.QPushButton(self.centralwidget)
        self.pushButton_montecarlo_config_json.setGeometry(QtCore.QRect(550, 540, 41, 31))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.pushButton_montecarlo_config_json.setFont(font)
        self.pushButton_montecarlo_config_json.setStyleSheet("background-color: rgba(80, 80, 80, 0);")
        self.pushButton_montecarlo_config_json.setText("")
        self.pushButton_montecarlo_config_json.setIcon(icon1)
        self.pushButton_montecarlo_config_json.setIconSize(QtCore.QSize(32, 32))
        self.pushButton_montecarlo_config_json.setObjectName("pushButton_montecarlo_config_json")
        self.label_14 = QtWidgets.QLabel(self.centralwidget)
        self.label_14.setGeometry(QtCore.QRect(30, 520, 191, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.label_14.setFont(font)
        self.label_14.setObjectName("label_14")
        self.groupBox_3 = QtWidgets.QGroupBox(self.centralwidget)
        self.groupBox_3.setGeometry(QtCore.QRect(630, 80, 461, 61))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(11)
        self.groupBox_3.setFont(font)
        self.groupBox_3.setObjectName("groupBox_3")
        self.pushButton_get_solver_version = QtWidgets.QPushButton(self.groupBox_3)
        self.pushButton_get_solver_version.setGeometry(QtCore.QRect(30, 30, 111, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(10)
        self.pushButton_get_solver_version.setFont(font)
        self.pushButton_get_solver_version.setLayoutDirection(QtCore.Qt.LeftToRight)
        self.pushButton_get_solver_version.setStyleSheet("background-color: rgb(80, 80, 80);")
        icon5 = QtGui.QIcon()
        icon5.addPixmap(QtGui.QPixmap("white-24dp (5)/2x/outline_upload_white_24dp.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.pushButton_get_solver_version.setIcon(icon5)
        self.pushButton_get_solver_version.setIconSize(QtCore.QSize(32, 32))
        self.pushButton_get_solver_version.setObjectName("pushButton_get_solver_version")
        self.pushButton_check_solver_latest_version = QtWidgets.QPushButton(self.groupBox_3)
        self.pushButton_check_solver_latest_version.setGeometry(QtCore.QRect(180, 30, 111, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(10)
        self.pushButton_check_solver_latest_version.setFont(font)
        self.pushButton_check_solver_latest_version.setLayoutDirection(QtCore.Qt.LeftToRight)
        self.pushButton_check_solver_latest_version.setStyleSheet("background-color: rgb(80, 80, 80);")
        self.pushButton_check_solver_latest_version.setIcon(icon5)
        self.pushButton_check_solver_latest_version.setIconSize(QtCore.QSize(32, 32))
        self.pushButton_check_solver_latest_version.setObjectName("pushButton_check_solver_latest_version")
        self.pushButton_update_solver = QtWidgets.QPushButton(self.groupBox_3)
        self.pushButton_update_solver.setGeometry(QtCore.QRect(330, 30, 111, 21))
        font = QtGui.QFont()
        font.setFamily("Meiryo UI")
        font.setPointSize(10)
        self.pushButton_update_solver.setFont(font)
        self.pushButton_update_solver.setLayoutDirection(QtCore.Qt.LeftToRight)
        self.pushButton_update_solver.setStyleSheet("background-color: rgb(80, 80, 80);")
        self.pushButton_update_solver.setIcon(icon5)
        self.pushButton_update_solver.setIconSize(QtCore.QSize(32, 32))
        self.pushButton_update_solver.setObjectName("pushButton_update_solver")
        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QtWidgets.QMenuBar(MainWindow)
        self.menubar.setGeometry(QtCore.QRect(0, 0, 1125, 21))
        self.menubar.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.menubar.setObjectName("menubar")
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QtWidgets.QStatusBar(MainWindow)
        self.statusbar.setObjectName("statusbar")
        MainWindow.setStatusBar(self.statusbar)
        self.action = QtWidgets.QAction(MainWindow)
        self.action.setObjectName("action")

        self.retranslateUi(MainWindow)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

    def retranslateUi(self, MainWindow):
        _translate = QtCore.QCoreApplication.translate
        MainWindow.setWindowTitle(_translate("MainWindow", "ForRocket Workbench"))
        self.label_solver_config_json.setText(_translate("MainWindow", "config_solver.json"))
        self.label_stage_config_json.setText(_translate("MainWindow", "config_stage.json"))
        self.label_rocket_param_json.setText(_translate("MainWindow", "param_rocket.json"))
        self.label_engine_param_json.setText(_translate("MainWindow", "param_engine.json"))
        self.label_soe_json.setText(_translate("MainWindow", "soe.json"))
        self.label_7.setText(_translate("MainWindow", "Engine Parameter Json"))
        self.label_8.setText(_translate("MainWindow", "Rocket Parameter Json"))
        self.label_9.setText(_translate("MainWindow", "Stage Configuration Json"))
        self.label_10.setText(_translate("MainWindow", "Sequence of Event Json"))
        self.label_11.setText(_translate("MainWindow", "Solver Configuration Json"))
        self.label_12.setText(_translate("MainWindow", "Area Config Json"))
        self.label_area_config_json.setText(_translate("MainWindow", "config_area.json"))
        self.textEdit_console_view.setHtml(_translate("MainWindow", "<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.0//EN\" \"http://www.w3.org/TR/REC-html40/strict.dtd\">\n"
"<html><head><meta name=\"qrichtext\" content=\"1\" /><style type=\"text/css\">\n"
"p, li { white-space: pre-wrap; }\n"
"</style></head><body style=\" font-family:\'Cascadia Mono\'; font-size:9pt; font-weight:400; font-style:normal;\">\n"
"<p style=\" margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;\">Console View</p></body></html>"))
        self.groupBox.setTitle(_translate("MainWindow", "CPU"))
        self.label_18.setText(_translate("MainWindow", "GHz"))
        self.label_13.setText(_translate("MainWindow", "Usage"))
        self.label_cpu_freq.setText(_translate("MainWindow", "0"))
        self.label_16.setText(_translate("MainWindow", "Freq."))
        self.label_cpu_usage.setText(_translate("MainWindow", "0"))
        self.label_15.setText(_translate("MainWindow", "%"))
        self.label_19.setText(_translate("MainWindow", "Core"))
        self.label_cpu_thread.setText(_translate("MainWindow", "0"))
        self.label_cpu_core.setText(_translate("MainWindow", "0"))
        self.label_17.setText(_translate("MainWindow", "Thread"))
        self.groupBox_2.setTitle(_translate("MainWindow", "Run"))
        self.pushButton_trajectory_calc.setText(_translate("MainWindow", "Trajectory"))
        self.pushButton_area_calc.setText(_translate("MainWindow", "Area"))
        self.pushButton_montecarlo_calc.setText(_translate("MainWindow", "MonteCarlo"))
        self.checkBox_use_max_thread.setText(_translate("MainWindow", "Use Max CPU Thread"))
        self.label_montecarlo_config_json.setText(_translate("MainWindow", "config_montecarlo.json"))
        self.label_14.setText(_translate("MainWindow", "MonteCarlo Config Json"))
        self.groupBox_3.setTitle(_translate("MainWindow", "Solver"))
        self.pushButton_get_solver_version.setText(_translate("MainWindow", "Current Version"))
        self.pushButton_check_solver_latest_version.setText(_translate("MainWindow", "Latest Version"))
        self.pushButton_update_solver.setText(_translate("MainWindow", "Update"))
        self.action.setText(_translate("MainWindow", "ライセンス"))
import pics_rc
