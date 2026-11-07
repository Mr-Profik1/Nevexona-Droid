#!/usr/bin/env python3
"""Окно Джарвиса: чат в браузере. Сервер слушает только 127.0.0.1, вход по одноразовой ссылке.

Запуск: jarvis (окно), jarvis --cli или jarvis-cli (терминал).
Защита: страница открывается один раз по секретной ссылке (потом работает по cookie), все запросы
проверяют Host, Origin и служебный заголовок, а при заданном PIN сначала нужен PIN.
"""
import hmac
import http.cookies
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jarvis as j  # noqa: E402

IDLE_EXIT = 180  # секунд без обращений окна, после этого сервер сам закрывается
START_EXIT = 180  # секунд ждать, пока окно откроется
MAX_EVENTS = 2000
MAX_BODY = 1_000_000
PRESET_MODELS = ["openrouter/free", "nvidia/nemotron-3.5-super-vl:free", "nvidia/nemotron-3-ultra-550b-a55b:free"]


class App:
    def __init__(self):
        self.lock = threading.Lock()
        self.events = []
        self.next_id = 1
        self.history = []
        self.busy = False
        self.pending = {}
        self.sessions = {}  # cookie -> разблокирована ли сессия
        self.token = secrets.token_urlsafe(24)
        self.token_used = False
        self.voice_on = True
        self.last_poll = None
        self.started = time.time()
        self.port = 0
        self.quit = threading.Event()


APP = App()


