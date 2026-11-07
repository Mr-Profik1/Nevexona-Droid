#!/usr/bin/env python3
"""Джарвис: помощник для Linux. Вы пишете, он отвечает голосом и выполняет задачи.

Два режима, переключаются сами:
  с интернетом: ИИ (любой сервис с OpenAI-совместимым API) сам решает, какие команды выполнить;
  без интернета (или без ключа): простые заданные команды, напишите "помощь".
Свои короткие команды (макросы): "макрос rt = команда", список: "макросы".
Режим полного разрешения: JARVIS_AUTO=1 или флаг --auto (опасные команды всё равно спрашивают).
Озвучка: sudo apt install espeak-ng
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

CONFIG = os.path.expanduser("~/.config/jarvis/config")
MACROS = os.path.expanduser("~/.config/jarvis/macros.json")
LOG = os.path.expanduser("~/.jarvis_log")


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
BASE_URL = os.environ.get("JARVIS_BASE_URL", "").rstrip("/")
API_KEY = os.environ.get("JARVIS_API_KEY", "")
MODEL = os.environ.get("JARVIS_MODEL", "")
AUTO = os.environ.get("JARVIS_AUTO") == "1" or "--auto" in sys.argv
MAX_STEPS = 15 if AUTO else 6
MAX_OUT = 3000
CMD_TIMEOUT = 300
DANGEROUS = re.compile(
    r"\brm\s+-[a-zA-Z]*[rf]|\bmkfs|\bdd\s+.*of=/dev/|:\(\)\s*\{|>\s*/dev/sd|\bchmod\s+-R\s+[0-7]+\s+/\s*$"
    r"|\bshred\b|\bwipefs\b|\bfdisk\b|\bparted\b|\bpoweroff\b|\breboot\b|\bshutdown\b|\bpasswd\b|\buserdel\b")

SYSTEM = (
    "Ты голосовой помощник Джарвис на компьютере с Linux Mint (Cinnamon, X11). "
    "Пользователь даёт задачи на русском. Ты можешь выполнять команды bash. "
    "Отвечай СТРОГО одним JSON-объектом без пояснений вокруг: "
    '{"say": "короткая фраза для озвучки", "run": "одна команда bash или пустая строка"}. '
    "Если нужно выполнить команду, поставь её в run. Ты получишь её вывод и продолжишь. "
    "Когда задача выполнена или команда не нужна, оставь run пустым и скажи итог в say. "
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
}
QUICK = {"время", "дата", "помощь", "память", "громче", "тише", "без звука", "макросы"}

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
  помощь, выход
С интернетом и настроенным ИИ любые другие фразы выполняет ИИ."""


def say(text):
    print(f"Джарвис: {text}")
    if text and shutil.which("espeak-ng"):
        subprocess.Popen(["espeak-ng", "-v", "ru", text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def confirm(question):
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


def simple(text):
    """Простые команды. Возвращает True, если команда распознана."""
    t = text.strip().lower()
    if t in ("помощь", "help", "?"):
        print(HELP)
        say("Список команд на экране.")
    elif "время" in t or t == "time":
        say(datetime.datetime.now().strftime("Сейчас %H:%M"))
    elif "дата" in t or "какое число" in t:
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


# ---------- ИИ ----------

def ai_ready():
    return bool(BASE_URL and API_KEY and MODEL)


def chat(messages):
    body = json.dumps({"model": MODEL, "messages": messages, "temperature": 0.2}).encode()
    req = urllib.request.Request(
        BASE_URL + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + API_KEY})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    return data["choices"][0]["message"]["content"]


def parse(reply):
    m = re.search(r"\{.*\}", reply, re.S)
    if m:
        try:
            obj = json.loads(m.group())
            return str(obj.get("say", "")).strip(), str(obj.get("run", "") or "").strip()
        except json.JSONDecodeError:
            pass
    return reply.strip(), ""


def run_logged(cmd):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(cmd + "\n")
    except OSError:
        pass
    try:
        p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=CMD_TIMEOUT)
        return f"[код {p.returncode}]\n{(p.stdout + p.stderr).strip()[:MAX_OUT]}"
    except subprocess.TimeoutExpired:
        return f"[команда не завершилась за {CMD_TIMEOUT} секунд]"


def ask_ai(history, task):
    """Возвращает True, если ИИ ответил; False, если нет связи (нужен запасной режим)."""
    history.append({"role": "user", "content": task})
    for _ in range(MAX_STEPS):
        try:
            reply = chat([{"role": "system", "content": SYSTEM}] + history[-20:])
        except urllib.error.HTTPError as e:
            say(f"Ошибка сервиса ИИ: {e.code}. Проверьте ключ, модель и адрес (команда «настройка»).")
            return True
        except Exception:  # noqa: BLE001  нет сети, таймаут и т.п.
            history.pop()
            return False
        history.append({"role": "assistant", "content": reply})
        text, cmd = parse(reply)
        if text:
            say(text)
        if not cmd:
            return True
        print(f"  Команда: {cmd}")
        if (not AUTO or DANGEROUS.search(cmd)) and not confirm("  Выполнить?"):
            history.append({"role": "user", "content": "Пользователь отклонил команду."})
            say("Отменено.")
            return True
        out = run_logged(cmd)
        print(out)
        history.append({"role": "user", "content": "Вывод команды:\n" + out})
    say("Слишком много шагов, остановился.")
    return True


def wizard():
    global BASE_URL, API_KEY, MODEL
    print("Настройка ИИ. Нужен сервис с OpenAI-совместимым API (см. jarvis/README.md).")
    url = input("Адрес API (например https://openrouter.ai/api/v1): ").strip()
    key = input("Ключ: ").strip()
    model = input("Название модели: ").strip()
    if not (url and key and model):
        say("Отменено, нужны все три значения.")
        return
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as f:
        f.write(f'JARVIS_BASE_URL="{url}"\nJARVIS_API_KEY="{key}"\nJARVIS_MODEL="{model}"\n')
    os.chmod(CONFIG, 0o600)
    BASE_URL, API_KEY, MODEL = url.rstrip("/"), key, model
    say("Сохранено.")


def main():
    if os.name != "posix":
        print("Работает только на Linux.")
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
        low = text.lower()
        if not text:
            continue
        if low in ("выход", "пока", "exit", "quit"):
            say("До свидания.")
            return 0
        macros = load_macros()
        if low in macros:
            print(f"  Макрос: {macros[low]}")
            print(run_logged(macros[low]))
            continue
        if macro_commands(text):
            continue
        if low == "настройка":
            wizard()
            continue
        if not ai_ready() or low in QUICK:
            if not simple(text):
                say("Не понял. Напишите «помощь».")
            continue
        if not ask_ai(history, text):
            say("Нет связи с ИИ, перехожу в простой режим.")
            if not simple(text):
                say("Не понял. Напишите «помощь».")


if __name__ == "__main__":
    sys.exit(main())
