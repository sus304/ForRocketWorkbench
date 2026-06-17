from pathlib import Path
import pytest

_REPO_ROOT = Path(__file__).parent.parent

_BINARY_CANDIDATES = [
    Path.home() / "ForRocket/build/ForRocket",
    _REPO_ROOT / "ForRocket",
    _REPO_ROOT / "ForRocket.exe",
]


def pytest_addoption(parser):
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Regenerate golden metric files instead of comparing against them",
    )
    parser.addoption(
        "--binary",
        type=str,
        default=None,
        help="Path to ForRocket binary (overrides auto-detection)",
    )


@pytest.fixture(scope="session")
def update_golden(request) -> bool:
    return request.config.getoption("--update-golden")


@pytest.fixture(scope="session")
def binary_path(request) -> Path:
    override = request.config.getoption("--binary")
    if override:
        p = Path(override)
        if p.is_file():
            return p
        pytest.fail(f"--binary path not found: {p}")

    for p in _BINARY_CANDIDATES:
        if p.is_file():
            return p

    pytest.skip("ForRocket binary not found. Use --binary=<path> to specify.")


@pytest.fixture(scope="session")
def projects_dir() -> Path:
    return _REPO_ROOT / "projects"


@pytest.fixture(scope="session")
def config_dir(projects_dir) -> Path:
    """Default config dir. Uses the tracked sample project so the suite is runnable from a
    clean checkout (projects/example is the only project under version control; real vehicle
    projects are gitignored, local-only data and never committed to this public repo)."""
    return projects_dir / "example"


@pytest.fixture(scope="session")
def golden_dir() -> Path:
    d = Path(__file__).parent / "golden"
    d.mkdir(exist_ok=True)
    return d
