"""Repository Manager: каталог F-Droid (index-v1.json) и безопасная загрузка APK."""
import hashlib
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass

FDROID = "https://f-droid.org/repo"


class RepoError(Exception):
    pass


@dataclass
class App:
    package: str
    name: str
    summary: str
    description: str
    categories: list
    version: str
    apk_name: str
    sha256: str
    size: int
    icon: str
    repo: str


def parse_index(data: dict, repo=FDROID):
    """Только приложения, у которых есть реальный APK с контрольной суммой."""
    out = []
    for a in data.get("apps", []):
        pkg = a.get("packageName")
        versions = data.get("packages", {}).get(pkg) or []
        if not pkg or not versions:
            continue
        v = max(versions, key=lambda x: x.get("versionCode", 0))
        if not v.get("apkName") or v.get("hashType") != "sha256" or not v.get("hash"):
            continue
        loc = a.get("localized", {}).get("en-US", {})
        out.append(App(
            package=pkg,
            name=a.get("name") or loc.get("name") or pkg,
            summary=a.get("summary") or loc.get("summary", ""),
            description=a.get("description") or loc.get("description", ""),
            categories=a.get("categories", []),
            version=v.get("versionName", ""),
            apk_name=v["apkName"], sha256=v["hash"].lower(),
            size=v.get("size", 0),
            icon=f"{repo}/icons/{a['icon']}" if a.get("icon") else "",
            repo=repo,
        ))
    return sorted(out, key=lambda x: x.name.lower())


def search(apps, query="", category=None):
    q = query.strip().lower()
    return [a for a in apps
            if (not category or category in a.categories)
            and (not q or q in a.name.lower() or q in a.summary.lower() or q in a.package.lower())]


def categories(apps):
    return sorted({c for a in apps for c in a.categories})


def _https(url):
    if urllib.parse.urlparse(url).scheme != "https":
        raise RepoError("Разрешены только HTTPS-источники")


def fetch_index(repo=FDROID, timeout=60):
    url = f"{repo}/index-v1.json"
    _https(url)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return parse_index(json.load(r), repo)
    except Exception as e:
        raise RepoError(f"Каталог недоступен: {e}") from e


def download(app: App, dest_dir, progress=None, timeout=60):
    """Скачивает APK, проверяет SHA-256 и размер. Битый файл удаляется."""
    if os.path.basename(app.apk_name) != app.apk_name:
        raise RepoError("Недопустимое имя файла в каталоге")
    url = f"{app.repo}/{urllib.parse.quote(app.apk_name)}"
    _https(url)
    os.makedirs(dest_dir, exist_ok=True)
    final = os.path.join(dest_dir, app.apk_name)
    part = final + ".part"
    h, got = hashlib.sha256(), 0
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or app.size or 0)
            while chunk := r.read(65536):
                f.write(chunk); h.update(chunk); got += len(chunk)
                if progress:
                    progress(got, total)
        if h.hexdigest() != app.sha256:
            raise RepoError("SHA-256 не совпал: файл повреждён или подменён")
        os.replace(part, final)
        return final
    except RepoError:
        raise
    except Exception as e:
        raise RepoError(f"Загрузка не удалась: {e}") from e
    finally:
        if os.path.exists(part):
            os.remove(part)
