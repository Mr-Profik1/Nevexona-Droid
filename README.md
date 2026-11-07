# NEVEXONA Droid — Android Apps On Linux

Linux-приложение для запуска Android-приложений через Waydroid и ADB: менеджер APK, каталог F-Droid, проверка совместимости системы. Waydroid ставится отдельно (см. установку ниже).

## Быстрая установка (одной командой)
Вставьте в терминал целиком. Скачает исходники, соберёт и поставит пакет, спросит согласие перед установкой системных пакетов:
```
sudo apt update && sudo apt install -y git && git clone https://github.com/Mr-Profik1/Nevexona-Droid && cd Nevexona-Droid && ./install.sh
```
После установки запуск: `nevexona-droid`. Waydroid ставится отдельно (шаг 4 ниже).

## Установка вручную (Debian 13 / Ubuntu / Mint)
1. Скачайте `.deb` из раздела **Releases** (или из Actions → Artifacts). Если скачался `.zip`, распакуйте его.
2. Откройте терминал в папке с файлом и поставьте зависимости:
   ```
   sudo apt update
   sudo apt install adb python3-pip
   sudo apt install python3-pyside6.qtwidgets
   ```
   Если пакет `python3-pyside6.qtwidgets` не найден, поставьте PySide6 через pip:
   ```
   pip install --user --break-system-packages PySide6
   ```
   (Флаг `--break-system-packages` нужен на новых системах, где pip пишет `externally-managed-environment`.)
3. Установите пакет:
   ```
   sudo apt install ./nevexona-droid_*_all.deb
   ```
   Если пишет «Неразрешимая зависимость: python3-pyside6.qtwidgets» (старая версия пакета), выполните:
   ```
   sudo dpkg -i --ignore-depends=python3-pyside6.qtwidgets nevexona-droid_*_all.deb
   ```
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
