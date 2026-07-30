"""Pure helpers behind the projects UI (web.service_ui.projects_ui). The NiceGUI page bodies are
manual/e2e; here we lock name sanitisation, which decides whether an uploaded project lands with a
valid store name instead of failing far away with a cryptic 422."""
from __future__ import annotations

import io
import re

from web.service_ui.projects_ui import _sanitize_name, _upload_filename, _upload_content

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


def test_upload_content_across_versions():
    buf = io.BytesIO(b"data")
    assert _upload_content(_Evt(content=buf)) is buf
    buf2 = io.BytesIO(b"x")
    assert _upload_content(_Evt(contents=[buf2])) is buf2
    assert _upload_content(_Evt(name="only-name.zip")) is None  # no content → None, no crash


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
