"""Фоновые задачи: результат возвращается в главный поток через очередь Qt."""
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

_alive = set()
_bridge = None


class _Bridge(QObject):
    @Slot(object, object, object)
    def dispatch(self, cb, res, err):
        cb(res, err)

    @Slot(object, int, int)
    def dispatch_progress(self, cb, a, b):
        cb(a, b)


class _Worker(QThread):
    result = Signal(object, object, object)
    progress = Signal(object, int, int)

    def __init__(self, fn, cb, pcb):
        super().__init__()
        self.fn, self.cb, self.pcb = fn, cb, pcb

    def run(self):
        try:
            if self.pcb:
                res = self.fn(lambda a, b: self.progress.emit(self.pcb, int(a), int(b)))
            else:
                res = self.fn()
            self.result.emit(self.cb, res, None)
        except Exception as e:  # noqa: BLE001 — ошибка уходит в UI
            self.result.emit(self.cb, None, e)


def spawn(fn, on_done, on_progress=None):
    """fn() выполняется в потоке; on_done(result, error) — в главном.
    Если задан on_progress, fn получает аргумент progress(done, total)."""
    global _bridge
    if _bridge is None:
        _bridge = _Bridge()
    w = _Worker(fn, on_done, on_progress)
    w.result.connect(_bridge.dispatch, Qt.QueuedConnection)
    w.progress.connect(_bridge.dispatch_progress, Qt.QueuedConnection)
    _alive.add(w)
    w.finished.connect(lambda: _alive.discard(w))
    w.start()
