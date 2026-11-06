"""Android Engine: управление Waydroid через его CLI."""
import shutil
import subprocess
from enum import Enum

from .runner import run


class State(str, Enum):
    NOT_INSTALLED = "Not Installed"
    READY = "Ready"
    STARTING = "Starting"
    RUNNING = "Running"
    STOPPED = "Stopped"
    ERROR = "Error"


def parse_status(text: str) -> dict:
    info = {}
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            info[k.strip().lower()] = v.strip()
    return info


def get_state(runner=run, which=shutil.which) -> State:
    if not which("waydroid"):
        return State.NOT_INSTALLED
    res = runner(["waydroid", "status"])
    if not res.ok:
        return State.ERROR
    info = parse_status(res.out)
    session = info.get("session", "").upper()
    container = info.get("container", "").upper()
    if session == "RUNNING" and container == "RUNNING":
        return State.RUNNING
    if session == "RUNNING":
        return State.STARTING
    if session == "STOPPED" and container in ("STOPPED", ""):
        return State.STOPPED
    return State.READY


def init_command():
    """Инициализация требует root: запрашиваем через стандартный pkexec."""
    return ["pkexec", "waydroid", "init"]


def start():
    """Сессия Waydroid живёт долго, поэтому запускаем в фоне без shell."""
    return subprocess.Popen(["waydroid", "session", "start"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)


def stop(runner=run):
    return runner(["waydroid", "session", "stop"], timeout=60)
