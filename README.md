# NEVEXONA Droid — Android Apps On Linux

Linux-приложение для запуска Android-приложений через Waydroid и ADB: менеджер APK, каталог F-Droid, проверка совместимости системы. Waydroid ставится отдельно (см. установку ниже).

## Установка: скопируйте и вставьте в терминал
Шаг 1. Установка (приложение, PySide6, adb, Waydroid). Нужны интернет и пароль sudo:
```
curl -fsSL https://raw.githubusercontent.com/Mr-Profik1/Nevexona-Droid/main/setup.sh | bash
```
Шаг 2. Запуск:
```
nevexona-droid
```
Шаг 3. В окне приложения нажмите Android Engine → «Инициализировать Android» (скачает образ Android около 1 ГБ). Затем на Dashboard: Start Android → Show Android.

Если что-то не запустилось, посмотрите состояние Waydroid и пришлите вывод в Issues:
```
sudo waydroid init
waydroid session start
```

Файл можно и скачать вручную: [setup.sh](https://raw.githubusercontent.com/Mr-Profik1/Nevexona-Droid/main/setup.sh), затем `bash setup.sh`.

## Установка вручную (Debian 13 / Ubuntu / Mint)
1. Скачайте `.deb` из раздела **Releases** (или из Actions → Artifacts). Если скачался `.zip`, распакуйте его.
2. Откройте терминал в папке с файлом и выполните (нужен интернет):
   ```
   sudo apt update
   sudo apt install ./nevexona-droid_*_all.deb
   ```
   Пакет сам доустановит PySide6 в `/opt/nevexona-droid/venv`, если его нет в системе (около 100 МБ). Отдельно ничего ставить не нужно.
3. Для работы с Android поставьте `adb`: `sudo apt install adb` (обычно ставится сам как рекомендуемый пакет).
   Если установка PySide6 не удалась (не было интернета), повторите: `sudo apt install --reinstall ./nevexona-droid_*_all.deb`.
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
