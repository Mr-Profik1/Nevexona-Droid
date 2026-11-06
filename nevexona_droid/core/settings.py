"""Settings Manager: настройки и история в SQLite."""
import sqlite3
import time
from pathlib import Path

DEFAULTS = {
    "language": "ru", "theme": "dark", "resolution": "1280x720",
    "adb_host": "192.168.240.112:5555", "auto_check": "1",
    "download_dir": str(Path.home() / "Downloads"),
    "apk_dir": str(Path.home() / "Downloads"),
}


class Settings:
    def __init__(self, path=None):
        path = path or Path.home() / ".local/share/nevexona-droid/data.db"
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.execute("CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS launches(pkg TEXT, ts REAL)")
        self.db.commit()

    def get(self, key):
        row = self.db.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
        return row[0] if row else DEFAULTS[key]

    def set(self, key, value):
        if key not in DEFAULTS:
            raise KeyError(key)
        self.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, str(value)))
        self.db.commit()

    def log_launch(self, pkg):
        self.db.execute("INSERT INTO launches VALUES(?,?)", (pkg, time.time()))
        self.db.commit()

    def recent(self, n=5):
        rows = self.db.execute("SELECT pkg FROM launches GROUP BY pkg "
                               "ORDER BY MAX(ts) DESC LIMIT ?", (n,)).fetchall()
        return [r[0] for r in rows]
