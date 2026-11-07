#!/usr/bin/env python3
"""Джарвис: помощник для Linux. Вы пишете, он отвечает голосом и выполняет задачи.

Два режима, переключаются сами:
  с интернетом: ИИ (любой сервис с OpenAI-совместимым API) сам решает, какие команды выполнить
    и что сделать на экране (X11: скриншот, клик, ввод, клавиши; нужны xdotool и scrot);
  без интернета (или без ключа): простые заданные команды, напишите "помощь" или "help".
Защита: команда "пин" задаёт PIN, он спрашивается при каждом запуске.
Свои короткие команды (макросы): "макрос rt = команда", список: "макросы".
Режим полного разрешения: JARVIS_AUTO=1 или флаг --auto, только с PIN (опасные команды всё равно спрашивают).
Озвучка: sudo apt install espeak-ng
"""
import base64
import datetime
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

VERSION = "1.2.0"
CONFIG_DIR = os.path.expanduser("~/.config/jarvis")
CONFIG = os.path.join(CONFIG_DIR, "config")
MACROS = os.path.join(CONFIG_DIR, "macros.json")
PIN_FILE = os.path.join(CONFIG_DIR, "pin")
LOCK_FILE = os.path.join(CONFIG_DIR, "pin.lock")
LOG = os.path.expanduser("~/.jarvis_log")
PIN_ROUNDS = 200_000
PIN_TRIES = 3
PIN_LOCK_SECONDS = 60
STOP = threading.Event()  # кнопка «Стоп» в окне: прерывает текущую задачу
PIN_FAILS = {"n": 0}


def load_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"'))
    except OSError:
        pass


load_config()
DEFAULT_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openrouter/free"  # сам выбирает любую доступную бесплатную модель
DEFAULT_VISION_MODEL = "nvidia/nemotron-3.5-super-vl:free"  # бесплатная, понимает скриншоты
BASE_URL = (os.environ.get("JARVIS_BASE_URL") or DEFAULT_URL).rstrip("/")
API_KEY = os.environ.get("JARVIS_API_KEY", "")
MODEL = os.environ.get("JARVIS_MODEL") or DEFAULT_MODEL
VISION_MODEL = os.environ.get("JARVIS_VISION_MODEL") or DEFAULT_VISION_MODEL
AUTO = os.environ.get("JARVIS_AUTO") == "1" or "--auto" in sys.argv
MAX_STEPS = 30 if AUTO else 12
MAX_OUT = 3000
SHOT_MAX_WIDTH = 1280
CMD_TIMEOUT = 300
DANGEROUS = re.compile(
    r"\brm\s+-[a-zA-Z]*[rf]|\bmkfs|\bdd\s+.*of=/dev/|:\(\)\s*\{|>\s*/dev/sd|\bchmod\s+-R\s+[0-7]+\s+/\s*$"
    r"|\bshred\b|\bwipefs\b|\bfdisk\b|\bparted\b|\bpoweroff\b|\breboot\b|\bshutdown\b|\bpasswd\b|\buserdel\b")

SYSTEM = (
    "Ты помощник Джарвис на компьютере с Linux (X11). "
    "Пользователь даёт задачи на русском или английском, отвечай на языке пользователя. "
    "Ты можешь выполнять команды bash и управлять экраном. "
    "Отвечай СТРОГО одним JSON-объектом без пояснений вокруг: "
    '{"say": "короткая фраза", "run": "одна команда bash или пустая строка", "screen": null или действие}. '
    "За один ответ делай одно: или run, или screen. "
    "Действие screen это объект: "
    '{"do":"shot"} сделать скриншот и получить его; '
    '{"do":"click","x":100,"y":200} (также double_click, right_click, move); '
    '{"do":"type","text":"текст"} напечатать текст; '
    '{"do":"key","keys":"ctrl+l"} нажать клавиши (формат xdotool: Return, ctrl+t, alt+F4); '
    '{"do":"scroll","dy":-3} прокрутка (минус вверх, плюс вниз). '
    "Координаты x,y считай по последнему скриншоту, который ты получил. "
    "Перед кликом по экрану сначала сделай shot и посмотри результат, после действия снова shot, чтобы проверить итог. "
    "Если нужно выполнить команду, поставь её в run. Ты получишь её вывод и продолжишь. "
    "Когда задача выполнена или действий больше не нужно, оставь run пустым, screen null и скажи итог в say. "
    "Графические программы запускай так: setsid -f ПРОГРАММА >/dev/null 2>&1. "
    "sudo можно использовать, когда это нужно (пароль уже введён), для apt всегда добавляй -y. "
    "Чтобы прочитать сайт, используй curl -sL URL | sed 's/<[^>]*>//g' | tr -s ' \\n' | head -c 3000. "
    "Для поиска: curl -sL 'https://html.duckduckgo.com/html/?q=ЗАПРОС'. "
    "Не делай необратимых действий (удаление файлов, форматирование) без явной просьбы. "
    "Говори коротко, без markdown."
)

