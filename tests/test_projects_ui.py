"""Pure helpers behind the projects UI (web.service_ui.projects_ui). The NiceGUI page bodies are
manual/e2e; here we lock name sanitisation and the version-agnostic upload reading, which is what
broke across the NiceGUI 2.x (local) / 3.x (VM) split: 2.x gives a sync `e.content`, 3.x gives an
`e.file` whose `read()` is a coroutine."""
from __future__ import annotations

import asyncio
import io
import re

from web.service_ui.projects_ui import _sanitize_name, _upload_filename, _read_upload

_NAME_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class _Evt:
    """Stand-in for a NiceGUI upload event; the real class differs across versions."""
    def __init__(self, **attrs):
        self.__dict__.update(attrs)


class _AsyncFile:
    """NiceGUI 3.x FileUpload shape: `.name` and an async `read()`, no sync accessor."""
    def __init__(self, name, data):
        self.name = name
        self._data = data

    async def read(self):
        return self._data


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── name sanitisation ────────────────────────────────────────────────────────────

def test_sanitize_keeps_valid_names():
    assert _sanitize_name("MyRocket") == "MyRocket"
    assert _sanitize_name("ROCKET-A_1") == "ROCKET-A_1"


def test_sanitize_replaces_spaces_and_symbols():
    assert _sanitize_name("bad name!") == "bad_name"
    assert _sanitize_name("  spaced  ") == "spaced"


def test_sanitize_falls_back_when_empty_after_stripping():
    assert _sanitize_name("日本語") == "project"
    assert _sanitize_name("") == "project"


def test_sanitize_truncates_to_64():
    assert _sanitize_name("x" * 100) == "x" * 64


def test_sanitize_output_is_always_a_valid_store_name():
    for raw in ["bad name!", "日本語", "", "a/../b", "x" * 100, "..", "---", "ロケットA"]:
        assert _NAME_OK.match(_sanitize_name(raw)), raw


# ── filename across NiceGUI versions ──────────────────────────────────────────────

def test_upload_filename_2x_shapes():
    assert _upload_filename(_Evt(name="a.zip")) == "a.zip"
    assert _upload_filename(_Evt(file_name="b.zip")) == "b.zip"
    assert _upload_filename(_Evt(names=["d.zip"])) == "d.zip"
    assert _upload_filename(_Evt(type="application/zip")) == ""  # nothing usable → no crash


def test_upload_filename_3x_file_attribute():
    # VM's NiceGUI: only client/file/sender; filename lives on the FileUpload as `.name`.
    assert _upload_filename(_Evt(file=_AsyncFile("MyRocket.zip", b"z"))) == "MyRocket.zip"


# ── byte reading across NiceGUI versions (async) ──────────────────────────────────

def test_read_upload_3x_async_file():
    e = _Evt(file=_AsyncFile("p.zip", b"zip-bytes"), client=None, sender=None)
    assert _run(_read_upload(e)) == b"zip-bytes"


def test_read_upload_2x_sync_content():
    assert _run(_read_upload(_Evt(content=io.BytesIO(b"data")))) == b"data"


def test_read_upload_2x_content_at_eof_is_rewound():
    buf = io.BytesIO(b"payload")
    buf.read()  # framework already consumed it → cursor at EOF
    assert _run(_read_upload(_Evt(content=buf))) == b"payload"


def test_read_upload_handles_raw_and_missing():
    assert _run(_read_upload(_Evt(content=b"raw"))) == b"raw"
    assert _run(_read_upload(_Evt(contents=[io.BytesIO(b"multi")]))) == b"multi"
    assert _run(_read_upload(_Evt(type="x"))) == b""  # no content/file → empty, no crash
