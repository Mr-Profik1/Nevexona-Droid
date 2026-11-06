ORANGE = "#FF781F"

PALETTES = {
    "dark": dict(bg="#171717", panel="#202020", card="#262626", text="#EDEDED", mute="#9A9A9A", line="#333333"),
    "light": dict(bg="#F5F5F5", panel="#FFFFFF", card="#FFFFFF", text="#1A1A1A", mute="#6B6B6B", line="#DDDDDD"),
}


def stylesheet(theme: str) -> str:
    p = PALETTES.get(theme, PALETTES["dark"])
    return f"""
QWidget {{ background:{p['bg']}; color:{p['text']}; font-size:14px; }}
QListWidget#nav {{ background:{p['panel']}; border:none; min-width:170px; max-width:170px; padding:8px; }}
QListWidget#nav::item {{ padding:10px 12px; border-radius:6px; }}
QListWidget#nav::item:selected {{ background:{ORANGE}; color:#111; }}
QListWidget, QPlainTextEdit, QLineEdit, QComboBox {{ background:{p['card']}; border:1px solid {p['line']}; border-radius:6px; padding:4px; }}
QListWidget::item:selected {{ background:{ORANGE}; color:#111; }}
QPushButton {{ background:{p['card']}; border:1px solid {p['line']}; border-radius:6px; padding:7px 14px; }}
QPushButton:hover {{ border-color:{ORANGE}; }}
QPushButton:disabled {{ color:{p['mute']}; }}
QPushButton#primary {{ background:{ORANGE}; color:#111; border:none; font-weight:600; }}
QLabel#title {{ font-size:18px; font-weight:600; }}
QLabel#mute {{ color:{p['mute']}; }}
QLabel#status {{ font-size:16px; font-weight:600; color:{ORANGE}; }}
QProgressBar {{ border:1px solid {p['line']}; border-radius:6px; text-align:center; }}
QProgressBar::chunk {{ background:{ORANGE}; border-radius:5px; }}
"""