APPS = {
    "браузер": ["firefox"], "firefox": ["firefox"], "терминал": ["x-terminal-emulator"],
    "файлы": ["nemo"], "калькулятор": ["gnome-calculator"], "телеграм": ["telegram-desktop"],
    "telegram": ["telegram-desktop"], "steam": ["steam"], "nevexona": ["nevexona-droid"],
    "droid": ["nevexona-droid"],
    "browser": ["firefox"], "terminal": ["x-terminal-emulator"], "files": ["nemo"],
    "calculator": ["gnome-calculator"],
}
QUICK = {"время", "дата", "помощь", "память", "громче", "тише", "без звука", "макросы",
         "time", "date", "help", "memory", "louder", "quieter", "mute", "macros"}
# английские команды приводятся к русским
EN_ALIASES = {"louder": "громче", "quieter": "тише", "mute": "без звука", "memory": "память",
              "macros": "макросы", "shutdown": "выключи компьютер", "reboot": "перезагрузи компьютер"}
EN_PREFIXES = (("open ", "открой "), ("launch ", "запусти "), ("search ", "найди "),
               ("find ", "найди "), ("volume ", "громкость "), ("run ", "выполни "))

HELP = """Простые команды (работают и без интернета):
  время, дата
  открой <браузер|терминал|файлы|калькулятор|телеграм|steam|nevexona>
  найди <запрос>              поиск в браузере
  громкость 50 | громче | тише | без звука
  память                      сколько оперативки свободно
  выполни <команда>           команда в терминале (спросит подтверждение)
  выключи компьютер | перезагрузи компьютер   (спросит подтверждение)
  макрос <имя> = <команда>    своя короткая команда, например: макрос rt = setsid -f firefox
  макросы                     список; "удали макрос <имя>"
  настройка                   подключить ИИ (адрес, ключ, модель)
  пин                         задать или сменить PIN; "пин удалить" снять защиту
  помощь, выход
Английские версии тоже работают: time, date, open browser, search ..., volume 50, louder, quieter, mute, memory, run ...
С интернетом и настроенным ИИ любые другие фразы выполняет ИИ, в том числе управляет экраном
(скриншот, клики, ввод текста, клавиши; только X11, нужны xdotool и scrot или imagemagick)."""


