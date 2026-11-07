"""Запуск: python3 -m unittest discover -s jarvis -p "test_*.py"

Проверки jarvis.py: PIN, разбор ответов ИИ, экран (с заглушками xdotool/scrot), цикл с поддельным API."""
import contextlib
import importlib.util
import io
import json
import os
import stat
import struct
import tempfile
import threading
import unittest
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

JARVIS = Path(__file__).resolve().parent / "jarvis.py"


def load_module(home):
    old = os.environ.get("HOME")
    os.environ["HOME"] = home
    try:
        spec = importlib.util.spec_from_file_location("jarvis_under_test", JARVIS)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if old is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old
    return mod


def make_png(w, h):
    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name
        self.j = load_module(self.home)
        cfg = os.path.join(self.home, "cfg")
        self.j.CONFIG_DIR = cfg
        self.j.PIN_FILE = os.path.join(cfg, "pin")
        self.j.LOCK_FILE = os.path.join(cfg, "pin.lock")
        self.j.LOG = os.path.join(self.home, "log")
        sleep = mock.patch.object(self.j.time, "sleep")
        sleep.start()
        self.addCleanup(sleep.stop)
        self.j.AUTO = False
        self.j.SCREEN.update(w=0, h=0, scale=1.0, always=False)
        out = contextlib.redirect_stdout(io.StringIO())
        out.__enter__()
        self.addCleanup(out.__exit__, None, None, None)


class PinTests(Base):
    def test_hash_and_verify(self):
        stored = self.j.hash_pin("1234")
        self.assertTrue(self.j.verify_pin("1234", stored))
        self.assertFalse(self.j.verify_pin("1235", stored))
        self.assertFalse(self.j.verify_pin("1234", "мусор"))
        self.assertNotIn("1234", stored)

    def test_save_check_and_mode(self):
        self.j.save_pin("secret")
        self.assertTrue(self.j.check_pin("secret"))
        self.assertFalse(self.j.check_pin("other"))
        self.assertEqual(stat.S_IMODE(os.stat(self.j.PIN_FILE).st_mode), 0o600)

    def test_unlock_without_pin(self):
        self.assertTrue(self.j.unlock())

    def test_unlock_ok_and_lockout(self):
        self.j.save_pin("1234")
        with mock.patch.object(self.j.getpass, "getpass", return_value="1234"):
            self.assertTrue(self.j.unlock())
        with mock.patch.object(self.j.getpass, "getpass", return_value="bad") as gp:
            self.assertFalse(self.j.unlock())
            self.assertEqual(gp.call_count, self.j.PIN_TRIES)
        self.assertGreater(self.j.lock_left(), 0)
        with mock.patch.object(self.j.getpass, "getpass", return_value="1234") as gp:
            self.assertFalse(self.j.unlock())  # блокировка действует даже с верным PIN
            gp.assert_not_called()

    def test_pin_command_set_change_remove(self):
        with mock.patch.object(self.j.getpass, "getpass", side_effect=["abcd", "abcd"]):
            self.assertTrue(self.j.pin_command("пин"))
        self.assertTrue(self.j.check_pin("abcd"))
        with mock.patch.object(self.j.getpass, "getpass", side_effect=["wrong"]):
            self.j.pin_command("пин удалить")
        self.assertTrue(self.j.pin_set_up())
        with mock.patch.object(self.j.getpass, "getpass", side_effect=["abcd"]):
            self.j.pin_command("пин удалить")
        self.assertFalse(self.j.pin_set_up())

    def test_pin_too_short_or_mismatch(self):
        with mock.patch.object(self.j.getpass, "getpass", side_effect=["12", "12"]):
            self.j.pin_command("пин")
        self.assertFalse(self.j.pin_set_up())
        with mock.patch.object(self.j.getpass, "getpass", side_effect=["abcd", "abce"]):
            self.j.pin_command("pin")
        self.assertFalse(self.j.pin_set_up())

    def test_not_a_pin_command(self):
        self.assertFalse(self.j.pin_command("пинать"))


class ParseTests(Base):
    def test_run_only(self):
        self.assertEqual(self.j.parse('{"say":"ок","run":"ls"}'), ("ок", "ls", None))

    def test_screen_action(self):
        t, c, a = self.j.parse('Вот: {"say":"кликаю","run":"","screen":{"do":"Click","x":5,"y":6}}')
        self.assertEqual((t, c), ("кликаю", ""))
        self.assertEqual(a, {"do": "click", "x": 5, "y": 6})

    def test_bad_screen_actions_ignored(self):
        for bad in ('{"say":"a","screen":{"do":"format_disk"}}', '{"say":"a","screen":"shot"}',
                    '{"say":"a","screen":null}'):
            self.assertIsNone(self.j.parse(bad)[2])

    def test_plain_text_and_non_dict(self):
        self.assertEqual(self.j.parse("просто текст"), ("просто текст", "", None))
        self.assertEqual(self.j.parse("[1,2]"), ("[1,2]", "", None))

    def test_english_aliases(self):
        self.assertEqual(self.j.to_ru("open browser"), "открой browser")
        self.assertEqual(self.j.to_ru("Louder"), "громче")
        self.assertEqual(self.j.to_ru("volume 50"), "громкость 50")
        self.assertEqual(self.j.to_ru("привет"), "привет")


