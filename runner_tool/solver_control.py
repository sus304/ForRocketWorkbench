import os
import shutil
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_LINUX_BUILD = Path.home() / "ForRocket" / "build"


def _find_binary() -> Path:
    """Find the ForRocket binary. Prefers native Linux binary over Windows exe."""
    for name in ("ForRocket", "ForRocket.exe"):
        for base in (Path.cwd(), _REPO_ROOT, _LINUX_BUILD):
            p = base / name
            if p.is_file():
                return p
    raise FileNotFoundError(
        f"ForRocket binary not found. Searched CWD ({Path.cwd()}), {_REPO_ROOT}, {_LINUX_BUILD}"
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
        cwd=cwd, stdout=subprocess.PIPE,
    )
    _current_process.wait()
    _current_process = None


def cancel_current_solver():
    global _current_process
    proc = _current_process
    if proc is not None:
        proc.terminate()


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
