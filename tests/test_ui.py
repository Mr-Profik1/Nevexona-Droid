import pytest

pytest.importorskip("PySide6")


def test_main_window_builds(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from nevexona_droid.core.settings import Settings
    from nevexona_droid.ui.main_window import MainWindow, NAV
    app = QApplication.instance() or QApplication([])
    win = MainWindow(Settings(tmp_path / "t.db"))
    assert win.nav.count() == len(NAV) == 7
    for i in range(1, 7):
        win.show_page(i)
    win.pages[5].refresh()
    assert win.pages[5].theme.currentText() == "dark"
