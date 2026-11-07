#!/usr/bin/env bash
# Сборка .deb: ./packaging/build_deb.sh  ->  dist/nevexona-droid_<версия>_all.deb
set -euo pipefail
cd "$(dirname "$0")/.."
VER=$(python3 -c "import re;print(re.search(r'\"(.+)\"',open('nevexona_droid/__init__.py').read()).group(1))")
ROOT=build/pkg
rm -rf build/pkg && mkdir -p "$ROOT/DEBIAN" "$ROOT/opt/nevexona-droid" "$ROOT/usr/bin" \
  "$ROOT/usr/share/applications" "$ROOT/usr/share/icons/hicolor/scalable/apps"
cp -r nevexona_droid "$ROOT/opt/nevexona-droid/"
find "$ROOT" -name __pycache__ -prune -exec rm -rf {} +
cat > "$ROOT/usr/bin/nevexona-droid" <<'LAUNCH'
#!/bin/sh
PY=python3
[ -x /opt/nevexona-droid/venv/bin/python ] && PY=/opt/nevexona-droid/venv/bin/python
PYTHONPATH=/opt/nevexona-droid exec "$PY" -m nevexona_droid "$@"
LAUNCH
chmod 755 "$ROOT/usr/bin/nevexona-droid"
cp packaging/nevexona-droid.desktop "$ROOT/usr/share/applications/"
cp packaging/nevexona-droid.svg "$ROOT/usr/share/icons/hicolor/scalable/apps/"
cat > "$ROOT/DEBIAN/control" <<CTL
Package: nevexona-droid
Version: $VER
Section: utils
Priority: optional
Architecture: all
Maintainer: NEVEXONA Corporation <noreply@nevexona.invalid>
Depends: python3 (>= 3.10), python3-venv
Recommends: adb, waydroid, libxcb-cursor0, libxkbcommon-x11-0, libegl1, libgl1
Homepage: https://github.com/Mr-Profik1/Nevexona-Droid
Description: NEVEXONA Droid - Android apps on Linux
 Graphical manager for Waydroid and ADB: install APKs, F-Droid catalog.
 Waydroid is installed separately (see README).
CTL
cat > "$ROOT/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
python3 -m compileall -q /opt/nevexona-droid || true
# Если PySide6 нет в системе, ставим его в отдельное окружение (нужен интернет).
if ! python3 -c "from PySide6 import QtWidgets" 2>/dev/null; then
  if [ ! -x /opt/nevexona-droid/venv/bin/python ]; then
    echo "NEVEXONA Droid: PySide6 не найден, ставлю в /opt/nevexona-droid/venv (скачается около 100 МБ)..."
    python3 -m venv --system-site-packages /opt/nevexona-droid/venv || true
    /opt/nevexona-droid/venv/bin/pip install --no-input PySide6-Essentials \
      || echo "NEVEXONA Droid: не удалось поставить PySide6. Проверьте интернет и выполните: sudo apt install --reinstall nevexona-droid"
  fi
fi
exit 0
POST
cat > "$ROOT/DEBIAN/prerm" <<'PRE'
#!/bin/sh
set -e
find /opt/nevexona-droid -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
case "$1" in remove|purge) rm -rf /opt/nevexona-droid/venv ;; esac
exit 0
PRE
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/prerm"
mkdir -p dist
dpkg-deb --root-owner-group --build "$ROOT" "dist/nevexona-droid_${VER}_all.deb"
