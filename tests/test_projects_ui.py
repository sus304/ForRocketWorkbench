"""Pure helpers behind the projects UI (web.service_ui.projects_ui). The NiceGUI page bodies are
manual/e2e; here we lock name sanitisation, which decides whether an uploaded project lands with a
valid store name instead of failing far away with a cryptic 422."""
from __future__ import annotations

import io
import re

from web.service_ui.projects_ui import (
    _sanitize_name, _upload_filename, _upload_content, _read_upload_bytes,
)

_NAME_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class _Evt:
    """Minimal stand-in for a NiceGUI upload event with an arbitrary attribute set — the real
    class differs across NiceGUI versions (the VM lacked `.name`, which crashed the handler)."""
    def __init__(self, **attrs):
        self.__dict__.update(attrs)


def test_upload_filename_across_versions():
    assert _upload_filename(_Evt(name="a.zip")) == "a.zip"
    assert _upload_filename(_Evt(file_name="b.zip")) == "b.zip"
    assert _upload_filename(_Evt(filename="c.zip")) == "c.zip"
    assert _upload_filename(_Evt(names=["d.zip", "e.zip"])) == "d.zip"
    assert _upload_filename(_Evt(type="application/zip")) == ""  # no name attr at all → no crash


class _UploadFile:
    """Stand-in for Starlette's UploadFile as newer NiceGUI hands it to on_upload: a `.filename`
    and a SYNC underlying stream `.file` (its own read() would be async)."""
    def __init__(self, filename, data):
        self.filename = filename
        self.file = io.BytesIO(data)


def test_upload_content_across_versions():
    buf = io.BytesIO(b"data")
    assert _upload_content(_Evt(content=buf)) is buf
    buf2 = io.BytesIO(b"x")
    assert _upload_content(_Evt(contents=[buf2])) is buf2
    assert _upload_content(_Evt(name="only-name.zip")) is None  # no content → None, no crash


def test_upload_event_with_single_file_attribute():
    # The VM's NiceGUI: event exposes only client/file/sender; the file is a Starlette UploadFile.
    uf = _UploadFile("MyRocket.zip", b"zip-bytes")
    e = _Evt(file=uf, client=None, sender=None)
    assert _upload_filename(e) == "MyRocket.zip"
    assert _upload_content(e) is uf.file           # the sync inner stream, not the UploadFile
    assert _read_upload_bytes(_upload_content(e)) == b"zip-bytes"


def test_read_upload_bytes_handles_eof_stream():
    buf = io.BytesIO(b"payload")
    buf.read()  # framework already consumed it → cursor at EOF
    assert _read_upload_bytes(buf) == b"payload"  # we seek(0) first


def test_read_upload_bytes_handles_raw_and_str_and_none():
    assert _read_upload_bytes(b"raw") == b"raw"
    assert _read_upload_bytes(bytearray(b"ba")) == b"ba"
    assert _read_upload_bytes(io.StringIO("text")) == b"text"
    assert _read_upload_bytes(None) == b""


def test_sanitize_keeps_valid_names():
    assert _sanitize_name("MyRocket") == "MyRocket"
    assert _sanitize_name("ROCKET-A_1") == "ROCKET-A_1"


def test_sanitize_replaces_spaces_and_symbols():
    assert _sanitize_name("bad name!") == "bad_name"
    assert _sanitize_name("  spaced  ") == "spaced"


def test_sanitize_falls_back_when_empty_after_stripping():
    # a fully non-ASCII name has nothing left → a usable default, never an invalid store name
    assert _sanitize_name("日本語") == "project"
    assert _sanitize_name("") == "project"


def test_sanitize_truncates_to_64():
    assert _sanitize_name("x" * 100) == "x" * 64


def test_sanitize_output_is_always_a_valid_store_name():
    for raw in ["bad name!", "日本語", "", "a/../b", "x" * 100, "..", "---", "ロケットA"]:
        assert _NAME_OK.match(_sanitize_name(raw)), raw