class ScreenBase(Base):
    def setUp(self):
        super().setUp()
        self.stubs = os.path.join(self.home, "stubs")
        os.makedirs(self.stubs)
        self.real = os.path.join(self.home, "real.png")
        self.small = os.path.join(self.home, "small.png")
        Path(self.real).write_bytes(make_png(200, 100))
        Path(self.small).write_bytes(make_png(128, 64))
        self.xlog = os.path.join(self.home, "xdotool.log")
        self._stub("xdotool", f'echo "$@" >> "{self.xlog}"')
        self._stub("scrot", f'cp "{self.real}" "$1"')
        self._stub("convert", f'for last; do :; done; cp "{self.small}" "$last"')
        env = {"PATH": self.stubs + os.pathsep + os.environ.get("PATH", ""), "DISPLAY": ":0"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("XDG_SESSION_TYPE", None)
        self.j.SHOT_MAX_WIDTH = 128

    def _stub(self, name, body):
        path = os.path.join(self.stubs, name)
        Path(path).write_text("#!/bin/sh\n" + body + "\n")
        os.chmod(path, 0o755)

    def xcalls(self):
        return Path(self.xlog).read_text().splitlines() if os.path.exists(self.xlog) else []


class ScreenTests(ScreenBase):
    def test_png_size(self):
        self.assertEqual(self.j.png_size(make_png(7, 9)), (7, 9))
        with self.assertRaises(ValueError):
            self.j.png_size(b"not a png at all, definitely not")

    def test_problems(self):
        self.assertIsNone(self.j.screen_problem())
        os.environ["XDG_SESSION_TYPE"] = "wayland"
        self.assertIn("Wayland", self.j.screen_problem())
        os.environ["XDG_SESSION_TYPE"] = "x11"
        del os.environ["DISPLAY"]
        self.assertIn("DISPLAY", self.j.screen_problem())

    def test_shot_scale_and_click(self):
        data, w, h = self.j.take_shot()
        self.assertEqual((w, h), (128, 64))
        self.assertAlmostEqual(self.j.SCREEN["scale"], 200 / 128)
        self.assertEqual(self.j.png_size(data), (128, 64))
        self.assertEqual(self.j.screen_do({"do": "click", "x": 64, "y": 32}), "Готово.")
        self.assertEqual(self.xcalls(), ["mousemove 100 50", "click 1"])

    def test_click_before_shot_and_out_of_range(self):
        self.assertIn("скриншот", self.j.screen_do({"do": "click", "x": 1, "y": 1}))
        self.j.take_shot()
        self.assertIn("вне экрана", self.j.screen_do({"do": "click", "x": 500, "y": 1}))
        self.assertIn("ошибка", self.j.screen_do({"do": "click", "x": "abc", "y": 1}))
        self.assertEqual(self.xcalls(), [])

    def test_type_key_scroll(self):
        self.assertEqual(self.j.screen_do({"do": "type", "text": "привет мир"}), "Готово.")
        self.assertEqual(self.j.screen_do({"do": "key", "keys": "ctrl+l"}), "Готово.")
        self.assertEqual(self.j.screen_do({"do": "scroll", "dy": -3}), "Готово.")
        self.assertEqual(self.j.screen_do({"do": "scroll", "dy": 2}), "Готово.")
        self.assertEqual(self.xcalls(), ["type --delay 20 -- привет мир", "key ctrl+l",
                                         "click --repeat 3 4", "click --repeat 2 5"])

    def test_bad_input_rejected(self):
        self.assertIn("ошибка", self.j.screen_do({"do": "key", "keys": "ctrl+l; rm -rf /"}))
        self.assertIn("ошибка", self.j.screen_do({"do": "type", "text": ""}))
        self.assertIn("ошибка", self.j.screen_do({"do": "scroll", "dy": 0}))
        self.assertEqual(self.xcalls(), [])

    def test_decline_does_nothing(self):
        history = []
        with mock.patch("builtins.input", return_value="n"):
            self.assertFalse(self.j.handle_screen(history, {"do": "type", "text": "x"}))
        self.assertEqual(self.xcalls(), [])
        self.assertIn("отклонил", history[-1]["content"])

    def test_always_answer(self):
        with mock.patch("builtins.input", return_value="a") as inp:
            self.assertTrue(self.j.allow_screen("что-то"))
            self.assertTrue(self.j.allow_screen("ещё"))
            self.assertEqual(inp.call_count, 1)

    def test_dangerous_text_still_asks_in_auto(self):
        self.j.AUTO = True
        history = []
        with mock.patch("builtins.input", return_value="n"):
            self.assertFalse(self.j.handle_screen(history, {"do": "type", "text": "sudo rm -rf /home"}))
        self.assertEqual(self.xcalls(), [])

    def test_log_hides_typed_text(self):
        self.j.AUTO = True
        self.j.handle_screen([], {"do": "type", "text": "мойпароль123"})
        log = Path(self.j.LOG).read_text()
        self.assertIn("type (12 символов)", log)
        self.assertNotIn("мойпароль123", log)

    def test_screen_unavailable_is_reported_to_ai(self):
        os.environ["XDG_SESSION_TYPE"] = "wayland"
        history = []
        self.assertTrue(self.j.handle_screen(history, {"do": "shot"}))
        self.assertIn("Wayland", history[-1]["content"])

    def test_strip_old_images(self):
        img = lambda: {"role": "user", "content": [{"type": "text", "text": "t"}, {"type": "image_url"}]}  # noqa: E731
        history = [img(), {"role": "assistant", "content": "a"}, img()]
        self.j.strip_old_images(history)
        self.assertIsInstance(history[0]["content"], str)
        self.assertIsInstance(history[2]["content"], list)


class FakeAPI(BaseHTTPRequestHandler):
    replies = []
    requests = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeAPI.requests.append(body)
        reply = FakeAPI.replies.pop(0)
        data = json.dumps({"choices": [{"message": {"content": reply}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class AgentLoopTests(ScreenBase):
    def setUp(self):
        super().setUp()
        FakeAPI.requests = []
        self.server = HTTPServer(("127.0.0.1", 0), FakeAPI)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.j.BASE_URL = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.j.API_KEY, self.j.MODEL, self.j.VISION_MODEL = "test", "test-model", "vision-model"
        self.j.AUTO = True

    def test_shot_click_done(self):
        FakeAPI.replies = [
            '{"say":"смотрю","run":"","screen":{"do":"shot"}}',
            '{"say":"кликаю","run":"","screen":{"do":"click","x":64,"y":32}}',
            '{"say":"готово","run":"","screen":{"do":"shot"}}',
            '{"say":"Всё сделано","run":"","screen":null}',
        ]
        history = []
        self.assertTrue(self.j.ask_ai(history, "нажми в центре"))
        self.assertEqual(self.xcalls(), ["mousemove 100 50", "click 1"])
        self.assertEqual(len(FakeAPI.requests), 4)
        first = FakeAPI.requests[0]["messages"]
        self.assertFalse(any(isinstance(m["content"], list) for m in first))
        second = FakeAPI.requests[1]["messages"]
        parts = [p for m in second if isinstance(m["content"], list) for p in m["content"]]
        self.assertEqual([p["type"] for p in parts], ["text", "image_url"])
        self.assertTrue(parts[1]["image_url"]["url"].startswith("data:image/png;base64,"))
        last = FakeAPI.requests[3]["messages"]
        images = [p for m in last if isinstance(m["content"], list) for p in m["content"] if p["type"] == "image_url"]
        self.assertEqual(len(images), 1)  # старый скриншот убран
        self.assertEqual(self.j.SCREEN["scale"], 200 / 128)
        # без скриншота в запросе модель для чата, со скриншотом модель для экрана
        self.assertEqual([r["model"] for r in FakeAPI.requests],
                         ["test-model", "vision-model", "vision-model", "vision-model"])

    def test_run_command_still_works(self):
        FakeAPI.replies = ['{"say":"пишу","run":"echo hello-jarvis"}', '{"say":"готово","run":""}']
        history = []
        self.assertTrue(self.j.ask_ai(history, "скажи привет"))
        self.assertIn("hello-jarvis", history[-2]["content"])

    def test_http_error_message(self):
        self._boom(401, "401", "Ключ не подошёл")

    def test_rate_limit_message(self):
        self._boom(429, "429", "Лимит бесплатной модели")

    def _boom(self, code, *expected):
        class Boom(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                self.send_response(code)
                self.end_headers()

            def log_message(self, *args):
                pass
        srv = HTTPServer(("127.0.0.1", 0), Boom)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        self.j.BASE_URL = f"http://127.0.0.1:{srv.server_address[1]}"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertTrue(self.j.ask_ai([], "привет"))
        for text in expected:
            self.assertIn(text, buf.getvalue())


if __name__ == "__main__":
    unittest.main()
