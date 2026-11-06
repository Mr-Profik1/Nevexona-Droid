import os
import re

from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QVBoxLayout, QWidget, QCheckBox)

from .. import __version__
from ..core import diagnostics, engine, repository
from ..core.adb import Adb, AdbError, validate_apk
from ..core.runner import run
from .worker import spawn


def _label(text, name=None):
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(True)
    return lab


def _button(text, fn, primary=False):
    b = QPushButton(text)
    if primary:
        b.setObjectName("primary")
    b.clicked.connect(fn)
    return b


def _row(*widgets):
    box = QHBoxLayout()
    for w in widgets:
        box.addWidget(w)
    box.addStretch()
    return box


def _err(parent, text):
    QMessageBox.warning(parent, "NEVEXONA Droid", str(text))


class Page(QWidget):
    def __init__(self, svc, win):
        super().__init__()
        self.svc, self.win = svc, win
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(20, 16, 20, 16)

    def refresh(self):
        pass

    def adb_ready(self):
        """Подключается к Android; возвращает (Adb, ошибка)."""
        a = self.svc.adb()
        if not a.available():
            return a, "ADB не установлен (sudo apt install adb)"
        if engine.get_state() != engine.State.RUNNING:
            return a, "Android не запущен. Нажмите Start Android."
        a.connect()
        st = a.state()
        if st == "unauthorized":
            return a, ("Android ждёт разрешения на отладку по ADB. Нажмите Show Android, "
                       "подтвердите диалог в окне Android и повторите.")
        if st != "device":
            return a, "Не удаётся подключиться к Android по ADB. Проверьте адрес в настройках."
        return a, None


class Dashboard(Page):
    def __init__(self, svc, win):
        super().__init__(svc, win)
        self.lay.addWidget(_label("NEVEXONA Droid", "title"))
        self.lay.addWidget(_label("NEVEXONA Corporation", "mute"))
        self.status = _label("Android Engine: …", "status")
        self.lay.addWidget(self.status)
        self.start_b = _button("Start Android", self.start, True)
        self.stop_b = _button("Stop Android", self.stop)
        self.show_b = _button("Show Android", self.show_ui)
        self.lay.addLayout(_row(self.start_b, self.show_b, self.stop_b,
                                _button("Install APK", lambda: win.open_apk_install())))
        self.adb_l, self.count_l = _label(""), _label("")
        self.lay.addWidget(self.adb_l)
        self.lay.addWidget(self.count_l)
        self.lay.addWidget(_label("Недавно запущенные", "title"))
        self.recent = QListWidget()
        self.recent.setMaximumHeight(120)
        self.lay.addWidget(self.recent)
        self.lay.addWidget(_label("Система", "title"))
        self.sysinfo = _label("")
        self.lay.addWidget(self.sysinfo)
        self.lay.addStretch()

    def refresh(self):
        def probe():
            st = engine.get_state()
            a = self.svc.adb()
            has = a.available()
            online, n = False, None
            if has and st == engine.State.RUNNING:
                a.connect()
                online = a.is_online()
                if online:
                    n = len(a.packages())
            return st, has, online, n, diagnostics.collect()

        def show(res, err):
            if err:
                self.status.setText(f"Android Engine: {engine.State.ERROR.value}")
                return
            st, has, online, n, rep = res
            self.status.setText(f"Android Engine: {st.value}")
            self.start_b.setEnabled(st in (engine.State.READY, engine.State.STOPPED))
            self.stop_b.setEnabled(st in (engine.State.RUNNING, engine.State.STARTING))
            self.show_b.setEnabled(st == engine.State.RUNNING)
            self.adb_l.setText("ADB: " + ("подключён" if online else "установлен, нет подключения" if has else "не установлен"))
            self.count_l.setText("Установлено приложений: " + (str(n) if n is not None else "— (Android не подключён)"))
            self.recent.clear()
            self.recent.addItems(self.svc.settings.recent())
            self.sysinfo.setText(f"{rep.arch} · RAM {rep.ram_mb} МБ · ядро {rep.kernel} · {rep.session} · {rep.verdict}")
        spawn(probe, show)

    def start(self):
        def job():
            if engine.get_state() == engine.State.NOT_INSTALLED:
                raise RuntimeError("Waydroid не установлен. См. раздел Android Engine.")
            engine.start()

        def done(_, err):
            if err:
                return _err(self, err)
            self.status.setText("Android Engine: Starting")
            self.win.poll_soon()
        spawn(job, done)

    def show_ui(self):
        spawn(engine.show_ui, lambda r, e: _err(self, e or r.err or r.out)
              if (e or not r.ok) else None)

    def stop(self):
        spawn(engine.stop, lambda r, e: (_err(self, e or r.err) if (e or not r.ok) else None, self.refresh()))


