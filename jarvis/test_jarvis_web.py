"""Проверки окна (jarvis_web.py) по настоящему HTTP и новых функций ядра. Запуск: см. test_jarvis.py."""
import contextlib
import http.client
import io
import json
import os
import re
import stat
import sys
import tempfile
import threading
import time
import unittest
from http.server import HTTPServer
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_jarvis import Base, FakeAPI  # noqa: E402
import jarvis_web as web  # noqa: E402

j = web.j


class CoreExtraTests(Base):
    def test_model_for(self):
        self.j.MODEL, self.j.VISION_MODEL = "chat-m", "vision-m"
        text_only = [{"role": "user", "content": "привет"}]
        with_image = text_only + [{"role": "user", "content": [{"type": "image_url"}]}]
        self.assertEqual(self.j.model_for(text_only), "chat-m")
        self.assertEqual(self.j.model_for(with_image), "vision-m")
        self.j.VISION_MODEL = ""
        self.assertEqual(self.j.model_for(with_image), "chat-m")

    def test_defaults_without_config(self):
        self.assertEqual(self.j.DEFAULT_MODEL, "openrouter/free")
        self.assertEqual(self.j.DEFAULT_VISION_MODEL, "nvidia/nemotron-3.5-super-vl:free")
        self.assertTrue(self.j.BASE_URL.startswith("https://openrouter.ai"))
        self.assertFalse(self.j.ai_ready())  # без ключа ИИ не включается

    def test_try_pin_states(self):
        self.j.save_pin("1234")
        self.assertEqual(self.j.try_pin("x")[0], "bad")
        self.assertEqual(self.j.try_pin("x")[0], "bad")
        self.assertEqual(self.j.try_pin("x")[0], "locked")
        self.assertEqual(self.j.try_pin("1234")[0], "locked")
        os.remove(self.j.LOCK_FILE)
        self.assertEqual(self.j.try_pin("1234"), ("ok", 0))

    def test_save_config(self):
        self.j.CONFIG = os.path.join(self.j.CONFIG_DIR, "config")
        self.j.save_config("http://x/v1/", "key1", "model1")
        text = Path(self.j.CONFIG).read_text(encoding="utf-8")
        self.assertIn('JARVIS_API_KEY="key1"', text)
        self.assertEqual(stat.S_IMODE(os.stat(self.j.CONFIG).st_mode), 0o600)
        self.assertEqual((self.j.BASE_URL, self.j.API_KEY, self.j.MODEL), ("http://x/v1", "key1", "model1"))
        with self.assertRaises(ValueError):
            self.j.save_config("http://x", 'bad"key', "m")

    def test_process_simple_exit_and_macro(self):
        self.j.MACROS = os.path.join(self.j.CONFIG_DIR, "macros.json")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertFalse(self.j.process("time", []))
            self.assertFalse(self.j.process("   ", []))
            self.assertFalse(self.j.process("макрос t1 = echo macro-ok", []))
            self.assertFalse(self.j.process("t1", []))
            self.assertTrue(self.j.process("выход", []))
        out = buf.getvalue()
        self.assertIn("Сейчас", out)
        self.assertIn("macro-ok", out)
        self.assertIn("До свидания", out)

    def test_stop_kills_running_command(self):
        self.j.STOP.clear()
        timer = threading.Timer(1.0, self.j.STOP.set)
        timer.start()
        self.addCleanup(self.j.STOP.clear)
        started = time.time()
        out = self.j.run_logged("sleep 30")
        self.assertIn("остановлено", out)
        self.assertLess(time.time() - started, 10)

    def test_ask_ai_respects_stop(self):
        self.j.STOP.set()
        self.addCleanup(self.j.STOP.clear)
        history = []
        self.assertTrue(self.j.ask_ai(history, "что-нибудь"))


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = Path(self.tmp.name)
        self.log = self.bin / "calls.log"
        p = mock.patch.dict(os.environ, {"PATH": str(self.bin)})
        p.start()
        self.addCleanup(p.stop)

    def stub(self, name, body='echo "$0 $@" >> "%s"'):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + (body % self.log if "%s" in body else body) + "\n")
        path.chmod(0o755)

    def calls(self):
        end = time.time() + 3
        while time.time() < end and not self.log.exists():
            threading.Event().wait(0.05)
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_chromium_preferred_as_app_window(self):
        self.stub("chromium")
        self.stub("firefox")
        self.assertTrue(web.open_window("http://127.0.0.1:1/?t=x"))
        out = self.calls()
        self.assertEqual(len(out), 1)
        self.assertIn("chromium --app=http://127.0.0.1:1/?t=x", out[0])

    def test_firefox_new_window(self):
        self.stub("firefox")
        self.assertTrue(web.open_window("http://127.0.0.1:1/?t=x"))
        self.assertIn("firefox --new-window http://127.0.0.1:1/?t=x", self.calls()[0])

    def test_no_browser(self):
        self.assertFalse(web.open_window("http://127.0.0.1:1/"))

    def gsettings_stub(self, custom_list):
        self.stub("gsettings", f'''echo "$@" >> "{self.log}"
case "$1" in
  list-schemas) echo org.cinnamon.desktop.keybindings ;;
  get) echo "{custom_list}" ;;
esac''')

    def test_hotkey_empty_list(self):
        self.gsettings_stub("@as []")
        self.assertIn("Alt+7", web.set_hotkey())
        out = "\n".join(self.calls())
        self.assertIn("command jarvis", out)
        self.assertIn("binding ['<Alt>7']", out)
        self.assertIn("custom-list ['jarvis']", out)

    def test_hotkey_keeps_existing_and_is_idempotent(self):
        self.gsettings_stub("['custom0']")
        web.set_hotkey()
        self.assertIn("custom-list ['custom0', 'jarvis']", "\n".join(self.calls()))
        self.log.unlink()
        self.gsettings_stub("['custom0', 'jarvis']")
        web.set_hotkey()
        self.assertNotIn("set org.cinnamon.desktop.keybindings custom-list", "\n".join(self.calls()))

    def test_hotkey_not_cinnamon_or_no_gsettings(self):
        self.assertIn("gsettings", web.set_hotkey())
        self.stub("gsettings", 'echo org.gnome.desktop.interface')
        self.assertIn("Cinnamon", web.set_hotkey())


class WebBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = self.tmp.name
        cfg = os.path.join(home, "cfg")
        for p in (mock.patch.object(j, "CONFIG_DIR", cfg), mock.patch.object(j, "CONFIG", os.path.join(cfg, "config")),
                  mock.patch.object(j, "PIN_FILE", os.path.join(cfg, "pin")),
                  mock.patch.object(j, "LOCK_FILE", os.path.join(cfg, "pin.lock")),
                  mock.patch.object(j, "LOG", os.path.join(home, "log")),
                  mock.patch.object(j, "BASE_URL", ""), mock.patch.object(j, "API_KEY", ""),
                  mock.patch.object(j, "MODEL", ""), mock.patch.object(j, "AUTO", False),
                  mock.patch.object(j, "say", j.say), mock.patch.object(j, "confirm", j.confirm),
                  mock.patch.object(j, "allow_screen", j.allow_screen),
                  mock.patch.object(web.time, "sleep"),
                  mock.patch.object(web, "APP", web.App()),
                  mock.patch.object(sys, "stdout", web.OutWriter())):
            p.start()
            self.addCleanup(p.stop)
        j.PIN_FAILS["n"] = 0
        j.SCREEN.update(w=0, h=0, scale=1.0, always=False)
        j.STOP.clear()
        self.addCleanup(j.STOP.clear)
        self.server = web.make_server()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        web.install_hooks()

    # ---- помощники ----
    def call(self, method, path, body=None, cookie=None, host=None, csrf=True, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", web.APP.port, timeout=15)
        h = {"Host": host or f"127.0.0.1:{web.APP.port}"}
        if cookie:
            h["Cookie"] = f"jsid={cookie}"
        if method == "POST":
            h["Content-Type"] = "application/json"
            if csrf:
                h["X-Jarvis"] = "1"
        h.update(headers or {})
        conn.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            obj = json.loads(raw)
        except ValueError:
            obj = raw.decode("utf-8", "replace")
        return resp.status, resp, obj

    def login(self):
        status, resp, _ = self.call("GET", f"/?t={web.APP.token}")
        self.assertEqual(status, 302)
        m = re.search(r"jsid=([^;]+)", resp.getheader("Set-Cookie"))
        return m.group(1)

    def events(self, cookie, after=0):
        status, _, data = self.call("GET", f"/api/events?after={after}", cookie=cookie)
        self.assertEqual(status, 200)
        return data["events"]

    def wait_for(self, cookie, cond, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            evs = self.events(cookie)
            found = [e for e in evs if cond(e)]
            if found:
                return found[0]
            threading.Event().wait(0.1)
        self.fail(f"событие не появилось; было: {[e['type'] for e in self.events(cookie)]}")

    def fake_ai(self, replies):
        FakeAPI.replies = list(replies)
        FakeAPI.requests = []
        srv = HTTPServer(("127.0.0.1", 0), FakeAPI)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        j.BASE_URL = f"http://127.0.0.1:{srv.server_address[1]}"
        j.API_KEY, j.MODEL = "test", "test-model"

    def finish(self, cookie):
        """Закрывает зависшие вопросы и ждёт конца задачи, чтобы поток не остался висеть."""
        for _ in range(3):
            for cid in list(web.APP.pending):
                self.call("POST", "/api/answer", {"id": cid, "answer": "no"}, cookie=cookie)
        self.wait_for(cookie, lambda e: e["type"] == "done")


class AccessTests(WebBase):
    def test_cookie_and_one_time_token(self):
        self.assertEqual(self.call("GET", "/")[0], 403)
        self.assertEqual(self.call("GET", "/api/state")[0], 403)
        self.assertEqual(self.call("GET", "/?t=wrong")[0], 403)
        cookie = self.login()
        self.assertEqual(self.call("GET", f"/?t={web.APP.token}")[0], 403)  # второй раз ссылка не работает
        status, _, html = self.call("GET", "/", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn("Джарвис", html)
        self.assertEqual(self.call("GET", "/api/state", cookie="foreign")[0], 403)

    def test_host_origin_and_csrf(self):
        cookie = self.login()
        self.assertEqual(self.call("GET", "/api/state", cookie=cookie, host="evil.com")[0], 421)
        self.assertEqual(self.call("POST", "/api/stop", {}, cookie=cookie, csrf=False)[0], 403)
        self.assertEqual(self.call("POST", "/api/stop", {}, cookie=cookie, headers={"Origin": "http://evil.com"})[0], 403)
        origin = f"http://127.0.0.1:{web.APP.port}"
        self.assertEqual(self.call("POST", "/api/stop", {}, cookie=cookie, headers={"Origin": origin})[0], 200)
        self.assertEqual(self.call("POST", "/api/stop", {}, cookie=None)[0], 403)

    def test_bad_body(self):
        cookie = self.login()
        conn = http.client.HTTPConnection("127.0.0.1", web.APP.port, timeout=10)
        conn.request("POST", "/api/send", body="{не json".encode("utf-8"), headers={
            "Host": f"127.0.0.1:{web.APP.port}", "Cookie": f"jsid={cookie}", "X-Jarvis": "1"})
        self.assertEqual(conn.getresponse().status, 400)
        conn.close()

    def test_pin_gate(self):
        j.save_pin("1234")
        cookie = self.login()
        status, _, st = self.call("GET", "/api/state", cookie=cookie)
        self.assertEqual((status, st["unlocked"], st["pin_set"]), (200, False, True))
        self.assertEqual(self.call("GET", "/api/events?after=0", cookie=cookie)[0], 401)
        self.assertEqual(self.call("POST", "/api/send", {"text": "время"}, cookie=cookie)[0], 401)
        self.assertEqual(self.call("GET", "/api/settings", cookie=cookie)[0], 401)
        self.assertEqual(self.call("POST", "/api/unlock", {"pin": "0000"}, cookie=cookie)[2]["state"], "bad")
        self.assertEqual(self.call("GET", "/api/events?after=0", cookie=cookie)[0], 401)
        self.assertEqual(self.call("POST", "/api/unlock", {"pin": "1234"}, cookie=cookie)[2]["state"], "ok")
        self.assertEqual(self.call("GET", "/api/events?after=0", cookie=cookie)[0], 200)

    def test_pin_lockout(self):
        j.save_pin("1234")
        cookie = self.login()
        states = [self.call("POST", "/api/unlock", {"pin": "x"}, cookie=cookie)[2]["state"] for _ in range(3)]
        self.assertEqual(states, ["bad", "bad", "locked"])
        self.assertEqual(self.call("POST", "/api/unlock", {"pin": "1234"}, cookie=cookie)[2]["state"], "locked")
        self.assertEqual(self.call("GET", "/api/events?after=0", cookie=cookie)[0], 401)


class ChatTests(WebBase):
    def test_simple_command_and_clear(self):
        cookie = self.login()
        self.assertEqual(self.call("POST", "/api/send", {"text": "время"}, cookie=cookie)[0], 200)
        self.wait_for(cookie, lambda e: e["type"] == "say" and e["text"].startswith("Сейчас"))
        self.wait_for(cookie, lambda e: e["type"] == "done")
        evs = self.events(cookie)
        self.assertEqual(evs[0]["type"], "user")
        self.assertEqual(self.call("POST", "/api/clear", {}, cookie=cookie)[0], 200)
        self.assertEqual([e["type"] for e in self.events(cookie)], ["info"])

    def test_settings_and_pin_words_open_dialogs(self):
        cookie = self.login()
        self.call("POST", "/api/send", {"text": "настройка"}, cookie=cookie)
        self.call("POST", "/api/send", {"text": "пин"}, cookie=cookie)
        evs = self.events(cookie)
        self.assertEqual([(e["type"], e["what"]) for e in evs], [("open", "settings"), ("open", "pin")])

    def test_empty_and_huge_message_rejected(self):
        cookie = self.login()
        self.assertEqual(self.call("POST", "/api/send", {"text": "  "}, cookie=cookie)[0], 400)
        self.assertEqual(self.call("POST", "/api/send", {"text": "я" * 5000}, cookie=cookie)[0], 400)

    def test_ai_command_confirm_yes(self):
        self.fake_ai(['{"say":"запускаю","run":"echo hi-web"}', '{"say":"готово","run":""}'])
        cookie = self.login()
        self.call("POST", "/api/send", {"text": "скажи привет"}, cookie=cookie)
        card = self.wait_for(cookie, lambda e: e["type"] == "confirm")
        self.assertEqual((card["kind"], card["detail"]), ("command", "echo hi-web"))
        self.call("POST", "/api/answer", {"id": card["id"], "answer": "yes"}, cookie=cookie)
        self.wait_for(cookie, lambda e: e["type"] == "done")
        evs = self.events(cookie)
        self.assertTrue(any(e["type"] == "out" and "hi-web" in e["text"] for e in evs))
        self.assertTrue(any(e["type"] == "say" and e["text"] == "готово" for e in evs))
        self.assertTrue(any(e["type"] == "confirm_done" and e["answer"] == "yes" for e in evs))

    def test_ai_command_confirm_no(self):
        self.fake_ai(['{"say":"запускаю","run":"echo must-not-run"}'])
        cookie = self.login()
        self.call("POST", "/api/send", {"text": "сделай"}, cookie=cookie)
        card = self.wait_for(cookie, lambda e: e["type"] == "confirm")
        self.call("POST", "/api/answer", {"id": card["id"], "answer": "no"}, cookie=cookie)
        self.wait_for(cookie, lambda e: e["type"] == "done")
        evs = self.events(cookie)
        outs = [e["text"] for e in evs if e["type"] == "out"]
        self.assertFalse(any(t.strip() == "must-not-run" or t.startswith("[код") for t in outs))
        self.assertTrue(any(e["type"] == "say" and e["text"] == "Отменено." for e in evs))
        self.assertEqual(self.call("POST", "/api/answer", {"id": card["id"], "answer": "yes"}, cookie=cookie)[0], 404)

    def test_stop_button(self):
        self.fake_ai(['{"say":"жду","run":"sleep 30"}', '{"say":"x","run":""}'])
        cookie = self.login()
        self.call("POST", "/api/send", {"text": "подожди"}, cookie=cookie)
        card = self.wait_for(cookie, lambda e: e["type"] == "confirm")
        self.call("POST", "/api/answer", {"id": card["id"], "answer": "yes"}, cookie=cookie)
        self.call("POST", "/api/stop", {}, cookie=cookie)
        self.wait_for(cookie, lambda e: e["type"] == "done", timeout=15)
        self.assertTrue(any(e["type"] == "out" and "остановлено" in e["text"] for e in self.events(cookie)))

    def test_busy_returns_409(self):
        self.fake_ai(['{"say":"a","run":"echo x"}'])
        cookie = self.login()
        self.call("POST", "/api/send", {"text": "первая"}, cookie=cookie)
        self.wait_for(cookie, lambda e: e["type"] == "confirm")
        self.assertEqual(self.call("POST", "/api/send", {"text": "вторая"}, cookie=cookie)[0], 409)
        self.assertEqual(self.call("POST", "/api/clear", {}, cookie=cookie)[0], 409)
        self.finish(cookie)

    def test_screen_confirm_always(self):
        cookie = self.login()
        result = []
        t = threading.Thread(target=lambda: result.append(web.web_allow_screen("click (1,2)")))
        t.start()
        card = self.wait_for(cookie, lambda e: e["type"] == "confirm")
        self.assertEqual((card["kind"], card["options"]), ("screen", ["yes", "always", "no"]))
        self.call("POST", "/api/answer", {"id": card["id"], "answer": "always"}, cookie=cookie)
        t.join(5)
        self.assertEqual(result, [True])
        self.assertTrue(j.SCREEN["always"])
        self.assertTrue(web.web_allow_screen("ещё одно"))  # без нового вопроса
        self.assertEqual(len([e for e in self.events(cookie) if e["type"] == "confirm"]), 1)

    def test_dangerous_screen_text_always_asks(self):
        cookie = self.login()
        j.SCREEN["always"] = True
        result = []
        t = threading.Thread(target=lambda: result.append(web.web_allow_screen("type", danger=True)))
        t.start()
        card = self.wait_for(cookie, lambda e: e["type"] == "confirm")
        self.assertEqual(card["kind"], "danger")
        self.call("POST", "/api/answer", {"id": card["id"], "answer": "no"}, cookie=cookie)
        t.join(5)
        self.assertEqual(result, [False])


class SettingsTests(WebBase):
    def test_settings_roundtrip_never_returns_key(self):
        cookie = self.login()
        body = {"url": "https://openrouter.ai/api/v1", "key": "sk-test-123", "model": "openrouter/free"}
        status, _, data = self.call("POST", "/api/settings", body, cookie=cookie)
        self.assertEqual((status, data["ai_ready"]), (200, True))
        status, resp, raw = self.call("GET", "/api/settings", cookie=cookie)
        self.assertTrue(raw["has_key"])
        self.assertNotIn("sk-test-123", json.dumps(raw))
        self.assertEqual(stat.S_IMODE(os.stat(j.CONFIG).st_mode), 0o600)
        self.assertEqual(self.call("POST", "/api/settings", {**body, "url": "ftp://x"}, cookie=cookie)[0], 400)
        self.assertEqual(self.call("POST", "/api/settings", {**body, "key": ""}, cookie=cookie)[0], 200)  # прежний ключ
        status, _, _ = self.call("POST", "/api/settings", {**body, "key": "", "model": "other/model"}, cookie=cookie)
        self.assertEqual(status, 200)  # пустой ключ значит «оставить прежний»
        self.assertIn("sk-test-123", Path(j.CONFIG).read_text(encoding="utf-8"))
        self.assertIn("other/model", Path(j.CONFIG).read_text(encoding="utf-8"))

    def test_key_only_uses_defaults(self):
        cookie = self.login()
        status, _, data = self.call("POST", "/api/settings", {"key": "sk-only-key"}, cookie=cookie)
        self.assertEqual((status, data["ai_ready"]), (200, True))
        text = Path(j.CONFIG).read_text(encoding="utf-8")
        self.assertIn('JARVIS_BASE_URL="https://openrouter.ai/api/v1"', text)
        self.assertIn('JARVIS_MODEL="openrouter/free"', text)
        self.assertIn('JARVIS_VISION_MODEL="nvidia/nemotron-3.5-super-vl:free"', text)
        got = self.call("GET", "/api/settings", cookie=cookie)[2]
        self.assertEqual((got["model"], got["vision"]), ("openrouter/free", "nvidia/nemotron-3.5-super-vl:free"))

    def test_settings_rejects_injection(self):
        cookie = self.login()
        body = {"url": "https://x.example/v1", "key": 'a"\nJARVIS_MODEL="evil', "model": "m"}
        self.assertEqual(self.call("POST", "/api/settings", body, cookie=cookie)[0], 400)

    def test_pin_change_flow(self):
        cookie = self.login()
        self.assertEqual(self.call("POST", "/api/pin", {"new": "12"}, cookie=cookie)[0], 400)
        self.assertEqual(self.call("POST", "/api/pin", {"new": "abcd"}, cookie=cookie)[0], 200)
        self.assertTrue(j.check_pin("abcd"))
        self.assertEqual(self.call("POST", "/api/pin", {"current": "wrong", "new": "zzzz"}, cookie=cookie)[0], 403)
        self.assertEqual(self.call("POST", "/api/pin", {"current": "wrong", "remove": True}, cookie=cookie)[0], 403)
        self.assertTrue(j.pin_set_up())
        self.assertEqual(self.call("POST", "/api/pin", {"current": "abcd", "new": "zzzz"}, cookie=cookie)[0], 200)
        self.assertEqual(self.call("POST", "/api/pin", {"current": "zzzz", "remove": True}, cookie=cookie)[0], 200)
        self.assertFalse(j.pin_set_up())

    def test_voice_toggle_and_state(self):
        cookie = self.login()
        self.assertFalse(self.call("POST", "/api/voice", {"on": False}, cookie=cookie)[2]["voice_on"])
        st = self.call("GET", "/api/state", cookie=cookie)[2]
        self.assertTrue(st["unlocked"])
        self.assertFalse(st["voice_on"])
        self.assertNotIn("key", json.dumps(st).lower())


if __name__ == "__main__":
    unittest.main()
