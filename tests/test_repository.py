import hashlib
import pytest
from nevexona_droid.core import repository as r

INDEX = {
    "apps": [
        {"packageName": "org.a", "name": "Alpha", "summary": "notes app", "categories": ["Writing"], "icon": "a.png"},
        {"packageName": "org.nohash", "name": "Bad"},
        {"packageName": "org.nopkg", "name": "Empty"},
    ],
    "packages": {
        "org.a": [{"versionName": "1", "versionCode": 1, "apkName": "a_1.apk", "hash": "AA", "hashType": "sha256", "size": 5},
                  {"versionName": "2", "versionCode": 2, "apkName": "a_2.apk", "hash": "BB", "hashType": "sha256", "size": 6}],
        "org.nohash": [{"versionCode": 1, "apkName": "x.apk"}],
    },
}


def test_parse_skips_unverifiable_and_picks_latest():
    apps = r.parse_index(INDEX)
    assert [a.package for a in apps] == ["org.a"]
    assert apps[0].apk_name == "a_2.apk" and apps[0].sha256 == "bb"


def test_search_and_categories():
    apps = r.parse_index(INDEX)
    assert r.search(apps, "NOTES") and not r.search(apps, "zzz")
    assert r.search(apps, category="Writing") and not r.search(apps, category="Games")
    assert r.categories(apps) == ["Writing"]


def test_rejects_http_and_path_traversal(tmp_path):
    a = r.parse_index(INDEX)[0]
    a.repo = "http://evil"
    with pytest.raises(r.RepoError):
        r.download(a, tmp_path)
    a.repo, a.apk_name = "https://x", "../etc/passwd"
    with pytest.raises(r.RepoError):
        r.download(a, tmp_path)


def test_checksum_mismatch_removes_file(tmp_path, monkeypatch):
    import io
    class Resp(io.BytesIO):
        headers = {"Content-Length": "4"}
        def __enter__(self): return self
        def __exit__(self, *a): pass
    monkeypatch.setattr(r.urllib.request, "urlopen", lambda *a, **k: Resp(b"data"))
    a = r.parse_index(INDEX)[0]
    with pytest.raises(r.RepoError):
        r.download(a, tmp_path)
    assert list(tmp_path.iterdir()) == []
    a.sha256 = hashlib.sha256(b"data").hexdigest()
    assert r.download(a, tmp_path).endswith("a_2.apk")
