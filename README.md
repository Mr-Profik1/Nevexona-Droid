# NEVEXONA Droid

Linux-приложение для запуска Android через Waydroid и ADB: менеджер APK, каталог F-Droid, проверка совместимости.

## Установка (Debian 13 / Ubuntu / Mint)
1. Скачайте `.deb` из раздела **Releases** (или из Actions → Artifacts).
2. `sudo apt install ./nevexona-droid_*_all.deb`
3. `sudo apt install adb`
   PySide6: если пакета `python3-pyside6.qtwidgets` нет в вашем дистрибутиве (старый Mint/Ubuntu), поставьте через pip: `pip install --user PySide6`
4. Установите Waydroid: https://docs.waydro.id/usage/install-on-desktops
5. Запустите из меню приложений или командой `nevexona-droid`, затем Android Engine → «Инициализировать Android».
6. На Dashboard: Start Android → Show Android. При первом ADB-подключении подтвердите диалог отладки в окне Android.

Из исходников: `./install.sh` (спросит согласие перед установкой системных пакетов). Удаление: `./uninstall.sh`.

## Требования
x86_64/aarch64, от 2 ГБ RAM (рекомендуется 4+), от 8 ГБ места, ядро с binder, Wayland-сессия рекомендуется.
Приложение проверяет это само (Android Engine → «Проверить совместимость») и не обещает работу на неподдерживаемом железе.

## Статус
Окно, APK Manager, App Store (F-Droid, проверка SHA-256), My Apps, Settings и Compatibility Checker реализованы и собираются в CI.
Работа с живым Waydroid ещё не проверена на реальной машине. Не сделано: иконки приложений, переключение языка интерфейса, AppImage.

## Разработка
    pip install -r requirements-dev.txt
    python3 -m pytest
    ./packaging/build_deb.sh
