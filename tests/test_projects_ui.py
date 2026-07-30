"""Pure helpers behind the projects UI (web.service_ui.projects_ui). The NiceGUI page bodies are
manual/e2e; here we lock name sanitisation, which decides whether an uploaded project lands with a
valid store name instead of failing far away with a cryptic 422."""
from __future__ import annotations

import re

from web.service_ui.projects_ui import _sanitize_name

_NAME_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


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
