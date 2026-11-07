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
printf '#!/bin/sh\nPYTHONPATH=/opt/nevexona-droid exec python3 -m nevexona_droid "$@"\n' > "$ROOT/usr/bin/nevexona-droid"
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
Depends: python3 (>= 3.10)
Recommends: python3-pyside6.qtwidgets, adb, waydroid
Homepage: https://github.com/Mr-Profik1/Nevexona-Droid
Description: NEVEXONA Droid - Android apps on Linux
 Graphical manager for Waydroid and ADB: install APKs, F-Droid catalog.
 Waydroid is installed separately (see README).
CTL
printf '#!/bin/sh\nset -e\npython3 -m compileall -q /opt/nevexona-droid || true\n' > "$ROOT/DEBIAN/postinst"
printf '#!/bin/sh\nset -e\nfind /opt/nevexona-droid -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true\n' > "$ROOT/DEBIAN/prerm"
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/prerm"
mkdir -p dist
dpkg-deb --root-owner-group --build "$ROOT" "dist/nevexona-droid_${VER}_all.deb"
