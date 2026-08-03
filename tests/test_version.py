"""The Workbench version string (version.py).

`build_id` is the only part with logic worth pinning: it normalises whatever `git describe`
emits into a local-version segment, and it runs on every service start and every /health call.
The shapes below are the ones git actually produces for this repo's tagging scheme.
"""
import version


def test_build_id_from_tag_description():
    assert version.build_id("v2.0.5-111-gb246ef1") == "111.gb246ef1"


def test_build_id_marks_a_dirty_checkout():
    assert version.build_id("v2.0.5-111-gb246ef1-dirty") == "111.gb246ef1.dirty"


def test_build_id_is_empty_exactly_on_a_tag():
    # Nothing to add: the declared version already says everything.
    assert version.build_id("v2.0.5") == ""
    assert version.build_id("v2.0.5-dirty") == "dirty"


def test_build_id_from_bare_sha_when_no_tag_is_reachable():
    assert version.build_id("b246ef1") == "gb246ef1"
    assert version.build_id("b246ef1-dirty") == "gb246ef1.dirty"


def test_build_id_tolerates_a_hyphenated_tag():
    assert version.build_id("v2.1.0-rc1-3-gabcdef0") == "3.gabcdef0"


def test_build_id_empty_without_git():
    assert version.build_id("") == ""


def test_workbench_version_starts_with_the_declared_version():
    v = version.workbench_version()
    assert v.startswith(version.__version__)
    assert v == version.workbench_version()  # cached, stable within a process
