#!/usr/bin/env bash
# Установка Джарвиса на Linux (Debian/Ubuntu/Mint): команда `jarvis`, значок, горячая клавиша Alt+7 (Cinnamon).
# Ключ ИИ можно передать переменными: curl ... | JARVIS_API_KEY=... [JARVIS_MODEL=...] [JARVIS_BASE_URL=...] bash
set -euo pipefail
BASE=https://raw.githubusercontent.com/Mr-Profik1/Nevexona-Droid/main/jarvis
DIR="$HOME/.local/share/jarvis"
BIN="$HOME/.local/bin"
CONF="$HOME/.config/jarvis"
mkdir -p "$DIR" "$BIN" "$CONF" "$HOME/.local/share/applications"

if command -v apt-get >/dev/null; then
  # python3 и curl обязательны; espeak-ng (голос), xdotool и scrot (управление экраном) по желанию
  sudo apt-get install -y python3 curl || { echo "Не удалось поставить python3 и curl."; exit 1; }
  for p in python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 espeak-ng xdotool scrot imagemagick; do
    sudo apt-get install -y "$p" || echo "Не удалось поставить $p (окно приложения, голос или управление экраном могут не работать)."
  done
else
  echo "apt-get не найден: поставьте вручную python3, curl, espeak-ng, xdotool, scrot."
fi

for f in jarvis.py jarvis_web.py; do
  src="$(dirname "$0")/$f"
  if [ -f "$src" ]; then cp "$src" "$DIR/$f"; else curl -fsSL "$BASE/$f" -o "$DIR/$f"; fi
done

# jarvis = окно в браузере, jarvis-cli = терминал
cat > "$BIN/jarvis" <<EOF
#!/bin/sh
exec python3 "$DIR/jarvis_web.py" "\$@"
EOF
cat > "$BIN/jarvis-cli" <<EOF
#!/bin/sh
exec python3 "$DIR/jarvis.py" "\$@"
EOF
chmod +x "$BIN/jarvis" "$BIN/jarvis-cli"

if [ -n "${JARVIS_API_KEY:-}" ]; then
  umask 077
  printf 'JARVIS_BASE_URL="%s"\nJARVIS_API_KEY="%s"\nJARVIS_MODEL="%s"\nJARVIS_VISION_MODEL="%s"\n' \
    "${JARVIS_BASE_URL:-https://openrouter.ai/api/v1}" "$JARVIS_API_KEY" \
    "${JARVIS_MODEL:-openrouter/free}" "${JARVIS_VISION_MODEL:-nvidia/nemotron-3.5-super-vl:free}" > "$CONF/config"
  chmod 600 "$CONF/config"
  echo "Настройки ИИ сохранены в $CONF/config"
fi

cat > "$HOME/.local/share/applications/jarvis.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Джарвис
Comment=Помощник
Exec=$BIN/jarvis
Icon=utilities-terminal
Terminal=false
Categories=Utility;
EOF

desk="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$desk" ]; then
  cp "$HOME/.local/share/applications/jarvis.desktop" "$desk/Джарвис.desktop"
  chmod +x "$desk/Джарвис.desktop"
  gio set "$desk/Джарвис.desktop" metadata::trusted true 2>/dev/null || true
fi

# Горячая клавиша Alt+7 (Cinnamon). Если не сработает, задайте её в Параметры -> Клавиатура -> Сочетания.
if command -v gsettings >/dev/null && gsettings list-schemas | grep -q '^org.cinnamon.desktop.keybindings$'; then
  p=/org/cinnamon/desktop/keybindings/custom-keybindings/jarvis/
  s="org.cinnamon.desktop.keybindings.custom-keybinding:$p"
  gsettings set "$s" name 'Джарвис' || true
  gsettings set "$s" command "$BIN/jarvis" || true
  gsettings set "$s" binding "['<Alt>7']" || true
  cur=$(gsettings get org.cinnamon.desktop.keybindings custom-list)
  case "$cur" in
    *"'jarvis'"*) ;;
    "@as []"|"[]") gsettings set org.cinnamon.desktop.keybindings custom-list "['jarvis']" || true ;;
    *) gsettings set org.cinnamon.desktop.keybindings custom-list "${cur%]}, 'jarvis']" || true ;;
  esac
fi

echo
echo "Готово. Запуск: $BIN/jarvis (или значок «Джарвис», Alt+7 в Cinnamon). Терминальная версия: jarvis-cli."
echo "Защита: в окне нажмите «PIN» и задайте PIN-код."
[ -n "${JARVIS_API_KEY:-}" ] || echo "Подключить ИИ: в окне нажмите «Настройки»."
case ":$PATH:" in *":$BIN:"*) ;; *) echo "Если команда jarvis не находится, перезайдите в сеанс или запускайте $BIN/jarvis" ;; esac
