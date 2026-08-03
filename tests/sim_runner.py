"""
Core simulation runner for tests.
Runs ForRocket binary in an isolated temp directory and returns results as DataFrame.
"""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from copy import deepcopy
from typing import Callable, Dict, Optional, Union

import pandas as pd
from scipy.interpolate import interp1d


_BINARY_CANDIDATES = [
    Path.home() / "ForRocket/build/ForRocket",
    Path(__file__).parent.parent / "ForRocket",
    Path(__file__).parent.parent / "ForRocket.exe",
]


def find_binary() -> Optional[Path]:
    for p in _BINARY_CANDIDATES:
        if p.is_file():
            return p
    return None


_VERSION_RE = re.compile(r"version\s*:\s*([0-9]+(?:\.[0-9]+)*)")

UNKNOWN_VERSION = "unknown"


def binary_version(binary_path: Union[str, Path]) -> str:
    """
    Return the solver version reported by `ForRocket --version`, e.g. "4.4.2".

    Returns UNKNOWN_VERSION if the binary does not understand `--version`
    (solvers older than v4.3) or prints something unparsable.
    """
    try:
        proc = subprocess.run(
            [str(binary_path), "--version"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN_VERSION

    m = _VERSION_RE.search(proc.stdout or "")
    return m.group(1) if m else UNKNOWN_VERSION


def load_configs(config_dir: Path, solver_config_name: str) -> Dict:
    """
    Load the full config tree from config_dir.

    Returns dict with keys:
      "solver", "stage1", "rocket1", "engine1", "soe1"  (per stage N: stageN, rocketN, ...)
    """
    solver = json.loads((config_dir / solver_config_name).read_text())
    result = {"solver": solver}

    n_stages = solver.get("Number of Stage", 1)
    for i in range(1, n_stages + 1):
        stage_file = solver.get(f"Stage{i} Config File List")
        if not stage_file:
            continue
        stage_path = config_dir / stage_file
        if not stage_path.exists():
            continue
        stage = json.loads(stage_path.read_text())
        result[f"stage{i}"] = stage

        for key, cfg_key in [
            ("rocket", "Rocket Configuration File Path"),
            ("engine", "Engine Configuration File Path"),
            ("soe",    "Sequence of Event File Path"),
        ]:
            f = stage.get(cfg_key)
            if f and (config_dir / f).exists():
                result[f"{key}{i}"] = json.loads((config_dir / f).read_text())

    return result


def _collect_dep_files(config_dir: Path, solver: dict, n_stages: int) -> Dict[str, Path]:
    """Collect all files referenced in the config chain. Returns {filename: abs_path}."""
    files: Dict[str, Path] = {}

    def add(name: Optional[str]):
        if name and name not in files:
            p = config_dir / name
            if p.exists():
                files[name] = p

    wind = solver.get("Wind Condition", {})
    if wind.get("Enable Wind"):
        add(wind.get("Wind File Path"))

    for i in range(1, n_stages + 1):
        stage_file = solver.get(f"Stage{i} Config File List")
        if not stage_file:
            continue
        stage_path = config_dir / stage_file
        if not stage_path.exists():
            continue
        stage = json.loads(stage_path.read_text())

        rocket_file = stage.get("Rocket Configuration File Path")
        engine_file = stage.get("Engine Configuration File Path")
        soe_file    = stage.get("Sequence of Event File Path")
        add(rocket_file)
        add(engine_file)
        add(soe_file)

        if rocket_file and (config_dir / rocket_file).exists():
            rocket = json.loads((config_dir / rocket_file).read_text())
            for enable, block, key in [
                ("Enable Program Attitude", "Program Attitude", "File Path"),
                ("Enable X-C.G. File", "X-C.G. File", "X-C.G. File Path"),
                ("Enable M.I. File",   "M.I. File",   "M.I. File Path"),
                ("Enable X-C.P. File", "X-C.P. File", "X-C.P. File Path"),
                ("Enable CA File",     "CA File",     "CA File Path"),
                ("Enable CA File",     "CA File",     "BurnOut CA File Path"),
                ("Enable CNa File",    "CNa File",    "CNa File Path"),
                ("Enable Cld File",    "Cld File",    "Cld File Path"),
                ("Enable Clp File",    "Clp File",    "Clp File Path"),
                ("Enable Cmq File",    "Cmq File",    "Cmq File Path"),
                ("Enable Cnr File",    "Cnr File",    "Cnr File Path"),
            ]:
                if rocket.get(enable):
                    add(rocket.get(block, {}).get(key))

        if engine_file and (config_dir / engine_file).exists():
            engine = json.loads((config_dir / engine_file).read_text())
            if engine.get("Enable Thrust File"):
                add(engine.get("Thrust File", {}).get("Thrust at vacuum File Path"))

    return files


def run_sim(
    config_dir: Union[str, Path],
    solver_config_name: str,
    binary_path: Union[str, Path, None] = None,
    modify_configs: Optional[Callable] = None,
) -> pd.DataFrame:
    """
    Run a ForRocket simulation and return the stage1 flight log as DataFrame.

    Parameters
    ----------
    config_dir : directory containing all input files
    solver_config_name : solver config JSON filename (within config_dir)
    binary_path : ForRocket binary; auto-detected if None
    modify_configs : optional callable(configs: dict) -> None
        Receives the loaded config tree and may modify dicts in place.
        Keys: "solver", "stage1", "rocket1", "engine1", "soe1" (per stage N)

    Raises
    ------
    FileNotFoundError : binary not found or no output produced
    RuntimeError : ForRocket returned non-zero exit code
    """
    binary = Path(binary_path).resolve() if binary_path else find_binary()
    if binary is None or not binary.is_file():
        raise FileNotFoundError(f"ForRocket binary not found. Tried: {_BINARY_CANDIDATES}")

    config_dir = Path(config_dir).resolve()
    configs = load_configs(config_dir, solver_config_name)

    if modify_configs is not None:
        modify_configs(configs)

    solver = configs["solver"]
    n_stages = solver.get("Number of Stage", 1)

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)

        # Copy all referenced CSV / file dependencies
        for fname, src in _collect_dep_files(config_dir, solver, n_stages).items():
            shutil.copy2(src, tmpdir / fname)

        # Handle "Moving equivalent wind mode" (Workbench extension, not a ForRocket field).
        # Sets initial velocity to match wind at launch altitude, then removes the key.
        lc = solver.get("Launch Condition", {})
        if lc.pop("Moving equivalent wind mode", False):
            wind_file = tmpdir / solver["Wind Condition"]["Wind File Path"]
            df_w = pd.read_csv(wind_file, header=0)
            alt = lc["Height for WGS84 [m]"]
            fu = interp1d(df_w.iloc[:, 0], df_w.iloc[:, 1],
                          bounds_error=False, fill_value=(0.0, float(df_w.iloc[-1, 1])))
            fv = interp1d(df_w.iloc[:, 0], df_w.iloc[:, 2],
                          bounds_error=False, fill_value=(0.0, float(df_w.iloc[-1, 2])))
            lc["East Velocity [m/s]"]  = float(fu(alt))
            lc["North Velocity [m/s]"] = float(fv(alt))

        # Write (possibly modified) JSON files to temp dir
        with open(tmpdir / solver_config_name, "w") as f:
            json.dump(solver, f)

        for i in range(1, n_stages + 1):
            if f"stage{i}" in configs:
                stage_file = solver.get(f"Stage{i} Config File List")
                with open(tmpdir / stage_file, "w") as f:
                    json.dump(configs[f"stage{i}"], f)
            for sub in ("rocket", "engine", "soe"):
                if f"{sub}{i}" in configs:
                    sub_file = configs[f"stage{i}"][{
                        "rocket": "Rocket Configuration File Path",
                        "engine": "Engine Configuration File Path",
                        "soe":    "Sequence of Event File Path",
                    }[sub]]
                    with open(tmpdir / sub_file, "w") as f:
                        json.dump(configs[f"{sub}{i}"], f)

        # Run ForRocket
        proc = subprocess.run(
            [str(binary), "-q", solver_config_name],
            cwd=tmpdir, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"ForRocket exited {proc.returncode}:\n{proc.stderr or proc.stdout}"
            )

        # Find stage1 flight log
        model_id = solver["Model ID"]
        log_path = tmpdir / f"{model_id}_stage1_flight_log.csv"
        if not log_path.exists():
            logs = list(tmpdir.glob("*_stage1_flight_log.csv"))
            if not logs:
                raise FileNotFoundError(
                    f"No stage1 flight log found in {tmpdir}.\nstdout: {proc.stdout}"
                )
            log_path = logs[0]

        return pd.read_csv(log_path)


def extract_metrics(df: pd.DataFrame) -> dict:
    """
    Extract key scalar metrics from a flight log DataFrame.

    Returns a flat dict suitable for golden-file comparison and assertions.
    """
    idx_apogee = int(df["Altitude [m]"].idxmax())
    idx_maxq   = int(df["DynamicPressure [kPa]"].iloc[:idx_apogee + 1].idxmax())

    return {
        "apogee_altitude_m":        float(df["Altitude [m]"].max()),
        "apogee_time_s":            float(df["Time [s]"].iloc[idx_apogee]),
        "apogee_downrange_m":       float(df["Downrange [m]"].iloc[idx_apogee]),
        "max_dynamic_pressure_kPa": float(df["DynamicPressure [kPa]"].max()),
        "max_mach":                 float(df["MachNumber [-]"].max()),
        "max_acc_body_G":           float(df["Gccx-body [G]"].max()),
        "landing_downrange_m":      float(df["Downrange [m]"].iloc[-1]),
        "landing_lat_deg":          float(df["Latitude [deg]"].iloc[-1]),
        "landing_lon_deg":          float(df["Longitude [deg]"].iloc[-1]),
        "flight_duration_s":        float(df["Time [s]"].iloc[-1]),
    }
