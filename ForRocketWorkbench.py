import sys
import multiprocessing

import PyQt5.QtCore as QtCore
import PyQt5.QtWidgets as QtWidgets
import PyQt5.QtGui as QtGui

# Window
from main_window import MainWindow

argvs = sys.argv
argc = len(argvs)

class Workbench:
    def __init__(self):
        self.main_win = MainWindow()


def main():
    app = QtWidgets.QApplication(argvs)
    wb = Workbench()
    sys.exit(app.exec_())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    
    main()