def say(text):
    print(f"Джарвис: {text}")
    if text and shutil.which("espeak-ng"):
        subprocess.Popen(["espeak-ng", "-v", "ru", text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def confirm(question, detail=None):
    """detail (команда целиком) нужен окну; в терминале она уже напечатана выше."""
    return input(f"{question} [y/N] ").strip().lower() in ("y", "д", "да")


def run(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout + p.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return f"ошибка: {e}"


def detach(cmd):
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


# ---------- простые команды (без ИИ) ----------

def open_app(name):
    for key, cmd in APPS.items():
        if key in name:
            if not shutil.which(cmd[0]):
                say(f"Программа {cmd[0]} не установлена.")
                return
            detach(cmd)
            say(f"Открываю {key}.")
            return
    say("Не знаю такую программу. Напишите «помощь».")


def volume(arg):
    if not shutil.which("pactl"):
        say("Не найден pactl, громкость не изменить.")
        return
    if arg == "mute":
        run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
    else:
        run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", arg])
    say("Готово.")


def to_ru(text):
    """Приводит английские простые команды к русским."""
    t = text.strip()
    low = t.lower()
    if low in EN_ALIASES:
        return EN_ALIASES[low]
    for en, ru in EN_PREFIXES:
        if low.startswith(en):
            return ru + t[len(en):]
    return t


def simple(text):
    """Простые команды. Возвращает True, если команда распознана."""
    text = to_ru(text)
    t = text.strip().lower()
    if t in ("помощь", "help", "?"):
        print(HELP)
        say("Список команд на экране.")
    elif "время" in t or t == "time":
        say(datetime.datetime.now().strftime("Сейчас %H:%M"))
    elif "дата" in t or "какое число" in t or t == "date":
        say(datetime.datetime.now().strftime("Сегодня %d.%m.%Y"))
    elif t.startswith(("открой ", "запусти ")):
        open_app(t.split(" ", 1)[1])
    elif t.startswith(("найди ", "поиск ")):
        q = text.split(" ", 1)[1].strip()
        detach(["xdg-open", "https://duckduckgo.com/?q=" + re.sub(r"\s+", "+", q)])
        say(f"Ищу: {q}")
    elif t.startswith("громкость"):
        m = re.search(r"\d+", t)
        if m:
            volume(f"{min(int(m.group()), 100)}%")
        else:
            say("Скажите число, например: громкость 50.")
    elif t in ("громче", "тише", "без звука"):
        volume({"громче": "+10%", "тише": "-10%", "без звука": "mute"}[t])
    elif "память" in t or t in ("ram", "озу"):
        print(run(["free", "-h"]))
        say("Данные о памяти на экране.")
    elif t.startswith("выполни "):
        cmd = text.split(" ", 1)[1].strip()
        if confirm(f"Выполнить в терминале: {cmd}?"):
            print(run(["bash", "-c", cmd], CMD_TIMEOUT))
            say("Выполнено.")
        else:
            say("Отменено.")
    elif t in ("выключи компьютер", "выключи"):
        if confirm("Выключить компьютер?"):
            subprocess.run(["systemctl", "poweroff"])
    elif t in ("перезагрузи компьютер", "перезагрузи"):
        if confirm("Перезагрузить компьютер?"):
            subprocess.run(["systemctl", "reboot"])
    else:
        return False
    return True


# ---------- макросы ----------

def load_macros():
    try:
        with open(MACROS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_macros(m):
    os.makedirs(os.path.dirname(MACROS), exist_ok=True)
    with open(MACROS, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def macro_commands(text):
    """Управление макросами. Возвращает True, если фраза была командой про макросы."""
    t = text.strip()
    low = t.lower()
    m = re.match(r"макрос\s+(\S+)\s*=\s*(.+)$", t, re.I | re.S)
    if m:
        macros = load_macros()
        macros[m.group(1).lower()] = m.group(2).strip()
        save_macros(macros)
        say(f"Макрос {m.group(1)} сохранён.")
        return True
    if low == "макросы":
        macros = load_macros()
        if not macros:
            say("Макросов пока нет. Пример: макрос rt = setsid -f firefox")
        for k, v in macros.items():
            print(f"  {k} = {v}")
        return True
    m = re.match(r"удали макрос\s+(\S+)$", low)
    if m:
        macros = load_macros()
        if macros.pop(m.group(1), None) is not None:
            save_macros(macros)
            say("Удалил.")
        else:
            say("Такого макроса нет.")
        return True
    return False


# ---------- PIN ----------

def pin_set_up():
    return os.path.exists(PIN_FILE)


def hash_pin(pin, salt=None, rounds=PIN_ROUNDS):
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, rounds)
    return f"pbkdf2${rounds}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_pin(pin, stored):
    try:
        _, rounds, salt, dk = stored.strip().split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pin.encode(), base64.b64decode(salt), int(rounds))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except ValueError:
        return False


def save_pin(pin):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    fd = os.open(PIN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(hash_pin(pin) + "\n")


def check_pin(pin):
    try:
        with open(PIN_FILE, encoding="utf-8") as f:
            return verify_pin(pin, f.read())
    except OSError:
        return False


def lock_left():
    """Сколько секунд ещё действует блокировка после неверных попыток."""
    try:
        with open(LOCK_FILE, encoding="utf-8") as f:
            return max(0, int(float(f.read().strip()) - time.time()))
    except (OSError, ValueError):
        return 0


def try_pin(pin):
    """Одна попытка ввода PIN: ("ok" | "bad" | "locked", секунд до конца блокировки)."""
    left = lock_left()
    if left:
        return "locked", left
    if check_pin(pin):
        PIN_FAILS["n"] = 0
        try:
            os.remove(LOCK_FILE)
        except OSError:
            pass
        return "ok", 0
    PIN_FAILS["n"] += 1
    if PIN_FAILS["n"] >= PIN_TRIES:
        PIN_FAILS["n"] = 0
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(LOCK_FILE, "w", encoding="utf-8") as f:
                f.write(str(time.time() + PIN_LOCK_SECONDS))
        except OSError:
            pass
        return "locked", PIN_LOCK_SECONDS
    return "bad", 0


def unlock():
    """Спрашивает PIN при старте. True, если можно работать."""
    if not pin_set_up():
        return True
    left = lock_left()
    if left:
        print(f"Слишком много неверных попыток. Подождите {left} с.")
        return False
    while True:
        state, left = try_pin(getpass.getpass("PIN: "))
        if state == "ok":
            return True
        if state == "locked":
            print(f"Доступ закрыт на {left} с.")
            return False
        print("Неверный PIN.")
        time.sleep(1)


def pin_command(text):
    """Команды «пин» и «пин удалить». Возвращает True, если фраза была про PIN."""
    low = text.strip().lower()
    if low not in ("пин", "pin", "пин удалить", "pin remove"):
        return False
    remove = low.endswith(("удалить", "remove"))
    if remove and not pin_set_up():
        say("PIN и так не задан.")
        return True
    if pin_set_up() and not check_pin(getpass.getpass("Текущий PIN: ")):
        say("Неверный PIN.")
        return True
    if remove:
        try:
            os.remove(PIN_FILE)
        except OSError:
            pass
        say("PIN снят.")
        return True
    new = getpass.getpass("Новый PIN (минимум 4 символа): ")
    if len(new) < 4 or new != getpass.getpass("Повторите PIN: "):
        say("PIN не сохранён: он короче 4 символов или повтор не совпал.")
        return True
    save_pin(new)
    say("PIN сохранён.")
    return True


# ---------- управление экраном (X11) ----------

SCREEN = {"w": 0, "h": 0, "scale": 1.0, "always": False}
SCREEN_DO = {"shot", "click", "double_click", "right_click", "move", "type", "key", "scroll"}


def screen_problem():
    """Причина, почему экран недоступен, или None, если всё готово."""
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return "Сессия Wayland: xdotool в ней не работает. Войдите в сеанс X11."
    if not os.environ.get("DISPLAY"):
        return "Нет графического экрана (переменная DISPLAY пуста)."
    if not shutil.which("xdotool"):
        return "Не установлен xdotool: sudo apt install xdotool"
    if not (shutil.which("scrot") or shutil.which("import")):
        return "Нет программы для скриншотов: sudo apt install scrot"
    return None


def png_size(data):
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("это не PNG")
    return struct.unpack(">II", data[16:24])


def take_shot():
    """Скриншот. Возвращает (png-байты, ширина, высота) того, что уйдёт ИИ; запоминает масштаб."""
    d = tempfile.mkdtemp(prefix="jarvis-")
    path = os.path.join(d, "s.png")
    try:
        cmd = ["scrot", path] if shutil.which("scrot") else ["import", "-window", "root", path]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if p.returncode != 0 or not os.path.exists(path):
            raise RuntimeError((p.stderr or "скриншот не получился").strip()[:200])
        with open(path, "rb") as f:
            real_w, real_h = png_size(f.read(24))
        sent = path
        if real_w > SHOT_MAX_WIDTH and shutil.which("convert"):
            small = os.path.join(d, "small.png")
            q = subprocess.run(["convert", path, "-resize", f"{SHOT_MAX_WIDTH}x", small],
                               capture_output=True, timeout=30)
            if q.returncode == 0 and os.path.exists(small):
                sent = small
        with open(sent, "rb") as f:
            data = f.read()
        w, h = png_size(data)
        SCREEN.update(w=w, h=h, scale=real_w / w)
        return data, w, h
    finally:
        shutil.rmtree(d, ignore_errors=True)


def to_real(x, y):
    """Координаты со скриншота (какой видел ИИ) в настоящие координаты экрана."""
    if not SCREEN["w"]:
        raise ValueError("сначала нужен скриншот")
    x, y = int(x), int(y)
    if not (0 <= x < SCREEN["w"] and 0 <= y < SCREEN["h"]):
        raise ValueError(f"координаты вне экрана (скриншот {SCREEN['w']}x{SCREEN['h']})")
    return round(x * SCREEN["scale"]), round(y * SCREEN["scale"])


def xdo(*args):
    p = subprocess.run(["xdotool", *map(str, args)], capture_output=True, text=True, timeout=20)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "xdotool вернул ошибку").strip()[:200])


def describe_action(act, hide_text=False):
    kind = act.get("do")
    if kind in ("click", "double_click", "right_click", "move"):
        return f"{kind} ({act.get('x')},{act.get('y')})"
    if kind == "type":
        text = str(act.get("text", ""))
        return f"type ({len(text)} символов)" if hide_text else f"напечатать «{text}»"
    if kind == "key":
        return f"клавиши {act.get('keys')}"
    if kind == "scroll":
        return f"прокрутка {act.get('dy')}"
    return str(kind)


def screen_do(act):
    """Выполняет действие над экраном (кроме shot). Возвращает текст результата."""
    kind = str(act.get("do", "")).lower()
    try:
        if kind in ("click", "double_click", "right_click", "move"):
            x, y = to_real(act.get("x"), act.get("y"))
            xdo("mousemove", x, y)
            if kind == "click":
                xdo("click", 1)
            elif kind == "double_click":
                xdo("click", "--repeat", 2, "--delay", 80, 1)
            elif kind == "right_click":
                xdo("click", 3)
        elif kind == "type":
            text = str(act.get("text", ""))
            if not text:
                return "ошибка: пустой текст"
            xdo("type", "--delay", 20, "--", text)
        elif kind == "key":
            keys = str(act.get("keys", "")).strip()
            if not re.fullmatch(r"[A-Za-z0-9_+\- ]+", keys):
                return "ошибка: неверные клавиши"
            xdo("key", *keys.split())
        elif kind == "scroll":
            dy = int(act.get("dy", 0))
            if dy == 0:
                return "ошибка: dy равно нулю"
            xdo("click", "--repeat", min(abs(dy), 20), 5 if dy > 0 else 4)
        else:
            return "ошибка: неизвестное действие"
    except (ValueError, TypeError, RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        return f"ошибка: {e}"
    time.sleep(0.5)
    return "Готово."


def allow_screen(desc, danger=False):
    if danger:
        return confirm(f"  Опасно: {desc}. Выполнить?")
    if AUTO or SCREEN["always"]:
        return True
    ans = input(f"  Экран: {desc}. Выполнить? [y/N/a=всегда в этой сессии] ").strip().lower()
    if ans in ("a", "а", "в"):
        SCREEN["always"] = True
        return True
    return ans in ("y", "д", "да")


def strip_old_images(history):
    """Оставляет в истории только последний скриншот, чтобы не раздувать запросы."""
    last = max((i for i, m in enumerate(history) if isinstance(m["content"], list)), default=-1)
    for i, m in enumerate(history):
        if isinstance(m["content"], list) and i != last:
            m["content"] = "[старый скриншот удалён]"


def handle_screen(history, act):
    """Выполняет действие над экраном, результат кладёт в историю. False, если пользователь отказал."""
    problem = screen_problem()
    if problem:
        say(problem)
        history.append({"role": "user", "content": "Экран недоступен: " + problem})
        return True
    kind = act["do"]
    if kind == "shot":
        desc, danger = "сделать скриншот и отправить его ИИ", False
    else:
        desc = describe_action(act)
        danger = kind == "type" and bool(DANGEROUS.search(str(act.get("text", ""))))
    if not allow_screen(desc, danger):
        history.append({"role": "user", "content": "Пользователь отклонил действие."})
        say("Отменено.")
        return False
    log_line("screen: " + ("shot" if kind == "shot" else describe_action(act, hide_text=True)))
    if kind == "shot":
        try:
            data, w, h = take_shot()
        except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as e:
            print(f"  Скриншот не получился: {e}")
            history.append({"role": "user", "content": f"Скриншот не получился: {e}"})
            return True
        history.append({"role": "user", "content": [
            {"type": "text", "text": f"Скриншот {w}x{h}. Координаты x,y считай по нему."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(data).decode()}},
        ]})
        return True
    out = screen_do(act)
    print("  " + out)
    history.append({"role": "user", "content": "Результат действия: " + out})
    return True


# ---------- ИИ ----------

def ai_ready():
    return bool(BASE_URL and API_KEY and MODEL)


def model_for(messages):
    """Запросы со скриншотом идут в модель, которая видит изображения; остальные в обычную."""
    has_image = any(isinstance(m.get("content"), list) for m in messages)
    return VISION_MODEL if has_image and VISION_MODEL else MODEL


def chat(messages):
    body = json.dumps({"model": model_for(messages), "messages": messages, "temperature": 0.2}).encode()
    req = urllib.request.Request(
        BASE_URL + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + API_KEY})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    return data["choices"][0]["message"]["content"]


def parse(reply):
    """Разбирает ответ ИИ: (текст для озвучки, команда bash, действие над экраном или None)."""
    m = re.search(r"\{.*\}", reply, re.S)
    if m:
        try:
            obj = json.loads(m.group())
            if not isinstance(obj, dict):
                return reply.strip(), "", None
            act = obj.get("screen")
            if not (isinstance(act, dict) and str(act.get("do", "")).lower() in SCREEN_DO):
                act = None
            else:
                act = {**act, "do": str(act["do"]).lower()}
            return str(obj.get("say", "") or "").strip(), str(obj.get("run", "") or "").strip(), act
        except json.JSONDecodeError:
            pass
    return reply.strip(), "", None


def log_line(line):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def run_logged(cmd):
    log_line(cmd)
    p = subprocess.Popen(["bash", "-c", cmd], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, start_new_session=True)
    start = time.time()
    while True:
        try:
            out, err = p.communicate(timeout=0.5)
            return f"[код {p.returncode}]\n{(out + err).strip()[:MAX_OUT]}"
        except subprocess.TimeoutExpired:
            stopped = STOP.is_set()
            if stopped or time.time() - start > CMD_TIMEOUT:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except OSError:
                    pass
                p.communicate()
                return "[остановлено пользователем]" if stopped else f"[команда не завершилась за {CMD_TIMEOUT} секунд]"


def ask_ai(history, task):
    """Возвращает True, если ИИ ответил; False, если нет связи (нужен запасной режим)."""
    history.append({"role": "user", "content": task})
    for _ in range(MAX_STEPS):
        if STOP.is_set():
            say("Остановлено.")
            return True
        strip_old_images(history)
        has_image = any(isinstance(m["content"], list) for m in history[-20:])
        try:
            reply = chat([{"role": "system", "content": SYSTEM}] + history[-20:])
        except urllib.error.HTTPError as e:
            hints = {401: "Ключ не подошёл: проверьте его в настройках.",
                     402: "На счёте OpenRouter нет средств для этой модели. Выберите бесплатную (с :free).",
                     404: "Модель недоступна или не существует: смените её в настройках.",
                     429: "Лимит бесплатной модели (около 20 запросов в минуту и 200 в день). Подождите минуту и повторите."}
            say(f"Ошибка сервиса ИИ: {e.code}. " + hints.get(e.code, "Проверьте ключ, модель и адрес (команда «настройка»)."))
            if has_image and e.code not in hints:
                print(f"  В запросе был скриншот: модель {VISION_MODEL} должна уметь работать с изображениями.")
            return True
        except Exception:  # noqa: BLE001  нет сети, таймаут и т.п.
            history.pop()
            return False
        if STOP.is_set():
            say("Остановлено.")
            return True
        history.append({"role": "assistant", "content": reply})
        text, cmd, act = parse(reply)
        if text:
            say(text)
        if act:
            if not handle_screen(history, act):
                return True
            continue
        if not cmd:
            return True
        print(f"  Команда: {cmd}")
        if (not AUTO or DANGEROUS.search(cmd)) and not confirm("  Выполнить?", detail=cmd):
            history.append({"role": "user", "content": "Пользователь отклонил команду."})
            say("Отменено.")
            return True
        out = run_logged(cmd)
        print(out)
        history.append({"role": "user", "content": "Вывод команды:\n" + out})
    say("Слишком много шагов, остановился.")
    return True


def wizard():
    print("Настройка ИИ (OpenRouter по умолчанию). Пустой ввод оставляет значение в скобках.")
    url = input(f"Адрес API [{BASE_URL}]: ").strip() or BASE_URL
    key = getpass.getpass("Ключ (ввод скрыт): ").strip() or API_KEY
    model = input(f"Модель [{MODEL}]: ").strip() or MODEL
    vision = input(f"Модель для экрана [{VISION_MODEL}]: ").strip() or VISION_MODEL
    if not key:
        say("Отменено: нужен ключ.")
        return
    try:
        save_config(url, key, model, vision)
    except ValueError as e:
        say(str(e))
        return
    say("Сохранено.")


def save_config(url, key, model, vision=None):
    """Сохраняет адрес, ключ и модели в ~/.config/jarvis/config (доступ только владельцу)."""
    global BASE_URL, API_KEY, MODEL, VISION_MODEL
    vision = vision or DEFAULT_VISION_MODEL
    for v in (url, key, model, vision):
        if any(c in v for c in '"\n\r'):
            raise ValueError("в адресе, ключе и моделях не должно быть кавычек и переводов строки")
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f'JARVIS_BASE_URL="{url}"\nJARVIS_API_KEY="{key}"\nJARVIS_MODEL="{model}"\n'
                f'JARVIS_VISION_MODEL="{vision}"\n')
    os.chmod(CONFIG, 0o600)
    BASE_URL, API_KEY, MODEL, VISION_MODEL = url.rstrip("/"), key, model, vision


