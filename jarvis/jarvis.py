#!/usr/bin/env python3
"""Простой текстовый помощник для Linux: вы пишете, он отвечает голосом и делает команды.

Без интернета и без нейросетей, только заранее заданные команды (напишите "помощь").
Озвучка: sudo apt install espeak-ng
"""
import datetime
import os
import re
import shutil
import subprocess
import sys

APPS = {
    "браузер": ["firefox"],
    "firefox": ["firefox"],
    "терминал": ["x-terminal-emulator"],
    "файлы": ["nemo"],
    "калькулятор": ["gnome-calculator"],
    "телеграм": ["telegram-desktop"],
    "telegram": ["telegram-desktop"],
    "steam": ["steam"],
    "nevexona": ["nevexona-droid"],
    "droid": ["nevexona-droid"],
}

HELP = """Команды:
  время, дата
  открой <браузер|терминал|файлы|калькулятор|телеграм|steam|nevexona>
  найди <запрос>              поиск в браузере
  громкость 50 | громче | тише | без звука
  память                      сколько оперативки свободно
  выполни <команда>           запустить команду в терминале (спросит подтверждение)
  выключи компьютер | перезагрузи компьютер   (спросит подтверждение)
  помощь, выход"""


def say(text):
    print(f"Помощник: {text}")
    if shutil.which("espeak-ng"):
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


def open_app(name):
    for key, cmd in APPS.items():
        if key in name:
            if not shutil.which(cmd[0]):
                say(f"Программа {cmd[0]} не установлена.")
                return
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            say(f"Открываю {key}.")
            return
    say("Не знаю такую программу. Напишите «помощь».")


def volume(args):
    if not shutil.which("pactl"):
        say("Не найден pactl, громкость не изменить.")
        return
    if args == "mute":
        run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
    else:
        run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", args])
    say("Готово.")


def handle(text):
    t = text.strip().lower()
    if not t:
        return True
    if t in ("выход", "пока", "exit", "quit"):
        say("До свидания.")
        return False
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
        subprocess.Popen(["xdg-open", "https://duckduckgo.com/?q=" + re.sub(r"\s+", "+", q)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
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
        out = run(["free", "-h"])
        print(out)
        say("Данные о памяти на экране.")
    elif t.startswith("выполни "):
        cmd = text.split(" ", 1)[1].strip()
        if confirm(f"Выполнить в терминале: {cmd}?"):
            print(run(["bash", "-c", cmd]))
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
        say("Не понял. Напишите «помощь».")
    return True


def main():
    if os.name != "posix":
        print("Работает только на Linux.")
        return 1
    if not shutil.which("espeak-ng"):
        print("Озвучка выключена. Включить: sudo apt install espeak-ng")
    say("Привет. Напишите команду или «помощь».")
    while True:
        try:
            text = input("Вы> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not handle(text):
            return 0


if __name__ == "__main__":
    sys.exit(main())