class Engine(Page):
    def __init__(self, svc, win):
        super().__init__(svc, win)
        self.lay.addWidget(_label("Android Engine (Waydroid)", "title"))
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.lay.addWidget(self.out)
        self.lay.addLayout(_row(_button("Проверить совместимость", self.refresh),
                                _button("Инициализировать Android", self.init, True),
                                _button("Подключить ADB", self.connect)))

    def refresh(self):
        spawn(diagnostics.collect, lambda r, e: self.out.setPlainText(
            str(e) if e else diagnostics.format_report(r)))

    def init(self):
        if QMessageBox.question(self, "Инициализация",
                                "Будет запущен «pkexec waydroid init» (потребуется пароль администратора, "
                                "скачивается образ Android). Продолжить?") != QMessageBox.Yes:
            return
        self.out.setPlainText("Инициализация… это может занять несколько минут.")
        spawn(lambda: run(engine.init_command(), timeout=3600),
              lambda r, e: self.out.setPlainText(str(e) if e else
                                                 ("Готово." if r.ok else f"Ошибка:\n{r.err or r.out}")))

    def connect(self):
        def job():
            a, msg = self.adb_ready()
            return msg or "ADB подключён"
        spawn(job, lambda r, e: self.out.setPlainText(str(e) if e else r))


