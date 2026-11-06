"""ADB Manager: подключение, установка и управление приложениями."""
import os
import re

from .runner import run

MAX_APK_BYTES = 4 * 1024**3
PKG_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")
DEFAULT_HOST = "192.168.240.112:5555"


class AdbError(Exception):
    pass


def validate_apk(path):
    if not path.lower().endswith(".apk"):
        raise AdbError("Файл должен иметь расширение .apk")
    if not os.path.isfile(path):
        raise AdbError("Файл не найден")
    size = os.path.getsize(path)
    if size == 0:
        raise AdbError("Файл пустой")
    if size > MAX_APK_BYTES:
        raise AdbError("Файл слишком большой")
    with open(path, "rb") as f:
        if f.read(2) != b"PK":
            raise AdbError("Файл не является APK (ZIP) архивом")


def check_package(name):
    if not PKG_RE.match(name):
        raise AdbError(f"Недопустимое имя пакета: {name!r}")
    return name


class Adb:
    def __init__(self, host=DEFAULT_HOST, runner=run):
        self.host, self.run = host, runner

    def _adb(self, *args, timeout=60):
        return self.run(["adb", "-s", self.host, *args], timeout=timeout)

    def available(self):
        return self.run(["adb", "version"], timeout=10).ok

    def connect(self):
        res = self.run(["adb", "connect", self.host], timeout=15)
        return res.ok and ("connected" in res.out and "unable" not in res.out
                           and "failed" not in res.out)

    def state(self):
        """device / unauthorized / offline / unreachable."""
        res = self._adb("get-state", timeout=10)
        if res.ok:
            return res.out.strip() or "unreachable"
        text = (res.out + res.err).lower()
        if "unauthorized" in text:
            return "unauthorized"
        if "offline" in text:
            return "offline"
        return "unreachable"

    def is_online(self):
        return self.state() == "device"

    def install(self, apk):
        validate_apk(apk)
        res = self._adb("install", "-r", apk, timeout=600)
        text = (res.out + res.err).strip()
        if res.ok and "Success" in res.out:
            return True, "Установлено"
        return False, text or "Установка не удалась"

    def uninstall(self, pkg):
        check_package(pkg)
        res = self._adb("uninstall", pkg)
        return (res.ok and "Success" in res.out), (res.out + res.err).strip()

    def packages(self):
        res = self._adb("shell", "pm", "list", "packages", "-3")
        if not res.ok:
            raise AdbError(res.err.strip() or "Не удалось получить список")
        return sorted(l.split(":", 1)[1].strip() for l in res.out.splitlines()
                      if l.startswith("package:"))

    def launch(self, pkg):
        check_package(pkg)
        res = self._adb("shell", "monkey", "-p", pkg,
                        "-c", "android.intent.category.LAUNCHER", "1")
        return res.ok and "No activities found" not in res.out
