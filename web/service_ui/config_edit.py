"""Pure helpers for the generic project config editor (docs/ui_refresh_design.md §4).

v1 editor: the browser renders the project's JSON config files as flat, typed leaf fields (the
faithful typed-form port of the legacy calculate.py builders — including sensitivity's dynamic
CRUD — is a follow-up UX upgrade, per review N-4). These helpers flatten a config dict to
editable leaves and apply edited leaves back, preserving structure and value types.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Tuple

_INDEX = re.compile(r"^\[(\d+)\]$")


def flatten_config(obj: Any, prefix: str = "") -> Dict[str, Any]:
    """Nested dict/list -> {dotted_path: scalar_leaf}. Lists use [i] segments."""
    out: Dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.update(flatten_config(v, key))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten_config(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def _split(path: str) -> List[str]:
    # "a.b[2].c" -> ["a", "b", "[2]", "c"]
    segs: List[str] = []
    for part in path.split("."):
        m = re.findall(r"\[\d+\]", part)
        base = re.sub(r"\[\d+\]", "", part)
        if base:
            segs.append(base)
        segs.extend(m)
    return segs


def _coerce(old: Any, new: Any) -> Any:
    """Coerce an edited value back to the original leaf's type (form inputs give strings)."""
    if isinstance(old, bool):
        return new in (True, "true", "True", "1", 1)
    if isinstance(old, int) and not isinstance(old, bool):
        try:
            return int(new)
        except (ValueError, TypeError):
            return old
    if isinstance(old, float):
        try:
            return float(new)
        except (ValueError, TypeError):
            return old
    return "" if new is None else new


def apply_edits(original: dict, edits: Dict[str, Any]) -> dict:
    """Return a deep copy of `original` with edited leaves set. Only existing scalar leaves are
    updated (no add/remove of keys); unknown paths are ignored."""
    result = copy.deepcopy(original)
    for path, new_val in edits.items():
        segs = _split(path)
        cur = result
        ok = True
        for seg in segs[:-1]:
            m = _INDEX.match(seg)
            if m:
                idx = int(m.group(1))
                if not isinstance(cur, list) or idx >= len(cur):
                    ok = False
                    break
                cur = cur[idx]
            else:
                if not isinstance(cur, dict) or seg not in cur:
                    ok = False
                    break
                cur = cur[seg]
        if not ok:
            continue
        last = segs[-1]
        m = _INDEX.match(last)
        if m:
            idx = int(m.group(1))
            if isinstance(cur, list) and idx < len(cur):
                cur[idx] = _coerce(cur[idx], new_val)
        elif isinstance(cur, dict) and last in cur:
            cur[last] = _coerce(cur[last], new_val)
    return result
