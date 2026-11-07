#!/usr/bin/env bash
# Установка NEVEXONA Droid на Debian/Ubuntu/Mint. Системные пакеты ставятся только с вашего согласия.
set -euo pipefail
cd "$(dirname "$0")"
command -v apt-get >/dev/null || { echo "Нужна система на базе Debian (apt)."; exit 1; }
need=()
need_pyside=0
if ! python3 -c "import PySide6" 2>/dev/null; then
  if apt-cache policy python3-pyside6.qtwidgets 2>/dev/null | grep -q "Candidate: [^(]"; then
    need+=(python3-pyside6.qtwidgets)
  else
    need_pyside=1
    command -v pip3 >/dev/null || need+=(python3-pip)
  fi
fi
command -v adb >/dev/null || need+=(adb)
command -v waydroid >/dev/null || echo "Внимание: Waydroid не найден. Установка: https://docs.waydro.id/usage/install-on-desktops"
if [ ${#need[@]} -gt 0 ]; then
  echo "Нужно установить: ${need[*]}"
  read -r -p "Установить через sudo apt? [y/N] " a
  [ "$a" = y ] || { echo "Отменено."; exit 1; }
  sudo apt-get install -y "${need[@]}"
fi
if [ "$need_pyside" = 1 ]; then
  echo "Пакета PySide6 в apt нет, ставлю через pip."
  pip3 install --user PySide6 || pip3 install --user --break-system-packages PySide6
fi
deb=$(ls dist/*.deb 2>/dev/null | head -1 || true)
[ -n "$deb" ] || { ./packaging/build_deb.sh >/dev/null; deb=$(ls dist/*.deb | head -1); }
sudo apt-get install -y "./$deb"
if ! command -v waydroid >/dev/null; then
  echo
  echo "Waydroid (Android) не установлен. Он ставится из официального репозитория waydro.id,"
  echo "затем образ Android (~1 ГБ) скачивается из приложения: Android Engine -> Инициализировать Android."
  read -r -p "Установить Waydroid сейчас? [y/N] " w
  if [ "$w" = y ]; then
    sudo apt-get install -y curl ca-certificates
    curl -fsSL https://repo.waydro.id | sudo bash
    sudo apt-get install -y waydroid
  fi
fi
echo "Готово. Запуск: nevexona-droid или из меню приложений."
