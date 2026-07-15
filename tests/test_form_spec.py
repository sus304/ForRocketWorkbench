"""Form <-> solver-input-spec parity guard for the web UI editor forms.

The form builders in web/pages/calculate.py and web/pages/editor.py are
hand-maintained twins, and the key set they write must track the solver input
spec (projects/example/*.json and runner_tool.json_api). Each form is built
headlessly (no UI server; NiceGUI attaches elements to the auto-index client)
and the key-path sets written by its collect() are compared, so a field added
to only one page, a missing input widget, or a Save that drops keys fails here
instead of in production.
"""
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip('nicegui')
# web.pages.calculate pulls in web.services.calc_service, whose module-level
# PEP 604 annotations need 3.10+. CI runs 3.10, so these never silently vanish.
pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 10),
    reason='web.pages.calculate requires Python 3.10+; runs in CI',
)

_EXAMPLE_DIR = Path(__file__).resolve().parent.parent / 'projects' / 'example'

# All form-editable config files, and the subset whose form exists in BOTH
# calculate.py and editor.py. Kept as literals so parametrize ids are stable;
# test_file_lists_match_parametrization pins them to the product lists.
_ALL_FILES = [
    'config_solver.json', 'param_list_stage1.json', 'param_rocket.json',
    'param_engine.json', 'sequence_of_event.json',
    'config_area.json', 'config_montecarlo.json', 'config_sensitivity.json',
]
_SHARED_FILES = _ALL_FILES[:5]

# Keys present in the example configs that no form manages on purpose.
_NOT_FORM_MANAGED = {
    'config_solver.json': {
        ('Number of Stage',),          # stage count / config lists are managed by
        ('Stage1 Config File List',),  # the run setup, not the Solver Config form
        ('Stage2 Config File List',),
        ('Stage3 Config File List',),
    },
}


def _is_comment(path):
    # 'Comment *' keys are in-JSON annotations for human readers, not form fields
    return any(seg.startswith('Comment ') for seg in path)


def _key_paths(d, prefix=()):
    """Recursive key-path set of a JSON dict; lists and scalars are leaves."""
    paths = set()
    for k, v in d.items():
        p = prefix + (k,)
        if isinstance(v, dict):
            paths |= _key_paths(v, p)
        else:
            paths.add(p)
    return paths


def _written_paths(builder, data):
    """Build a form headlessly and return the key paths its collect() writes."""
    from nicegui import ui
    collect = builder(dict(data), ui.column())
    return _key_paths(collect())


def _example(fname):
    return json.loads((_EXAMPLE_DIR / fname).read_text())


@pytest.fixture(scope='module')
def calculate():
    import web.pages.calculate as calculate
    return calculate


@pytest.fixture(scope='module')
def editor():
    import web.pages.editor as editor
    return editor


def test_file_lists_match_parametrization(calculate, editor):
    assert list(calculate._EDITABLE_FILES) == _ALL_FILES
    assert set(calculate._FORM_BUILDERS) == set(_ALL_FILES)
    assert set(editor._FORM_BUILDERS) == set(_SHARED_FILES)
    for fname in _SHARED_FILES:
        assert editor._FILE_LABELS[fname] == calculate._FILE_LABELS[fname]


@pytest.mark.parametrize('fname', _SHARED_FILES)
def test_calculate_and_editor_forms_write_same_keys(calculate, editor, fname):
    """A form change applied to only one of the two duplicated pages fails here."""
    calc_keys = _written_paths(calculate._FORM_BUILDERS[fname], {})
    ed_keys = _written_paths(editor._FORM_BUILDERS[fname], {})
    assert calc_keys == ed_keys, (
        f'{fname}: form fields drifted between calculate.py and editor.py\n'
        f'  only in calculate.py: {sorted(calc_keys - ed_keys)}\n'
        f'  only in editor.py:    {sorted(ed_keys - calc_keys)}'
    )


@pytest.mark.parametrize('fname', _ALL_FILES)
def test_form_fields_match_example_spec(calculate, fname):
    """Bidirectional check between the form fields and projects/example."""
    example_keys = _key_paths(_example(fname))
    form_keys = _written_paths(calculate._FORM_BUILDERS[fname], {})
    expected = {p for p in example_keys if not _is_comment(p)}
    expected -= _NOT_FORM_MANAGED.get(fname, set())
    missing_field = expected - form_keys
    missing_example = form_keys - example_keys
    assert not missing_field, (
        f'{fname}: keys in projects/example with no form field '
        f'(missing input widget?): {sorted(missing_field)}')
    assert not missing_example, (
        f'{fname}: form writes keys absent from projects/example '
        f'(example config not updated?): {sorted(missing_example)}')


@pytest.mark.parametrize('fname', _ALL_FILES)
def test_open_save_roundtrip_drops_no_keys(calculate, fname):
    """Opening the example in the form and saving untouched must not drop keys."""
    example = _example(fname)
    saved = _written_paths(calculate._FORM_BUILDERS[fname], example)
    lost = {p for p in _key_paths(example) - saved if not _is_comment(p)}
    assert not lost, (
        f'{fname}: open -> save with no edits drops keys: {sorted(lost)}')


def test_mc_and_sensitivity_param_names_match_runner(calculate):
    """The 'Keep in sync' contract between the form defs and the runners."""
    from runner_tool import runner_montecarlo, runner_sensitivity
    mc_names = {name for name, _, _ in calculate._MC_ERROR_PARAMS_DEF}
    assert mc_names == (set(runner_montecarlo._SCALAR_PARAM_REGISTRY)
                        | {'Wind', 'CA', 'Thrust', 'XCG', 'MOI'})
    sens_names = {name for name, _ in calculate._SENS_PARAM_DEFS}
    assert sens_names == set(runner_sensitivity._AVAILABLE_PARAMS)
    assert calculate._SENS_POI_PARAMS == set(runner_montecarlo._POI_PARAM_NAMES)


def test_forms_cover_file_input_specs(calculate):
    """Every json_api file-input spec key has a form field, even ones the example
    ships disabled (the spec lists are the single source of truth; see
    tests/_selfcontained.py for the same pattern on the runner side)."""
    from runner_tool import json_api
    for fname, specs in (
        ('param_rocket.json', json_api.ROCKET_FILE_INPUT_SPECS),
        ('param_engine.json', json_api.ENGINE_FILE_INPUT_SPECS),
    ):
        written = _written_paths(calculate._FORM_BUILDERS[fname], {})
        for enable_key, block_key, path_key in specs:
            assert (enable_key,) in written, (
                f'{fname}: form never writes {enable_key!r}')
            assert (block_key, path_key) in written, (
                f'{fname}: form never writes {block_key!r} -> {path_key!r}')