class MyApps(Page):
    def __init__(self, svc, win):
        super().__init__(svc, win)
        self.pkgs = []
        self.lay.addWidget(_label("My Apps", "title"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск…")
        self.search.textChanged.connect(self.fill)
        self.sort = QComboBox()
        self.sort.addItems(["А–Я", "Я–А", "Недавние"])
        self.sort.currentIndexChanged.connect(self.fill)
        self.lay.addLayout(_row(self.search, self.sort))
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self.launch())
        self.lay.addWidget(self.list)
        self.info = _label("", "mute")
        self.lay.addWidget(self.info)
        self.lay.addLayout(_row(_button("Запустить", self.launch, True),
                                _button("Удалить", self.remove), _button("Обновить список", self.refresh)))

    def refresh(self):
        def job():
            a, msg = self.adb_ready()
            if msg:
                raise AdbError(msg)
            return a.packages()

        def done(res, err):
            self.pkgs = [] if err else res
            self.info.setText(str(err) if err else "" if res else "Установленных приложений нет")
            self.fill()
        spawn(job, done)

    def fill(self):
        q = self.search.text().strip().lower()
        items = [p for p in self.pkgs if q in p.lower()]
        mode = self.sort.currentIndex()
        if mode == 2:
            rec = self.svc.settings.recent(1000)
            items.sort(key=lambda p: rec.index(p) if p in rec else len(rec))
        else:
            items.sort(reverse=(mode == 1))
        self.list.clear()
        self.list.addItems(items)

    def _current(self):
        it = self.list.currentItem()
        if not it:
            _err(self, "Выберите приложение")
        return it.text() if it else None

    def launch(self):
        pkg = self._current()
        if not pkg:
            return

        def job():
            a, msg = self.adb_ready()
            if msg:
                raise AdbError(msg)
            return a.launch(pkg)

        def done(ok, err):
            if err or not ok:
                return _err(self, err or "Не удалось запустить приложение")
            self.svc.settings.log_launch(pkg)
        spawn(job, done)

    def remove(self):
        pkg = self._current()
        if not pkg or QMessageBox.question(self, "Удаление", f"Удалить {pkg}?") != QMessageBox.Yes:
            return

        def job():
            a, msg = self.adb_ready()
            if msg:
                raise AdbError(msg)
            return a.uninstall(pkg)

        def done(res, err):
            if err or not res[0]:
                _err(self, err or res[1] or "Не удалось удалить")
            self.refresh()
        spawn(job, done)


class ApkManager(Page):
    def __init__(self, svc, win):
        super().__init__(svc, win)
        self.lay.addWidget(_label("APK Manager", "title"))
        self.lay.addWidget(_label("Очередь установки. Повторная установка того же пакета обновляет приложение.", "mute"))
        self.queue = QListWidget()
        self.lay.addWidget(self.queue)
        self.lay.addLayout(_row(_button("Добавить APK…", self.add_files),
                                _button("Убрать выбранный", self.remove_sel),
                                _button("Установить очередь", self.install, True)))

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Выберите APK", self.svc.settings.get("apk_dir"), "APK (*.apk)")
        for f in files:
            try:
                validate_apk(f)
            except AdbError as e:
                _err(self, f"{os.path.basename(f)}: {e}")
                continue
            self.queue.addItem(f)

    def remove_sel(self):
        for it in self.queue.selectedItems():
            self.queue.takeItem(self.queue.row(it))

    def install(self):
        paths = [self.queue.item(i).text().split("  —  ")[0] for i in range(self.queue.count())]
        if not paths:
            return _err(self, "Очередь пуста")

        def job():
            a, msg = self.adb_ready()
            if msg:
                raise AdbError(msg)
            out = []
            for p in paths:
                try:
                    out.append((p,) + a.install(p))
                except AdbError as e:
                    out.append((p, False, str(e)))
            return out

        def done(res, err):
            if err:
                return _err(self, err)
            self.queue.clear()
            for p, ok, msg in res:
                self.queue.addItem(f"{p}  —  {'✔ установлено' if ok else '✘ ' + msg}")
        spawn(job, done)


class AppStore(Page):
    def __init__(self, svc, win):
        super().__init__(svc, win)
        self.apps = []
        self.lay.addWidget(_label("App Store — F-Droid", "title"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск…")
        self.search.textChanged.connect(self.fill)
        self.cat = QComboBox()
        self.cat.currentIndexChanged.connect(self.fill)
        self.lay.addLayout(_row(self.search, self.cat, _button("Загрузить каталог", self.load)))
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.details)
        self.lay.addWidget(self.list)
        self.card = _label("Каталог не загружен. Нажмите «Загрузить каталог».", "mute")
        self.lay.addWidget(self.card)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.lay.addWidget(self.bar)
        self.lay.addLayout(_row(_button("Download", self.download), _button("Download + Install", self.install, True)))
        self.shown = []

    def load(self):
        self.card.setText("Загрузка каталога…")

        def done(res, err):
            if err:
                self.card.setText(f"Каталог недоступен: {err}")
                return
            self.apps = res
            self.cat.blockSignals(True)
            self.cat.clear()
            self.cat.addItem("Все категории")
            self.cat.addItems(repository.categories(res))
            self.cat.blockSignals(False)
            self.card.setText(f"Приложений в каталоге: {len(res)}")
            self.fill()
        spawn(repository.fetch_index, done)

    def fill(self):
        cat = self.cat.currentText() if self.cat.currentIndex() > 0 else None
        self.shown = repository.search(self.apps, self.search.text(), cat)[:300]
        self.list.clear()
        self.list.addItems([f"{a.name} — {a.summary}" for a in self.shown])

    def details(self, row):
        if 0 <= row < len(self.shown):
            a = self.shown[row]
            mb = f"{a.size / 1048576:.1f} МБ" if a.size else "размер неизвестен"
            self.card.setText(f"{a.name} {a.version} ({a.package}, {mb})\n{a.description[:400]}")

    def _selected(self):
        r = self.list.currentRow()
        if r < 0 or r >= len(self.shown):
            _err(self, "Выберите приложение")
            return None
        return self.shown[r]

    def _fetch(self, app, then_install):
        self.bar.setVisible(True)
        self.bar.setValue(0)
        dest = self.svc.settings.get("download_dir")

        def job(progress):
            path = repository.download(app, dest, progress)
            if not then_install:
                return path, None
            a, msg = self.adb_ready()
            if msg:
                raise AdbError(f"Файл скачан и проверен ({path}), но установка невозможна: {msg}")
            return path, a.install(path)

        def done(res, err):
            self.bar.setVisible(False)
            if err:
                return _err(self, err)
            path, inst = res
            if inst is None:
                _err(self, f"Скачано и проверено (SHA-256): {path}")
            elif inst[0]:
                _err(self, f"{app.name} установлено")
            else:
                _err(self, f"Установка не удалась: {inst[1]}")
        spawn(job, done, lambda d, t: self.bar.setValue(int(d * 100 / t) if t else 0))

    def download(self):
        a = self._selected()
        if a:
            self._fetch(a, False)

    def install(self):
        a = self._selected()
        if a:
            self._fetch(a, True)


class Settings(Page):
    def __init__(self, svc, win):
        super().__init__(svc, win)
        self.lay.addWidget(_label("Settings", "title"))
        form = QFormLayout()
        self.theme = QComboBox(); self.theme.addItems(["dark", "light"])
        self.res = QLineEdit(); self.win_size = QLineEdit(); self.host = QLineEdit()
        self.dl = QLineEdit(); self.apk = QLineEdit()
        self.auto = QCheckBox("Автоматически проверять Android Engine")
        for label, w in (("Тема", self.theme), ("Разрешение Android (ШИРИНАxВЫСОТА)", self.res),
                         ("Размер окна", self.win_size), ("Адрес ADB", self.host),
                         ("Папка загрузок", self.dl), ("Папка APK", self.apk)):
            form.addRow(label, w)
        self.lay.addLayout(form)
        self.lay.addWidget(self.auto)
        self.lay.addLayout(_row(_button("Сохранить", self.save, True), _button("Очистить кэш", self.clear),
                                _button("Диагностика", self.diag)))
        self.lay.addStretch()

    def refresh(self):
        s = self.svc.settings
        self.theme.setCurrentText(s.get("theme"))
        self.res.setText(s.get("resolution")); self.win_size.setText(s.get("window_size"))
        self.host.setText(s.get("adb_host")); self.dl.setText(s.get("download_dir"))
        self.apk.setText(s.get("apk_dir")); self.auto.setChecked(s.get("auto_check") == "1")

    def save(self):
        size = re.compile(r"^\d{3,4}x\d{3,4}$")
        host = re.compile(r"^[\w.\-]+:\d{2,5}$")
        if not size.match(self.res.text()) or not size.match(self.win_size.text()):
            return _err(self, "Размеры задаются как 1280x720")
        if not host.match(self.host.text()):
            return _err(self, "Адрес ADB в формате хост:порт")
        s = self.svc.settings
        for k, v in (("theme", self.theme.currentText()), ("resolution", self.res.text()),
                     ("window_size", self.win_size.text()), ("adb_host", self.host.text()),
                     ("download_dir", self.dl.text()), ("apk_dir", self.apk.text()),
                     ("auto_check", "1" if self.auto.isChecked() else "0")):
            s.set(k, v)
        self.win.apply_theme()
        w, h = self.res.text().split("x")

        def job():
            if engine.get_state() != engine.State.RUNNING:
                return False
            for key, val in (("persist.waydroid.width", w), ("persist.waydroid.height", h)):
                run(["waydroid", "prop", "set", key, val])
            return True

        spawn(job, lambda applied, e: _err(
            self, e or ("Сохранено. Разрешение применится после перезапуска Android."
                        if applied else "Сохранено.")))

    def clear(self):
        d, n = self.svc.settings.get("download_dir"), 0
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(".part"):
                    os.remove(os.path.join(d, f)); n += 1
        _err(self, f"Удалено незавершённых загрузок: {n}")

    def diag(self):
        spawn(diagnostics.collect, lambda r, e: _err(self, e or diagnostics.format_report(r)))


class About(Page):
    def __init__(self, svc, win):
        super().__init__(svc, win)
        self.lay.addWidget(_label(f"NEVEXONA Droid {__version__}", "title"))
        self.lay.addWidget(_label("NEVEXONA Corporation"))
        self.lay.addWidget(_label("Запуск Android-приложений в Linux через Waydroid и ADB. "
                                  "Каталог приложений: F-Droid.", "mute"))
        self.lay.addStretch()
