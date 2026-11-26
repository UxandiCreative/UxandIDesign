"""Uxandi. Run this file (PyCharm: right-click > Run 'main') and the app opens maximized.

Needs PySide6:  python -m pip install -r requirements.txt
"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QFont
from PySide6.QtWidgets import QApplication

from uxandi.window import MainWindow


def main():
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Uxandi")
    f = QFont("Segoe UI")
    f.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(f)
    w = MainWindow()
    w.showMaximized()        # F11 switches full screen on and off
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
