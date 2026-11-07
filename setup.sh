#!/usr/bin/env bash
# NEVEXONA Droid: установка одним файлом (приложение + Waydroid). Для Debian/Ubuntu/Mint.
# Запуск: bash setup.sh   (спросит пароль sudo, нужен интернет)
set -euo pipefail
command -v apt-get >/dev/null || { echo "Нужна система на базе Debian (apt)."; exit 1; }
sudo apt-get update
sudo apt-get install -y git
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git clone --depth 1 https://github.com/Mr-Profik1/Nevexona-Droid "$tmp/nd"
cd "$tmp/nd"
./install.sh --yes
echo
echo "Дальше: запустите nevexona-droid -> Android Engine -> Инициализировать Android (скачает образ ~1 ГБ)."
