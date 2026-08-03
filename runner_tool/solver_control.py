import os
import shutil
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_LINUX_BUILD = Path.home() / "ForRocket" / "build"


def _find_binary(cwd=None) -> Path:
    """Find the ForRocket binary. Prefers native Linux binary over Windows exe.

    `cwd` overrides the working directory used as the first search location; the compute service
    passes the run dir it is about to launch the runner in, so it identifies the same binary the
    run will use without having to chdir the service process."""
    cwd = Path(cwd) if cwd is not None else Path.cwd()
    for name in ("ForRocket", "ForRocket.exe"):
        for base in (cwd, _REPO_ROOT, _LINUX_BUILD):
            p = base / name
            if p.is_file():
                return p
    raise FileNotFoundError(
        f"ForRocket binary not found. Searched CWD ({cwd}), {_REPO_ROOT}, {_LINUX_BUILD}"
    )


def copy_solver_binary(dst_dir):
    # CMakeFile内のオプションで-static -lstdc++ -lgcc -lwinpthreadをつけること(MSYS2の場合)
    src = _find_binary()
    shutil.copy2(str(src), str(Path(dst_dir) / src.name))
    return src.name


def clean_solver_binary(dst_dir):
    src = _find_binary()
    target = Path(dst_dir) / src.name
    if target.exists():
        target.unlink()


_current_process = None


def run_solver(solver_config_json_file_path, cwd=None):
    global _current_process
    binary = _find_binary()
    _current_process = subprocess.Popen(
        [str(binary), solver_config_json_file_path],
        cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    _current_process.communicate()
    _current_process = None


def cancel_current_solver():
    global _current_process
    proc = _current_process
    if proc is not None:
        proc.terminate()


def solver_version_string(cwd=None) -> str:
    """The solver binary's `-v` output as one line, or '' if it cannot be determined.

    Recorded per job by the compute service so a result can be attributed to a solver build
    (service.worker). Never raises: a missing or unrunnable binary just leaves the version blank,
    and the run itself will report the real failure.
    """
    try:
        binary = _find_binary(cwd)
        out = subprocess.run([str(binary), "-v"], cwd=str(cwd) if cwd else None,
                             capture_output=True, text=True, timeout=10.0)
    except (OSError, FileNotFoundError, subprocess.SubprocessError):
        return ""
    text = (out.stdout or "") + (out.stderr or "")
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def print_solver_version_string():
    binary_name = _find_binary().name
    if os.name == 'nt':
        cmd = '.\\'+ binary_name + ' -v'
    else:
        cmd = './' + binary_name + ' -v'
    p = subprocess.Popen(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    while True:
        line = p.stdout.readline()
        if line:
            print(line)
        if not line and p.poll() is not None:
            break
