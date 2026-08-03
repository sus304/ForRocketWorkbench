"""Single source of truth for the Workbench version.

Before this module the version was written down twice, by hand, in two CLI entry points
(`runner.py`'s ver_runner_tool and `post.py`'s ver_post_tool) and nowhere else — so the product
had no version a running service could report, and the two hand-written strings had drifted away
from the release tags. Everything that shows a version now reads it from here.

`__version__` is the *declared* version and is bumped by hand at a release. `workbench_version()`
adds the build identity from git (commits since the tag, short sha, and a `.dirty` marker for an
unclean checkout), which is what makes a deployed service identifiable:

    2.1.0                    (no git checkout — e.g. an unpacked source tree)
    2.1.0+111.gb246ef1       (111 commits past the last v-tag)
    2.1.0+111.gb246ef1.dirty (uncommitted changes present — should never appear on the server,
                              which only ever fast-forwards)

The git query runs at most once per process (it is a subprocess call, and /health and the UI
header ask for the version constantly).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

__version__ = "2.2.0"

_REPO_ROOT = Path(__file__).resolve().parent

_cached: Optional[str] = None


def _git_describe() -> str:
    """`git describe` output for the repo this file lives in, or '' if unavailable.

    Never raises: a source tree without git, without a checkout, or with git missing entirely
    simply has no build identity, and the declared version stands alone.
    """
    try:
        out = subprocess.run(
            ["git", "describe", "--always", "--dirty", "--match", "v[0-9]*"],
            cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if out.returncode != 0:
        return ""
    return out.stdout.strip()


def build_id(describe: Optional[str] = None) -> str:
    """Normalise `git describe` output into a PEP 440 local-version segment (no leading '+').

    Pure so it can be unit-tested against the shapes git actually emits:
        v2.0.5-111-gb246ef1        -> 111.gb246ef1
        v2.0.5-111-gb246ef1-dirty  -> 111.gb246ef1.dirty
        v2.0.5                     -> ''            (exactly on the tag: nothing to add)
        v2.0.5-dirty               -> dirty
        b246ef1                    -> gb246ef1      (no tag reachable; g-prefixed like describe)
        b246ef1-dirty              -> gb246ef1.dirty
    """
    if describe is None:
        describe = _git_describe()
    if not describe:
        return ""
    parts = describe.split("-")
    dirty = parts[-1] == "dirty"
    if dirty:
        parts = parts[:-1]
    segs = []
    if len(parts) >= 3 and parts[-1].startswith("g"):
        segs = [parts[-2], parts[-1]]          # "<n>", "g<sha>" from a tag description
    elif len(parts) == 1 and not parts[0].startswith("v"):
        segs = ["g" + parts[0]]                # bare sha (no tag reachable)
    if dirty:
        segs.append("dirty")
    return ".".join(segs)


def workbench_version() -> str:
    """The full version string: declared version plus build identity. Cached per process."""
    global _cached
    if _cached is None:
        build = build_id()
        _cached = f"{__version__}+{build}" if build else __version__
    return _cached
