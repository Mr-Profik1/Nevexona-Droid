#!/usr/bin/env bash
# Установка NEVEXONA Droid на Debian/Ubuntu/Mint. Системные пакеты ставятся только с вашего согласия.
set -euo pipefail
cd "$(dirname "$0")"
command -v apt-get >/dev/null || { echo "Нужна система на базе Debian (apt)."; exit 1; }
need=()
python3 -c "import PySide6" 2>/dev/null || need+=(python3-pyside6.qtwidgets)
command -v adb >/dev/null || need+=(adb)
command -v waydroid >/dev/null || echo "Внимание: Waydroid не найден. Установка: https://docs.waydro.id/usage/install-on-desktops"
if [ ${#need[@]} -gt 0 ]; then
  echo "Нужно установить: ${need[*]}"
  read -r -p "Установить через sudo apt? [y/N] " a
  [ "$a" = y ] || { echo "Отменено."; exit 1; }
  sudo apt-get install -y "${need[@]}"
fi
deb=$(ls dist/*.deb 2>/dev/null | head -1 || true)
[ -n "$deb" ] || { ./packaging/build_deb.sh >/dev/null; deb=$(ls dist/*.deb | head -1); }
sudo apt-get install -y "./$deb"
echo "Готово. Запуск: nevexona-droid или из меню приложений."
