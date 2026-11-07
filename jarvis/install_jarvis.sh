#!/usr/bin/env bash
# Установка Джарвиса: команда `jarvis`, иконка на рабочем столе и в меню, горячая клавиша Alt+7 (Cinnamon).
set -euo pipefail
BASE=https://raw.githubusercontent.com/Mr-Profik1/Nevexona-Droid/main/jarvis
DIR="$HOME/.local/share/jarvis"
BIN="$HOME/.local/bin"
mkdir -p "$DIR" "$BIN" "$HOME/.local/share/applications"

sudo apt-get install -y espeak-ng || echo "Не удалось поставить espeak-ng, голоса не будет."

src="$(dirname "$0")/jarvis.py"
if [ -f "$src" ]; then cp "$src" "$DIR/jarvis.py"; else curl -fsSL "$BASE/jarvis.py" -o "$DIR/jarvis.py"; fi

cat > "$BIN/jarvis" <<EOF
#!/bin/sh
exec python3 "$DIR/jarvis.py" "\$@"
EOF
chmod +x "$BIN/jarvis"

cat > "$HOME/.local/share/applications/jarvis.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Джарвис
Comment=Голосовой помощник
Exec=$BIN/jarvis
Icon=utilities-terminal
Terminal=true
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
  gsettings set "$s" command "x-terminal-emulator -e $BIN/jarvis" || true
  gsettings set "$s" binding "['<Alt>7']" || true
  cur=$(gsettings get org.cinnamon.desktop.keybindings custom-list)
  case "$cur" in
    *"'jarvis'"*) ;;
    "@as []"|"[]") gsettings set org.cinnamon.desktop.keybindings custom-list "['jarvis']" || true ;;
    *) gsettings set org.cinnamon.desktop.keybindings custom-list "${cur%]}, 'jarvis']" || true ;;
  esac
fi

echo
echo "Готово. Запуск: значок «Джарвис» на рабочем столе или в меню, сочетание Alt+7, команда: $BIN/jarvis"
echo "Подключить ИИ: запустите Джарвиса и напишите «настройка»."
