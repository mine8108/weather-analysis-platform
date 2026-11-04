"""Regression checks for deployment reloads and self-contained downloads."""
import base64
import re
import subprocess
import sys
import tomllib
from html.parser import HTMLParser
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from modules.ui import downloads

ROOT = Path(__file__).resolve().parents[1]


class ButtonParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.attrs = {}
        self.labels = []

    def handle_starttag(self, tag, attrs):
        if tag == "button":
            self.attrs = dict(attrs)

    def handle_data(self, data):
        self.labels.append(data)


@pytest.mark.parametrize("data", [b"", b"\x00\x01\xff\n", "温度,℃\n21,1\n"])
def test_inline_download_freezes_exact_bytes_and_escapes_user_text(data):
    label = '<img src=x onerror="alert(1)">'
    filename = '观测"><script>alert(1)</script>.csv'
    html = downloads._inline_html(label, data, filename, "text/csv")
    parser = ButtonParser()
    parser.feed(html)
    encoded = re.search(r"const raw = atob\('([A-Za-z0-9+/=]*)'\)", html).group(1)
    assert base64.b64decode(encoded) == downloads._payload(data)
    assert parser.attrs["data-name"] == filename
    assert parser.attrs["data-mime"] == "text/csv"
    assert label in parser.labels
    assert '<img src=x' not in html and '<script>alert(1)</script>' not in html
    assert html.count("<script>") == 1


def test_small_download_is_rendered_in_sandbox_without_media_url():
    at = AppTest.from_string('''
from modules.ui.downloads import download_button
download_button("下载", b"hello", file_name="sample.txt", mime="text/plain", key="sample")
''').run()
    assert not at.exception
    frame = at.get("iframe")[0].proto
    assert "aGVsbG8=" in frame.srcdoc
    assert "/media/" not in frame.srcdoc
    assert "URL.createObjectURL" in frame.srcdoc
    assert not at.get("download_button")


def test_large_download_uses_deferred_snapshot_without_rerunning(monkeypatch):
    monkeypatch.setattr(downloads, "INLINE_LIMIT_BYTES", 3)
    captured = {}
    monkeypatch.setattr(downloads.st, "download_button", lambda label, data, **kwargs: captured.update(data=data, **kwargs))
    mutable = bytearray(b"original")
    downloads.download_button("下载", mutable, file_name="large.bin", mime="application/octet-stream", key="large")
    mutable[:] = b"changed!"
    assert captured["data"]() == b"original"
    assert captured["on_click"] == "ignore"
    assert captured["file_name"] == "large.bin"


def test_deployment_config_disables_watcher_and_documents_restart():
    config = tomllib.loads((ROOT / ".streamlit/config.toml").read_text(encoding="utf-8"))
    assert config["server"]["fileWatcherType"] == "none"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Reboot app" in readme and "仅推送代码不能确认新版本已生效" in readme


def test_streamlit_watcher_can_evict_module_during_another_thread_import():
    """Reproduce the upstream race in a subprocess without touching application modules."""
    code = r'''
import importlib, importlib.abc, importlib.util, sys, threading
from streamlit.watcher.local_sources_watcher import LocalSourcesWatcher
loading, release = threading.Event(), threading.Event()
class Loader(importlib.abc.Loader):
    def create_module(self, spec): return None
    def exec_module(self, module):
        loading.set()
        release.wait(5)
class Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        return importlib.util.spec_from_loader(fullname, Loader()) if fullname == "race_demo" else None
sys.meta_path.insert(0, Finder())
failures = []
def importing():
    try: importlib.import_module("race_demo")
    except Exception as exc: failures.append((type(exc).__name__, str(exc)))
thread = threading.Thread(target=importing)
thread.start()
assert loading.wait(5)
watcher = LocalSourcesWatcher.__new__(LocalSourcesWatcher)
watcher._pending_evictions_lock = threading.Lock()
watcher._pending_evictions = {"race_demo"}
watcher.flush_pending_evictions()
release.set()
thread.join(5)
assert not thread.is_alive()
assert failures == [("KeyError", "'race_demo'")], failures
'''
    result = subprocess.run([sys.executable, "-B", "-c", code],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
