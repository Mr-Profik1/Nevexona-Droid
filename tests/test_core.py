import pytest
from nevexona_droid.core import adb, diagnostics as d, engine
from nevexona_droid.core.runner import Result, run
from nevexona_droid.core.settings import Settings


def fake(out="", ok=True, err=""):
    return lambda args, timeout=30: Result(ok, 0 if ok else 1, out, err)


def test_runner_missing_command():
    assert run(["definitely-not-a-cmd"]).found is False


def test_runner_rejects_string():
    with pytest.raises(TypeError):
        run("ls -l")


def test_engine_states():
    w = lambda n: "/usr/bin/waydroid"
    assert engine.get_state(fake(), lambda n: None) == engine.State.NOT_INSTALLED
    assert engine.get_state(fake("Session:\tRUNNING\nContainer:\tRUNNING"), w) == engine.State.RUNNING
    assert engine.get_state(fake("Session:\tSTOPPED\nContainer:\tSTOPPED"), w) == engine.State.STOPPED
    assert engine.get_state(fake(ok=False), w) == engine.State.ERROR


def test_install_never_fakes_success(tmp_path):
    apk = tmp_path / "a.apk"
    apk.write_bytes(b"PK\x03\x04data")
    ok, _ = adb.Adb(runner=fake("Failure [INSTALL_FAILED_OLDER_SDK]")).install(str(apk))
    assert not ok
    ok, _ = adb.Adb(runner=fake("Success")).install(str(apk))
    assert ok


def test_validate_apk(tmp_path):
    bad = tmp_path / "x.txt"
    bad.write_text("x")
    with pytest.raises(adb.AdbError):
        adb.validate_apk(str(bad))
    fake_apk = tmp_path / "y.apk"
    fake_apk.write_text("not zip")
    with pytest.raises(adb.AdbError):
        adb.validate_apk(str(fake_apk))


def test_package_name_validation():
    with pytest.raises(adb.AdbError):
        adb.check_package("a.b; rm -rf /")
    assert adb.check_package("org.fdroid.fdroid")


def test_packages_parse():
    a = adb.Adb(runner=fake("package:com.b\npackage:com.a\n"))
    assert a.packages() == ["com.a", "com.b"]


def rep(**kw):
    base = dict(arch="x86_64", ram_mb=8192, free_gb=50, kernel="6.12", session="wayland",
                has_waydroid=True, has_adb=True, has_binder=True)
    base.update(kw)
    return d.evaluate(d.Report(**base))


def test_compat_verdicts():
    assert rep().verdict == d.COMPATIBLE
    assert rep(has_adb=False).verdict == d.PARTIAL
    assert rep(ram_mb=1024).verdict == d.NOT_COMPATIBLE
    assert rep(has_binder=False).verdict == d.NOT_COMPATIBLE


def test_settings(tmp_path):
    s = Settings(tmp_path / "t.db")
    assert s.get("theme") == "dark"
    s.set("theme", "light")
    assert s.get("theme") == "light"
    with pytest.raises(KeyError):
        s.set("nope", 1)
    s.log_launch("a.b"); s.log_launch("c.d"); s.log_launch("a.b")
    assert s.recent() == ["a.b", "c.d"]


def test_settings_from_other_thread(tmp_path):
    import threading
    s = Settings(tmp_path / "t.db")
    out = []
    t = threading.Thread(target=lambda: out.append(s.get("adb_host")))
    t.start(); t.join()
    assert out == ["192.168.240.112:5555"]


def test_engine_frozen_container_is_running():
    w = lambda n: "/usr/bin/waydroid"
    assert engine.get_state(fake("Session:\tRUNNING\nContainer:\tFROZEN"), w) == engine.State.RUNNING


def test_show_ui_command():
    assert engine.show_ui_command() == ["waydroid", "show-full-ui"]


def test_adb_state():
    def r(out="", err="", ok=True):
        return lambda args, timeout=30: Result(ok, 0 if ok else 1, out, err)
    assert adb.Adb(runner=r("device\n")).state() == "device"
    assert adb.Adb(runner=r(err="error: device unauthorized.", ok=False)).state() == "unauthorized"
    assert adb.Adb(runner=r(err="error: device offline", ok=False)).state() == "offline"
    assert adb.Adb(runner=r(err="error: no devices", ok=False)).state() == "unreachable"
    assert not adb.Adb(runner=r(err="error: device unauthorized.", ok=False)).is_online()


def test_format_report():
    text = d.format_report(rep(has_adb=False))
    assert "Partially Compatible" in text and "adb" in text.lower()
