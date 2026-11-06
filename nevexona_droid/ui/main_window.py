from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QHBoxLayout, QListWidget, QMainWindow, QStackedWidget, QWidget

from ..core.adb import Adb
from . import pages
from .theme import stylesheet


class Services:
    def __init__(self, settings):
        self.settings = settings

    def adb(self):
        return Adb(host=self.settings.get("adb_host"))


NAV = [("Dashboard", pages.Dashboard), ("App Store", pages.AppStore), ("My Apps", pages.MyApps),
       ("APK Manager", pages.ApkManager), ("Android Engine", pages.Engine),
       ("Settings", pages.Settings), ("About", pages.About)]


class MainWindow(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.svc = Services(settings)
        self.setWindowTitle("NEVEXONA Droid")
        try:
            w, h = (int(x) for x in settings.get("window_size").split("x"))
        except ValueError:
            w, h = 1100, 700
        self.resize(w, h)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.stack = QStackedWidget()
        self.pages = []
        for title, cls in NAV:
            self.nav.addItem(title)
            page = cls(self.svc, self)
            self.pages.append(page)
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.show_page)
        root = QWidget()
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.nav)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.apply_theme()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(8000)
        self.nav.setCurrentRow(0)

    def apply_theme(self):
        QApplication.instance().setStyleSheet(stylesheet(self.svc.settings.get("theme")))

    def show_page(self, i):
        self.stack.setCurrentIndex(i)
        self.pages[i].refresh()

    def open_apk_install(self):
        self.nav.setCurrentRow(3)
        self.pages[3].add_files()

    def poll_soon(self):
        for ms in (2000, 5000, 10000, 20000):
            QTimer.singleShot(ms, self.pages[0].refresh)

    def _tick(self):
        if self.svc.settings.get("auto_check") == "1" and self.stack.currentIndex() == 0:
            self.pages[0].refresh()