def emit(etype, /, **data):
    with APP.lock:
        eid = APP.next_id
        APP.next_id += 1
        APP.events.append({"id": eid, "type": etype, **data})
        if len(APP.events) > MAX_EVENTS:
            del APP.events[:MAX_EVENTS // 4]
    return eid


class OutWriter:
    """Всё, что печатает ядро (вывод команд и т.п.), попадает в чат построчно."""

    def __init__(self):
        self.buf = ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            emit("out", text=line)
        return len(s)

    def flush(self):
        if self.buf:
            emit("out", text=self.buf)
            self.buf = ""


def web_say(text):
    emit("say", text=text)
    if text and APP.voice_on and shutil.which("espeak-ng"):
        lang = "en" if re.search(r"[A-Za-z]", text) and not re.search(r"[А-Яа-яЁё]", text) else "ru"
        subprocess.Popen(["espeak-ng", "-v", lang, text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ask_user(kind, text, detail=None, options=("yes", "no")):
    """Показывает в чате карточку с вопросом и ждёт ответ. Возвращает yes, always, no или timeout."""
    cid = emit("confirm", kind=kind, text=text, detail=detail, options=list(options))
    slot = {"event": threading.Event(), "answer": None}
    APP.pending[cid] = slot
    deadline = time.time() + 600
    while not slot["event"].wait(0.3):
        if j.STOP.is_set() or time.time() > deadline:
            break
    answer = slot["answer"] or "timeout"
    APP.pending.pop(cid, None)
    emit("confirm_done", cid=cid, answer=answer)
    return answer


def web_confirm(question, detail=None):
    return ask_user("command", question.strip(), detail) == "yes"


def web_allow_screen(desc, danger=False):
    if danger:
        return ask_user("danger", f"Опасно: {desc}") == "yes"
    if j.AUTO or j.SCREEN["always"]:
        return True
    answer = ask_user("screen", f"Экран: {desc}", options=("yes", "always", "no"))
    if answer == "always":
        j.SCREEN["always"] = True
    return answer in ("yes", "always")


def install_hooks():
    j.say = web_say
    j.confirm = web_confirm
    j.allow_screen = web_allow_screen


def start_task(text):
    """Запускает фразу в фоне. False, если Джарвис ещё занят предыдущей задачей."""
    with APP.lock:
        if APP.busy:
            return False
        APP.busy = True
    j.STOP.clear()
    emit("user", text=text)

    def work():
        try:
            if j.process(text, APP.history):
                emit("info", text="Можно закрывать окно.")
                APP.quit.set()
        except Exception as e:  # noqa: BLE001
            emit("info", text=f"Ошибка: {e}")
        finally:
            try:
                sys.stdout.flush()
            except Exception:  # noqa: BLE001
                pass
            with APP.lock:
                APP.busy = False
            emit("done")

    threading.Thread(target=work, daemon=True).start()
    return True


def state_for(sid):
    unlocked = APP.sessions.get(sid, False)
    st = {"unlocked": unlocked, "pin_set": j.pin_set_up(), "lock_left": j.lock_left()}
    if unlocked:
        st.update(ai_ready=j.ai_ready(), model=j.MODEL, voice_available=bool(shutil.which("espeak-ng")),
                  voice_on=APP.voice_on, busy=APP.busy, auto=j.AUTO, screen_problem=j.screen_problem())
    return st


class Handler(BaseHTTPRequestHandler):
    server_version = "Jarvis"
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    # ---- вспомогательное ----
    def origins(self):
        return {f"127.0.0.1:{APP.port}", f"localhost:{APP.port}"}

    def send_bytes(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                         "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code, obj, headers=None):
        self.send_bytes(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), headers=headers)

    def sid(self):
        cookie = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("jsid")
        return morsel.value if morsel and morsel.value in APP.sessions else None

    def host_ok(self):
        return self.headers.get("Host", "") in self.origins()

    # ---- GET ----
    def do_GET(self):  # noqa: N802
        if not self.host_ok():
            return self.send_json(421, {"error": "неверный Host"})
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        if url.path == "/":
            token = query.get("t", [""])[0]
            if token:
                if not APP.token_used and hmac.compare_digest(token, APP.token):
                    APP.token_used = True
                    sid = secrets.token_urlsafe(32)
                    APP.sessions[sid] = not j.pin_set_up()
                    return self.send_bytes(302, b"", "text/plain", {
                        "Location": "/",
                        "Set-Cookie": f"jsid={sid}; HttpOnly; SameSite=Strict; Path=/"})
                return self.send_bytes(403, "Ссылка уже использована. Запустите jarvis заново.".encode(),
                                       "text/plain; charset=utf-8")
            if self.sid():
                return self.send_bytes(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return self.send_bytes(403, "Откройте Джарвиса командой jarvis.".encode(), "text/plain; charset=utf-8")
        sid = self.sid()
        if not sid:
            return self.send_json(403, {"error": "нет доступа"})
        if url.path == "/api/state":
            return self.send_json(200, state_for(sid))
        if not APP.sessions[sid]:
            return self.send_json(401, {"error": "нужен PIN"})
        if url.path == "/api/events":
            try:
                after = int(query.get("after", ["0"])[0])
            except ValueError:
                after = 0
            APP.last_poll = time.time()
            with APP.lock:
                events = [e for e in APP.events if e["id"] > after]
                last, busy = APP.next_id - 1, APP.busy
            return self.send_json(200, {"events": events, "last": last, "busy": busy})
        if url.path == "/api/settings":
            return self.send_json(200, {"url": j.BASE_URL, "model": j.MODEL, "vision": j.VISION_MODEL,
                                        "has_key": bool(j.API_KEY), "models": PRESET_MODELS})
        return self.send_json(404, {"error": "не найдено"})

    # ---- POST ----
    def do_POST(self):  # noqa: N802
        if not self.host_ok():
            return self.send_json(421, {"error": "неверный Host"})
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlparse(origin).netloc not in self.origins():
            return self.send_json(403, {"error": "чужой источник"})
        if self.headers.get("X-Jarvis") != "1":
            return self.send_json(403, {"error": "нет служебного заголовка"})
        sid = self.sid()
        if not sid:
            return self.send_json(403, {"error": "нет доступа"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > MAX_BODY:
                return self.send_json(413, {"error": "слишком большой запрос"})
            body = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except (ValueError, json.JSONDecodeError):
            return self.send_json(400, {"error": "неверный запрос"})
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/unlock":
            if not j.pin_set_up():
                APP.sessions[sid] = True
                return self.send_json(200, {"state": "ok", "left": 0})
            state, left = j.try_pin(str(body.get("pin", "")))
            if state == "ok":
                APP.sessions[sid] = True
            elif state == "bad":
                time.sleep(1)
            return self.send_json(200, {"state": state, "left": left})
        if not APP.sessions[sid]:
            return self.send_json(401, {"error": "нужен PIN"})
        return self.route_post(path, body)

    def route_post(self, path, body):
        if path == "/api/send":
            text = str(body.get("text", "")).strip()
            if not text or len(text) > 4000:
                return self.send_json(400, {"error": "пустое или слишком длинное сообщение"})
            low = text.lower()
            if low in ("настройка", "setup"):
                emit("open", what="settings")
                return self.send_json(200, {"ok": True})
            if low in ("пин", "pin", "пин удалить", "pin remove"):
                emit("open", what="pin")
                return self.send_json(200, {"ok": True})
            if not start_task(text):
                return self.send_json(409, {"error": "занят предыдущей задачей"})
            return self.send_json(200, {"ok": True})
        if path == "/api/answer":
            slot = APP.pending.get(body.get("id"))
            answer = body.get("answer")
            if slot is None or answer not in ("yes", "always", "no"):
                return self.send_json(404, {"error": "вопрос уже закрыт"})
            slot["answer"] = answer
            slot["event"].set()
            return self.send_json(200, {"ok": True})
        if path == "/api/stop":
            j.STOP.set()
            return self.send_json(200, {"ok": True})
        if path == "/api/voice":
            APP.voice_on = bool(body.get("on"))
            return self.send_json(200, {"voice_on": APP.voice_on})
        if path == "/api/clear":
            with APP.lock:
                if APP.busy:
                    return self.send_json(409, {"error": "занят предыдущей задачей"})
                APP.history.clear()
                APP.events.clear()
            j.SCREEN["always"] = False
            emit("info", text="Разговор очищен.")
            return self.send_json(200, {"ok": True})
        if path == "/api/settings":
            url = str(body.get("url", "")).strip() or j.DEFAULT_URL
            key = str(body.get("key", "")).strip() or j.API_KEY
            model = str(body.get("model", "")).strip() or j.DEFAULT_MODEL
            vision = str(body.get("vision", "")).strip() or j.DEFAULT_VISION_MODEL
            if not re.match(r"https?://\S+$", url) or not key:
                return self.send_json(400, {"error": "нужен ключ и адрес (http или https)"})
            try:
                j.save_config(url, key, model, vision)
            except (ValueError, OSError) as e:
                return self.send_json(400, {"error": str(e)})
            return self.send_json(200, {"ok": True, "ai_ready": j.ai_ready()})
        if path == "/api/pin":
            return self.change_pin(body)
        return self.send_json(404, {"error": "не найдено"})

    def change_pin(self, body):
        if j.pin_set_up():
            state, left = j.try_pin(str(body.get("current", "")))
            if state == "locked":
                return self.send_json(429, {"error": f"Подождите {left} с."})
            if state == "bad":
                time.sleep(1)
                return self.send_json(403, {"error": "Неверный текущий PIN."})
        if body.get("remove"):
            try:
                os.remove(j.PIN_FILE)
            except OSError:
                pass
            return self.send_json(200, {"ok": True, "pin_set": False})
        new = str(body.get("new", ""))
        if len(new) < 4:
            return self.send_json(400, {"error": "PIN короче 4 символов."})
        j.save_pin(new)
        return self.send_json(200, {"ok": True, "pin_set": True})


def make_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    APP.port = server.server_address[1]
    return server


def watchdog(server):
    while not APP.quit.wait(2):
        now = time.time()
        if APP.last_poll is None and now - APP.started > START_EXIT:
            break
        if APP.last_poll is not None and now - APP.last_poll > IDLE_EXIT and not APP.busy:
            break
    server.shutdown()


def open_window(url):
    # Chromium и родственные умеют окно без вкладок и адресной строки (--app)
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
                 "brave-browser", "microsoft-edge"):
        path = shutil.which(name)
        if path:
            subprocess.Popen([path, f"--app={url}", "--window-size=1000,800"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return True
    # Firefox (браузер по умолчанию в Linux Mint): отдельное окно
    path = shutil.which("firefox")
    if path:
        subprocess.Popen([path, "--new-window", url], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    for opener in ("xdg-open", "sensible-browser"):
        path = shutil.which(opener)
        if path:
            subprocess.Popen([path, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return True
    return False


def load_gtk():
    """GTK3 и WebKitGTK для настоящего окна приложения (без браузера). None, если библиотек нет."""
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        for ver in ("4.1", "4.0"):
            try:
                gi.require_version("WebKit2", ver)
                break
            except ValueError:
                continue
        else:
            return None
        from gi.repository import Gtk, WebKit2
        return Gtk, WebKit2
    except (ImportError, ValueError):
        return None


def open_external(uri):
    """Ссылки с чужих сайтов открываем в браузере по умолчанию, а не внутри окна Джарвиса."""
    if not uri.startswith(("http://", "https://")):
        return False
    opener = shutil.which("xdg-open")
    if not opener:
        return False
    subprocess.Popen([opener, uri], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    return True


def run_native_window(url, mods):
    """Окно приложения на GTK + WebKit. Возвращает True, когда окно было показано и закрыто,
    и False, если окно не удалось создать (нет экрана и т.п.): тогда нужен запасной способ."""
    Gtk, WebKit2 = mods
    try:
        ok = Gtk.init_check()
        if isinstance(ok, tuple):
            ok = ok[0]
        if not ok:
            return False
        win = Gtk.Window(title="Джарвис")
        win.set_default_size(1000, 800)
        win.set_icon_name("jarvis")
        view = WebKit2.WebView()
    except Exception:  # noqa: BLE001 - любая ошибка GTK означает: используем запасной способ
        return False
    local = f"http://127.0.0.1:{APP.port}/"

    def on_policy(_view, decision, dtype):
        if dtype not in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION,
                         WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
            return False
        uri = decision.get_navigation_action().get_request().get_uri() or ""
        if uri.startswith(local):
            return False
        decision.ignore()
        open_external(uri)
        return True

    view.connect("decide-policy", on_policy)
    win.connect("destroy", lambda *_: Gtk.main_quit())
    win.add(view)
    view.load_uri(url)
    win.show_all()
    Gtk.main()
    return True


def set_hotkey(binding="<Alt>7"):
    """Горячая клавиша запуска окна в Cinnamon (Linux Mint). Возвращает текст результата."""
    gs = shutil.which("gsettings")
    schema = "org.cinnamon.desktop.keybindings"
    if not gs:
        return "Не найден gsettings: задайте сочетание вручную в Параметры → Клавиатура → Сочетания."
    schemas = subprocess.run([gs, "list-schemas"], capture_output=True, text=True).stdout.split()
    if schema not in schemas:
        return "Это не Cinnamon: задайте сочетание клавиш вручную в настройках вашего рабочего стола."
    slot = "jarvis"
    path = f"/org/cinnamon/desktop/keybindings/custom-keybindings/{slot}/"
    item = f"{schema}.custom-keybinding:{path}"
    for key, value in (("name", "Джарвис"), ("command", "jarvis"), ("binding", f"['{binding}']")):
        subprocess.run([gs, "set", item, key, value], check=True)
    cur = subprocess.run([gs, "get", schema, "custom-list"], capture_output=True, text=True, check=True).stdout.strip()
    if f"'{slot}'" not in cur:
        names = re.findall(r"'([^']+)'", cur)
        subprocess.run([gs, "set", schema, "custom-list", str(names + [slot])], check=True)
    return f"Готово: {binding.replace('<', '').replace('>', '+')} открывает Джарвиса."


def main():
    if "--hotkey" in sys.argv:
        try:
            print(set_hotkey())
            return 0
        except (subprocess.CalledProcessError, OSError) as e:
            print(f"Не получилось задать сочетание: {e}")
            return 1
    if "--check" in sys.argv:
        problem = j.screen_problem()
        print("Управление экраном готово: X11, xdotool и скриншоты на месте." if not problem
              else "Управление экраном не готово: " + problem)
        return 0 if not problem else 1
    if "--version" in sys.argv:
        print("jarvis " + getattr(j, "VERSION", "?"))
        return 0
    if "--cli" in sys.argv:
        return j.main()
    if os.name != "posix":
        print("Работает только на Linux.")
        return 1
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        print("Нет экрана, запускаю режим терминала.")
        return j.main()
    if j.AUTO and not j.pin_set_up():
        print("Режим полного разрешения работает только с PIN. Запустите jarvis, задайте PIN (кнопка PIN) "
              "и запустите снова с --auto.")
        return 1
    server = make_server()
    install_hooks()
    sys.stdout = OutWriter()
    if j.ai_ready():
        emit("say", text="Привет. Что нужно сделать?")
    else:
        emit("say", text="Привет. Чтобы подключить ИИ, вставьте ключ OpenRouter в окне «Настройки». Остальное уже заполнено.")
    url = f"http://127.0.0.1:{APP.port}/?t={APP.token}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # Сначала настоящее окно приложения (GTK + WebKit); --browser или JARVIS_BROWSER=1 включает старый способ
    use_native = "--browser" not in sys.argv and not os.environ.get("JARVIS_BROWSER")
    mods = load_gtk() if use_native else None
    if mods and run_native_window(url, mods):
        APP.quit.set()
        server.shutdown()
        return 0
    if not open_window(url):
        sys.stderr.write(f"Не нашёл браузер. Откройте эту ссылку (одноразовая): {url}\n")
    try:
        watchdog(server)
    except KeyboardInterrupt:
        server.shutdown()
    return 0


INDEX_HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Джарвис</title>
<style>
:root{--bg:#0e1014;--panel:#161920;--panel2:#1d212a;--line:#272c38;--text:#e9ebf1;--muted:#8b93a7;
--accent:#ff8a1f;--accent2:#ffb15c;--ok:#3ddc97;--bad:#ff5d5d;--radius:16px}
*{box-sizing:border-box}
html,body{height:100%;margin:0}
body{background:radial-gradient(1200px 600px at 80% -10%,#2a1a0b 0,transparent 60%),var(--bg);color:var(--text);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans",sans-serif;display:flex;flex-direction:column}
button,input,textarea,select{font:inherit;color:inherit}
header{display:flex;align-items:center;gap:12px;padding:12px 18px;border-bottom:1px solid var(--line);
background:rgba(22,25,32,.85);backdrop-filter:blur(8px)}
.orb{width:30px;height:30px;border-radius:50%;flex:none;background:radial-gradient(circle at 35% 30%,#fff3e0,var(--accent) 45%,#b34a00);
box-shadow:0 0 18px rgba(255,138,31,.55)}
.busy .orb{animation:pulse 1.2s ease-in-out infinite}
@keyframes pulse{50%{box-shadow:0 0 30px rgba(255,138,31,.95);transform:scale(1.08)}}
h1{font-size:17px;margin:0;font-weight:650;letter-spacing:.2px}
.pill{font-size:12px;padding:3px 10px;border-radius:999px;border:1px solid var(--line);color:var(--muted);white-space:nowrap;
overflow:hidden;text-overflow:ellipsis;max-width:34vw}
.pill.ok{color:var(--ok);border-color:#1f4d3b}.pill.off{color:var(--accent2);border-color:#5a3a16}
.sp{flex:1}
.hb{background:none;border:1px solid var(--line);border-radius:10px;padding:6px 11px;color:var(--muted);cursor:pointer}
.hb:hover{color:var(--text);border-color:#3a4152}
#chat{flex:1;overflow-y:auto;padding:20px 18px 8px;display:flex;flex-direction:column;gap:12px;scroll-behavior:smooth}
.row{display:flex;gap:10px;max-width:860px;width:100%;margin:0 auto}
.row.user{justify-content:flex-end}
.av{width:26px;height:26px;border-radius:50%;flex:none;margin-top:4px;background:radial-gradient(circle at 35% 30%,#fff3e0,var(--accent) 50%,#b34a00)}
.bubble{padding:10px 14px;border-radius:var(--radius);max-width:80%;white-space:pre-wrap;word-wrap:break-word;overflow-wrap:anywhere}
.say .bubble{background:var(--panel2);border:1px solid var(--line);border-top-left-radius:6px}
.user .bubble{background:linear-gradient(135deg,var(--accent),#ff6a00);color:#1b0f02;font-weight:520;border-top-right-radius:6px}
details.out{max-width:860px;width:100%;margin:0 auto;background:#0b0d11;border:1px solid var(--line);border-radius:12px;padding:6px 12px}
details.out summary{cursor:pointer;color:var(--muted);font-size:13px;user-select:none}
details.out pre{margin:6px 0 4px;max-height:240px;overflow:auto;font:12.5px/1.45 ui-monospace,"DejaVu Sans Mono",Menlo,monospace;color:#c9d1e3;white-space:pre-wrap;word-break:break-all}
.card{max-width:860px;width:100%;margin:0 auto;border:1px solid #5a3a16;background:linear-gradient(180deg,#1f1810,#17130e);
border-radius:var(--radius);padding:14px 16px}
.card.danger{border-color:#7a2a2a;background:linear-gradient(180deg,#241313,#181010)}
.card .t{font-weight:600;margin-bottom:6px}
.card code{display:block;margin:8px 0 12px;padding:9px 11px;background:#0b0d11;border:1px solid var(--line);border-radius:10px;
font:12.5px/1.45 ui-monospace,"DejaVu Sans Mono",monospace;white-space:pre-wrap;word-break:break-all;max-height:160px;overflow:auto}
.btns{display:flex;gap:8px;flex-wrap:wrap}
.btn{border:1px solid var(--line);background:var(--panel2);padding:8px 16px;border-radius:10px;cursor:pointer}
.btn:hover{border-color:#3a4152}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#1b0f02;font-weight:650}
.btn.primary:hover{background:var(--accent2)}
.btn.bad{border-color:#6b2b2b;color:#ff9a9a}
.btn:disabled{opacity:.5;cursor:default}
.done{font-size:13px;color:var(--muted)}
.info{text-align:center;color:var(--muted);font-size:13px}
.dots{display:none;max-width:860px;width:100%;margin:0 auto;padding-left:36px}
.busy .dots{display:block}
.dots i{display:inline-block;width:7px;height:7px;margin-right:5px;border-radius:50%;background:var(--accent);opacity:.3;animation:b 1s infinite}
.dots i:nth-child(2){animation-delay:.15s}.dots i:nth-child(3){animation-delay:.3s}
@keyframes b{50%{opacity:1;transform:translateY(-3px)}}
.chips{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;margin:6px auto 0;max-width:860px}
.chip{border:1px solid var(--line);background:var(--panel);border-radius:999px;padding:6px 14px;cursor:pointer;color:var(--muted)}
.chip:hover{color:var(--text);border-color:var(--accent)}
.warn{max-width:860px;margin:0 auto;width:100%;font-size:13px;color:var(--accent2);text-align:center}
footer{padding:10px 18px 16px}
.comp{max-width:860px;margin:0 auto;display:flex;gap:10px;align-items:flex-end;background:var(--panel);border:1px solid var(--line);
border-radius:18px;padding:8px 8px 8px 16px}
.comp:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px rgba(255,138,31,.15)}
textarea{flex:1;background:none;border:none;outline:none;resize:none;max-height:150px;padding:6px 0;line-height:1.45}
#send{width:42px;height:42px;border-radius:50%;border:none;background:var(--accent);color:#1b0f02;cursor:pointer;font-size:20px;font-weight:700;flex:none}
#send:hover{background:var(--accent2)}
#send.stop{background:transparent;border:2px solid var(--bad);color:var(--bad);font-size:15px}
.hint{max-width:860px;margin:6px auto 0;text-align:center;font-size:12px;color:#5d6578}
.ov{position:fixed;inset:0;background:rgba(5,6,9,.72);display:none;align-items:center;justify-content:center;padding:18px;z-index:10}
.ov.show{display:flex}
.modal{width:min(440px,100%);background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:22px}
.modal h2{margin:0 0 4px;font-size:18px}
.modal p{margin:0 0 14px;color:var(--muted);font-size:13px}
label{display:block;font-size:12px;color:var(--muted);margin:12px 0 4px}
input,select{width:100%;background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:9px 11px;outline:none}
input:focus,select:focus{border-color:var(--accent)}
.err{color:var(--bad);font-size:13px;min-height:18px;margin-top:10px}
.modal .btns{margin-top:16px;justify-content:flex-end}
#lock{background:var(--bg)}
@media (max-width:560px){.pill{display:none}.bubble{max-width:92%}}
</style>
</head>
<body>
<header>
  <div class="orb"></div><h1>Джарвис</h1><span id="pill" class="pill">…</span>
  <div class="sp"></div>
  <button class="hb" id="bvoice" title="Озвучка ответов">Голос</button>
  <button class="hb" id="bset">Настройки</button>
  <button class="hb" id="bpin">PIN</button>
  <button class="hb" id="bclear">Очистить</button>
</header>
<main id="chat"><div class="dots"><i></i><i></i><i></i></div></main>
<footer>
  <div class="comp">
    <textarea id="inp" rows="1" placeholder="Напишите задачу по-русски или по-английски…" autofocus></textarea>
    <button id="send" title="Отправить">➤</button>
  </div>
  <div class="hint">Enter — отправить, Shift+Enter — новая строка</div>
</footer>

<div class="ov" id="lock"><div class="modal">
  <h2>Введите PIN</h2><p>Джарвис защищён PIN-кодом.</p>
  <input id="lpin" type="password" autocomplete="off" placeholder="PIN">
  <div class="err" id="lerr"></div>
  <div class="btns"><button class="btn primary" id="lgo">Войти</button></div>
</div></div>

<div class="ov" id="mset"><div class="modal">
  <h2>Подключение ИИ</h2><p>Любой сервис с OpenAI-совместимым API. Для действий на экране нужна модель с поддержкой изображений.</p>
  <label>Сервис</label>
  <select id="spreset">
    <option value="https://openrouter.ai/api/v1">OpenRouter</option>
    <option value="https://api.groq.com/openai/v1">Groq</option>
    <option value="https://generativelanguage.googleapis.com/v1beta/openai">Gemini</option>
    <option value="http://localhost:11434/v1">Ollama (локально)</option>
    <option value="">Другой адрес…</option>
  </select>
  <label>Адрес API</label><input id="surl" autocomplete="off">
  <label>Ключ <span id="skeyhint"></span></label><input id="skey" type="password" autocomplete="off">
  <label>Модель для чата (openrouter/free сам выбирает бесплатную)</label><input id="smodel" list="models" autocomplete="off">
  <label>Модель для действий на экране (должна видеть изображения)</label><input id="svision" list="models" autocomplete="off">
  <datalist id="models"></datalist>
  <div class="err" id="serr"></div>
  <div class="btns"><button class="btn" data-close="mset">Закрыть</button><button class="btn primary" id="ssave">Сохранить</button></div>
</div></div>

<div class="ov" id="mpin"><div class="modal">
  <h2>PIN-код</h2><p>Спрашивается при каждом открытии окна. 3 ошибки подряд блокируют вход на минуту.</p>
  <div id="pcurwrap"><label>Текущий PIN</label><input id="pcur" type="password" autocomplete="off"></div>
  <label>Новый PIN (минимум 4 символа)</label><input id="pnew" type="password" autocomplete="off">
  <label>Повторите новый PIN</label><input id="pnew2" type="password" autocomplete="off">
  <div class="err" id="perr"></div>
  <div class="btns"><button class="btn" data-close="mpin">Закрыть</button><button class="btn bad" id="prem">Снять PIN</button><button class="btn primary" id="psave">Сохранить</button></div>
</div></div>

<script>
"use strict";
const $=id=>document.getElementById(id);
const chat=$("chat"), inp=$("inp"), sendBtn=$("send");
let last=0, busy=false, st={}, outBox=null, started=false, polling=false;

async function api(path, body){
  const opt = body===undefined ? {} : {method:"POST", headers:{"Content-Type":"application/json","X-Jarvis":"1"}, body:JSON.stringify(body)};
  const r = await fetch(path, opt);
  let data = {}; try{ data = await r.json(); }catch(e){}
  return {status:r.status, data};
}
function el(tag, cls, text){ const e=document.createElement(tag); if(cls) e.className=cls; if(text!==undefined) e.textContent=text; return e; }
function add(node){ const near = chat.scrollHeight-chat.scrollTop-chat.clientHeight < 140; chat.insertBefore(node, chat.querySelector(".dots")); if(near) chat.scrollTop = chat.scrollHeight; }

function addSay(text){ outBox=null; const r=el("div","row say"); r.append(el("div","av"), el("div","bubble",text)); add(r); }
function addUser(text){ outBox=null; const r=el("div","row user"); r.append(el("div","bubble",text)); add(r); }
function addInfo(text){ outBox=null; add(el("div","info",text)); }
function addOut(text){
  if(!outBox){ const d=el("details","out"); d.open=true; d.append(el("summary","","Вывод")); const pre=el("pre"); d.append(pre); outBox={d,pre,n:0}; add(d); }
  outBox.pre.textContent += (outBox.n? "\n":"") + text; outBox.n++;
  outBox.d.querySelector("summary").textContent = "Вывод (" + outBox.n + " стр.)";
  if(outBox.n>12) outBox.d.open=false;
}
const cards={};
function addConfirm(ev){
  outBox=null;
  const c=el("div","card"+(ev.kind==="danger"?" danger":""));
  c.append(el("div","t",ev.text||"Выполнить?"));
  if(ev.detail){ c.append(el("code","",ev.detail)); }
  const b=el("div","btns");
  const labels={yes:"Выполнить",always:"Всегда в этой сессии",no:"Отмена"};
  (ev.options||["yes","no"]).forEach(o=>{
    const x=el("button","btn"+(o==="yes"?" primary":(o==="no"?" bad":"")),labels[o]);
    x.onclick=async()=>{ b.querySelectorAll("button").forEach(k=>k.disabled=true); await api("/api/answer",{id:ev.id,answer:o}); };
    b.append(x);
  });
  c.append(b); cards[ev.id]=c; add(c);
}
function closeConfirm(ev){
  const c=cards[ev.cid]; if(!c) return;
  const b=c.querySelector(".btns"); if(b){ const m={yes:"✓ Выполнено",always:"✓ Разрешено на сессию",no:"✗ Отменено",timeout:"Время вышло"}; b.replaceWith(el("div","done",m[ev.answer]||"")); }
  delete cards[ev.cid];
}

function handle(ev){
  started=true;
  switch(ev.type){
    case "say": addSay(ev.text); break;
    case "user": addUser(ev.text); break;
    case "out": addOut(ev.text); break;
    case "info": addInfo(ev.text); break;
    case "confirm": addConfirm(ev); break;
    case "confirm_done": closeConfirm(ev); break;
    case "open": openModal(ev.what==="pin"?"mpin":"mset"); break;
    case "done": outBox=null; break;
  }
}
function setBusy(b){
  busy=b; document.body.classList.toggle("busy",b);
  sendBtn.classList.toggle("stop",b); sendBtn.textContent=b?"■":"➤"; sendBtn.title=b?"Стоп":"Отправить";
}
function renderChips(){
  document.querySelectorAll(".chips").forEach(n=>n.remove());
  const box=el("div","chips");
  ["время","память","помощь","открой браузер"].forEach(t=>{ const c=el("button","chip",t); c.onclick=()=>send(t); box.append(c); });
  add(box);
}
async function pollOnce(){
  const {status,data}=await api("/api/events?after="+last);
  if(status===401){ await refreshState(); return; }
  if(status!==200) throw new Error("status "+status);
  document.querySelectorAll(".warn").forEach(n=>n.remove());
  const fresh = last===0;
  (data.events||[]).forEach(handle);
  if(data.last<last){ last=0; } else { last=data.last; }
  setBusy(!!data.busy);
  if(fresh && !document.querySelector(".chips") && (data.events||[]).filter(e=>e.type==="user").length===0) renderChips();
}
async function poll(){
  if(polling) return; polling=true;
  while(true){
    try{ await pollOnce(); }
    catch(e){ if(!document.querySelector(".warn")) add(el("div","warn","Связь с Джарвисом потеряна. Если окно было закрыто, запустите jarvis заново.")); }
    await new Promise(r=>setTimeout(r,400));
  }
}

async function send(text){
  text=(text||inp.value).trim(); if(!text) return;
  document.querySelectorAll(".chips").forEach(n=>n.remove());
  inp.value=""; fit();
  const {status,data}=await api("/api/send",{text});
  if(status===409) addInfo("Подождите, Джарвис ещё выполняет предыдущую задачу или нажмите «■».");
  else if(status!==200) addInfo(data.error||"Не отправилось.");
}
function fit(){ inp.style.height="auto"; inp.style.height=Math.min(inp.scrollHeight,150)+"px"; }
inp.addEventListener("input",fit);
inp.addEventListener("keydown",e=>{ if(e.key==="Enter"&&!e.shiftKey&&!e.isComposing){ e.preventDefault(); if(!busy) send(); } });
sendBtn.onclick=()=>{ if(busy) api("/api/stop",{}); else send(); };

function openModal(id){ $(id).classList.add("show"); const f=$(id).querySelector("input"); if(f) setTimeout(()=>f.focus(),50); if(id==="mset") loadSettings(); if(id==="mpin") renderPin(); }
function closeModal(id){ $(id).classList.remove("show"); inp.focus(); }
document.querySelectorAll("[data-close]").forEach(b=>b.onclick=()=>closeModal(b.dataset.close));
document.addEventListener("keydown",e=>{ if(e.key==="Escape"){ ["mset","mpin"].forEach(closeModal); } });

async function loadSettings(){
  $("serr").textContent=""; $("skey").value="";
  const {data}=await api("/api/settings");
  $("surl").value=data.url||"https://openrouter.ai/api/v1"; $("smodel").value=data.model||""; $("svision").value=data.vision||"";
  $("skeyhint").textContent=data.has_key?"(сохранён, оставьте пустым, чтобы не менять)":"";
  const dl=$("models"); dl.textContent=""; (data.models||[]).forEach(m=>{ const o=el("option"); o.value=m; dl.append(o); });
  const p=$("spreset"); p.value=[...p.options].some(o=>o.value===$("surl").value)?$("surl").value:"";
}
$("spreset").onchange=()=>{ if($("spreset").value) $("surl").value=$("spreset").value; else { $("surl").value=""; $("surl").focus(); } };
$("ssave").onclick=async()=>{
  const {status,data}=await api("/api/settings",{url:$("surl").value,key:$("skey").value,model:$("smodel").value,vision:$("svision").value});
  if(status===200){ closeModal("mset"); addInfo(data.ai_ready?"ИИ подключён.":"Сохранено."); refreshState(); }
  else $("serr").textContent=data.error||"Не сохранилось.";
};
function renderPin(){ $("perr").textContent=""; ["pcur","pnew","pnew2"].forEach(i=>$(i).value=""); $("pcurwrap").style.display=st.pin_set?"block":"none"; $("prem").style.display=st.pin_set?"inline-block":"none"; }
$("psave").onclick=async()=>{
  if($("pnew").value!==$("pnew2").value){ $("perr").textContent="Повтор не совпал."; return; }
  const {status,data}=await api("/api/pin",{current:$("pcur").value,new:$("pnew").value});
  if(status===200){ closeModal("mpin"); addInfo("PIN сохранён."); refreshState(); } else $("perr").textContent=data.error||"Не сохранилось.";
};
$("prem").onclick=async()=>{
  const {status,data}=await api("/api/pin",{current:$("pcur").value,remove:true});
  if(status===200){ closeModal("mpin"); addInfo("PIN снят."); refreshState(); } else $("perr").textContent=data.error||"Не получилось.";
};
$("bset").onclick=()=>openModal("mset"); $("bpin").onclick=()=>openModal("mpin");
$("bclear").onclick=async()=>{ const {status}=await api("/api/clear",{}); if(status===409) addInfo("Сначала остановите текущую задачу."); else { last=0; chat.querySelectorAll(".row,details.out,.card,.info,.chips,.warn").forEach(n=>n.remove()); outBox=null; } };
$("bvoice").onclick=async()=>{ const {data}=await api("/api/voice",{on:!st.voice_on}); st.voice_on=data.voice_on; paintHeader(); };

function paintHeader(){
  const p=$("pill");
  p.className="pill "+(st.ai_ready?"ok":"off");
  p.textContent=st.ai_ready?("ИИ: "+(st.model||"подключён")):"простой режим";
  const v=$("bvoice"); v.style.display=st.voice_available?"inline-block":"none"; v.textContent="Голос: "+(st.voice_on?"вкл":"выкл");
}
async function refreshState(){
  const {data}=await api("/api/state"); st=data;
  if(!st.unlocked){ $("lock").classList.add("show"); setTimeout(()=>$("lpin").focus(),50);
    if(st.lock_left) $("lerr").textContent="Слишком много попыток. Подождите "+st.lock_left+" с."; return; }
  $("lock").classList.remove("show"); paintHeader();
  if(!st.ai_ready && !window.setOpened){ window.setOpened=true; openModal("mset"); }
  if(st.screen_problem && !window.spNoted){ window.spNoted=true; addInfo("Управление экраном пока недоступно: "+st.screen_problem); }
  poll();
}
async function tryUnlock(){
  const {data}=await api("/api/unlock",{pin:$("lpin").value}); $("lpin").value="";
  if(data.state==="ok"){ $("lerr").textContent=""; refreshState(); }
  else if(data.state==="locked") $("lerr").textContent="Доступ закрыт на "+data.left+" с.";
  else $("lerr").textContent="Неверный PIN.";
}
$("lgo").onclick=tryUnlock; $("lpin").addEventListener("keydown",e=>{ if(e.key==="Enter") tryUnlock(); });
setInterval(()=>{ if(st.unlocked) api("/api/state").then(r=>{ st=r.data; paintHeader(); }); },5000);
refreshState();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
