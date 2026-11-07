#!/usr/bin/env python3
"""ИИ-помощник для Linux: вы пишете задачу, ИИ сам решает, какие команды выполнить, и отвечает голосом.

Нужен ключ любого сервиса с OpenAI-совместимым API (задаётся переменными окружения, см. README).
По умолчанию каждая команда перед запуском требует вашего подтверждения.
Режим полного разрешения: JARVIS_AUTO=1 (или флаг --auto). Опасные команды (удаление, форматирование и т.п.)
всё равно спрашивают подтверждение. Все выполненные команды записываются в ~/.jarvis_log.
Озвучка: sudo apt install espeak-ng
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

BASE_URL = os.environ.get("JARVIS_BASE_URL", "").rstrip("/")
API_KEY = os.environ.get("JARVIS_API_KEY", "")
MODEL = os.environ.get("JARVIS_MODEL", "")
AUTO = os.environ.get("JARVIS_AUTO") == "1" or "--auto" in sys.argv
MAX_STEPS = 15 if AUTO else 6
MAX_OUT = 3000
CMD_TIMEOUT = 300
LOG = os.path.expanduser("~/.jarvis_log")
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


def say(text):
    print(f"Джарвис: {text}")
    if text and shutil.which("espeak-ng"):
        subprocess.Popen(["espeak-ng", "-v", "ru", text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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


def run_command(cmd):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(cmd + "\n")
    except OSError:
        pass
    try:
        p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=CMD_TIMEOUT)
        out = (p.stdout + p.stderr).strip()
        return f"[код {p.returncode}]\n{out[:MAX_OUT]}"
    except subprocess.TimeoutExpired:
        return f"[команда не завершилась за {CMD_TIMEOUT} секунд]"


def handle(history, task):
    history.append({"role": "user", "content": task})
    for _ in range(MAX_STEPS):
        try:
            reply = chat([{"role": "system", "content": SYSTEM}] + history[-20:])
        except urllib.error.HTTPError as e:
            say(f"Ошибка сервиса ИИ: {e.code}. Проверьте ключ, модель и адрес.")
            return
        except Exception as e:  # noqa: BLE001
            say(f"Нет связи с сервисом ИИ: {e}")
            return
        history.append({"role": "assistant", "content": reply})
        text, cmd = parse(reply)
        if text:
            say(text)
        if not cmd:
            return
        print(f"  Команда: {cmd}")
        need_ask = not AUTO or DANGEROUS.search(cmd)
        if need_ask and input("  Выполнить? [y/N] ").strip().lower() not in ("y", "д", "да"):
            history.append({"role": "user", "content": "Пользователь отклонил команду."})
            say("Отменено.")
            return
        out = run_command(cmd)
        print(out)
        history.append({"role": "user", "content": "Вывод команды:\n" + out})
    say("Слишком много шагов, остановился.")


def main():
    if not (BASE_URL and API_KEY and MODEL):
        print("Не заданы переменные JARVIS_BASE_URL, JARVIS_API_KEY, JARVIS_MODEL. Смотрите jarvis/README.md.")
        return 1
    if not shutil.which("espeak-ng"):
        print("Озвучка выключена. Включить: sudo apt install espeak-ng")
    if AUTO:
        print("РЕЖИМ ПОЛНОГО РАЗРЕШЕНИЯ: команды выполняются без вопросов (кроме опасных). Журнал: " + LOG)
    say("Привет. Что нужно сделать?")
    history = []
    while True:
        try:
            task = input("Вы> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if task.lower() in ("выход", "пока", "exit", "quit"):
            say("До свидания.")
            return 0
        if task:
            handle(history, task)


if __name__ == "__main__":
    sys.exit(main())
