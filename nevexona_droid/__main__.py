import sys


def main():
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        sys.exit("Не найден PySide6. Установите: sudo apt install python3-pyside6.qtwidgets "
                 "или pip install PySide6")
    from .core.settings import Settings
    from .ui.main_window import MainWindow
    app = QApplication(sys.argv)
    app.setApplicationName("NEVEXONA Droid")
    win = MainWindow(Settings())
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
