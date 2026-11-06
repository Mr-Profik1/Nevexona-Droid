"""Compatibility Checker: реальные проверки системы."""
import os
import platform
import shutil
from dataclasses import dataclass, field

COMPATIBLE, PARTIAL, NOT_COMPATIBLE = "Compatible", "Partially Compatible", "Not Compatible"


@dataclass
class Report:
    arch: str
    ram_mb: int
    free_gb: float
    kernel: str
    session: str
    has_waydroid: bool
    has_adb: bool
    has_binder: bool
    verdict: str = COMPATIBLE
    problems: list = field(default_factory=list)
    advice: list = field(default_factory=list)


def _ram_mb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return 0


def _has_binder():
    if os.path.exists("/dev/binderfs") or os.path.exists("/dev/binder"):
        return True
    for path in ("/proc/filesystems", "/proc/modules"):
        try:
            with open(path) as f:
                if "binder" in f.read():
                    return True
        except OSError:
            pass
    return False


def evaluate(r: Report) -> Report:
    bad, warn = [], []
    if r.arch not in ("x86_64", "aarch64"):
        bad.append(f"Архитектура {r.arch} не поддерживается")
    if r.ram_mb < 2048:
        bad.append(f"Мало RAM: {r.ram_mb} МБ (нужно от 2048)")
    elif r.ram_mb < 4096:
        warn.append("RAM меньше 4 ГБ: Android будет работать медленно")
        r.advice.append("Закройте тяжёлые программы, ограничьте разрешение Android")
    if r.free_gb < 8:
        bad.append(f"Мало места: {r.free_gb:.1f} ГБ (нужно от 8)")
    if r.session not in ("wayland", "x11"):
        warn.append("Графическая сессия не определена")
    elif r.session == "x11":
        warn.append("Сессия X11: Waydroid рассчитан на Wayland, нужен вложенный compositor (например weston/cage)")
    if not r.has_binder:
        bad.append("Ядро без binder: Waydroid не запустится")
        r.advice.append("Установите ядро с binder (binder_linux / binderfs)")
    if not r.has_waydroid:
        warn.append("Waydroid не установлен")
        r.advice.append("Установите waydroid (apt install waydroid)")
    if not r.has_adb:
        warn.append("ADB не установлен")
        r.advice.append("Установите adb (apt install adb)")
    r.problems = bad + warn
    r.verdict = NOT_COMPATIBLE if bad else (PARTIAL if warn else COMPATIBLE)
    return r


def collect(path="/") -> Report:
    r = Report(
        arch=platform.machine(),
        ram_mb=_ram_mb(),
        free_gb=shutil.disk_usage(path).free / 1024**3,
        kernel=platform.release(),
        session=os.environ.get("XDG_SESSION_TYPE", "unknown").lower(),
        has_waydroid=shutil.which("waydroid") is not None,
        has_adb=shutil.which("adb") is not None,
        has_binder=_has_binder(),
    )
    return evaluate(r)


def format_report(r: Report) -> str:
    lines = [f"Результат: {r.verdict}", "",
             f"CPU: {r.arch}", f"RAM: {r.ram_mb} МБ", f"Свободно: {r.free_gb:.1f} ГБ",
             f"Ядро: {r.kernel}", f"Сессия: {r.session}",
             f"binder: {'да' if r.has_binder else 'нет'}",
             f"Waydroid: {'есть' if r.has_waydroid else 'нет'}",
             f"ADB: {'есть' if r.has_adb else 'нет'}"]
    if r.problems:
        lines += ["", "Замечания:"] + [f"• {p}" for p in r.problems]
    if r.advice:
        lines += ["", "Рекомендации:"] + [f"• {a}" for a in r.advice]
    return "\n".join(lines)
