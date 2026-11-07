#!/usr/bin/env bash
# Собирает пакет jarvis_<версия>_all.deb в jarvis/dist/. Код на чистом Python, поэтому один пакет
# ставится на amd64, arm64 и другие архитектуры (Linux Mint 22.x, Ubuntu 22.04+, Debian 12+).
# Нужен только dpkg-deb. Запуск: bash jarvis/packaging/build_deb.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$(dirname "$HERE")"
VER="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$SRC/jarvis.py" | head -1)"
[ -n "$VER" ] || { echo "Не нашёл VERSION в jarvis.py"; exit 1; }
OUT="$SRC/dist"
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT

install -d -m 755 "$ROOT/DEBIAN" "$ROOT/usr/lib/jarvis" "$ROOT/usr/bin" "$ROOT/usr/share/applications" \
  "$ROOT/usr/share/icons/hicolor/scalable/apps" "$ROOT/usr/share/doc/jarvis"
install -m 644 "$SRC/jarvis.py" "$SRC/jarvis_web.py" "$ROOT/usr/lib/jarvis/"
install -m 644 "$HERE/jarvis.svg" "$ROOT/usr/share/icons/hicolor/scalable/apps/jarvis.svg"
install -m 644 "$SRC/README.md" "$ROOT/usr/share/doc/jarvis/README.md"

cat > "$ROOT/usr/bin/jarvis" <<'EOF'
#!/bin/sh
exec python3 /usr/lib/jarvis/jarvis_web.py "$@"
EOF
cat > "$ROOT/usr/bin/jarvis-cli" <<'EOF'
#!/bin/sh
exec python3 /usr/lib/jarvis/jarvis.py "$@"
EOF
chmod 755 "$ROOT/usr/bin/jarvis" "$ROOT/usr/bin/jarvis-cli"

cat > "$ROOT/usr/share/applications/jarvis.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Джарвис
Name[en]=Jarvis
Comment=Помощник: чат, команды, управление экраном
Comment[en]=Assistant: chat, commands, screen control
Exec=jarvis
Icon=jarvis
Terminal=false
Categories=Utility;
Keywords=jarvis;assistant;джарвис;помощник;
EOF
chmod 644 "$ROOT/usr/share/applications/jarvis.desktop"

cat > "$ROOT/usr/share/doc/jarvis/copyright" <<'EOF'
Jarvis. Copyright (c) the Nevexona-Droid author (Mr-Profik1).
Исходники: https://github.com/Mr-Profik1/Nevexona-Droid/tree/main/jarvis
EOF
chmod 644 "$ROOT/usr/share/doc/jarvis/copyright"

SIZE="$(du -sk "$ROOT" | cut -f1)"
cat > "$ROOT/DEBIAN/control" <<EOF
Package: jarvis
Version: $VER
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), espeak-ng, xdotool, scrot, imagemagick, xdg-utils
Recommends: python3-gi, gir1.2-gtk-3.0, gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0, chromium | firefox | google-chrome-stable
Installed-Size: $SIZE
Maintainer: Mr-Profik1 <noreply@users.noreply.github.com>
Homepage: https://github.com/Mr-Profik1/Nevexona-Droid/tree/main/jarvis
Description: Джарвис, помощник с чатом, командами и управлением экраном
 Окно с чатом (русский и английский), ИИ через любой сервис с OpenAI-совместимым
 API, выполнение команд, управление экраном под X11 (xdotool), PIN-защита.
 Окно приложения на GTK и WebKitGTK; без них открывается в браузере.
 Запуск: команда jarvis или значок «Джарвис» в меню; терминальная версия: jarvis-cli.
EOF
chmod 644 "$ROOT/DEBIAN/control"

cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
  command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
fi
exit 0
EOF
chmod 755 "$ROOT/DEBIAN/postinst"

mkdir -p "$OUT"
rm -f "$OUT"/jarvis_*_all.deb
dpkg-deb --root-owner-group --build "$ROOT" "$OUT/jarvis_${VER}_all.deb" >/dev/null
echo "Готово: $OUT/jarvis_${VER}_all.deb"