def process(text, history):
    """Одна фраза пользователя (общая для терминала и окна). True, если нужно выйти."""
    text = text.strip()
    low = text.lower()
    if not text:
        return False
    if low in ("выход", "пока", "exit", "quit"):
        say("До свидания.")
        return True
    macros = load_macros()
    if low in macros:
        print(f"  Макрос: {macros[low]}")
        print(run_logged(macros[low]))
        return False
    if macro_commands(text) or pin_command(text):
        return False
    if low in ("настройка", "setup"):
        wizard()
        return False
    if not ai_ready() or low in QUICK:
        if not simple(text):
            say("Не понял. Напишите «помощь».")
        return False
    try:
        answered = ask_ai(history, text)
    except KeyboardInterrupt:
        print()
        say("Остановлено.")
        return False
    if not answered:
        say("Нет связи с ИИ, перехожу в простой режим.")
        if not simple(text):
            say("Не понял. Напишите «помощь».")
    return False


def main():
    if os.name != "posix":
        print("Работает только на Linux.")
        return 1
    if AUTO and not pin_set_up():
        print("Режим полного разрешения работает только с PIN. Запустите jarvis без --auto, "
              "напишите «пин», задайте PIN и запустите снова.")
        return 1
    if not unlock():
        return 1
    if not shutil.which("espeak-ng"):
        print("Озвучка выключена. Включить: sudo apt install espeak-ng")
    if AUTO:
        print("РЕЖИМ ПОЛНОГО РАЗРЕШЕНИЯ: команды ИИ выполняются без вопросов (кроме опасных). Журнал: " + LOG)
    if ai_ready():
        say("Привет. Что нужно сделать?")
    else:
        say("Привет. ИИ не настроен, работаю в простом режиме. Напишите «настройка» или «помощь».")
    history = []
    while True:
        try:
            text = input("Вы> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if process(text, history):
            return 0


if __name__ == "__main__":
    sys.exit(main())
