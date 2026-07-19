"""Pure result-inspection layer for the remote result API (docs/result_retrieval_design.md §4).

Operates read-only on a finished job's work_dir (== result_dir; service.worker sets result_dir
to the work_dir). No FastAPI here: the HTTP wiring (api.py) maps the exceptions below to status
codes and adds auth. Keeping this layer pure makes it unit-testable without the ForRocket binary
and without a running service, and lets the CLI (`wb extract`) reuse the same resolution.

Layout it reads (Monte Carlo keep-logs, the primary target):
  <work_dir>/result_table.csv | decent_result_table.csv | ballistic_result_table.csv
  <work_dir>/cases/<case>_stage1_flight_log.csv, <case>_ballistic_flight_log.csv
  <work_dir>/cases/<case>_stage1_iip_log.csv (eager, gated)
  <work_dir>/*_summary.txt  (3-sigma summary, MC >= 1000 cases)

Metric source of truth is the result_table family (present in keep-logs, the mode where extract
is meaningful); case_metrics.csv exists only in stats-only mode where per-case logs are deleted
(design §2 / review R3).
"""
from __future__ import annotations

import glob
import math
import os
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

# Extract limits (design §4.2). Provisional; requests over these get 422 at the API layer.
MAX_CASES = 20
MAX_POINTS_CAP = 20_000
MAX_TOTAL_CELLS = 5_000_000  # rows*cols summed over logs; caps a wide phase=all zip request
NO_DECIMATION_MAX_CASES = 3  # max_points=0 (raw) only for a handful of cases (design Y8)


class ResultError(Exception):
    """Bad request against a result: unknown table/metric, malformed select, etc. (-> 422/400)."""


class ResultsGone(ResultError):
    """The work_dir is missing entirely (never produced or retention-swept) (-> 410)."""


# Logical table name -> filename. The logical names are what meta enumerates and what
# tables/{name} accepts, so a raw filename or path from the client never touches the FS.
_LOGICAL_TABLES = {
    "result_table": "result_table.csv",
    "decent_result_table": "decent_result_table.csv",
    "ballistic_result_table": "ballistic_result_table.csv",
    "sensitivity_results": "sensitivity_results.csv",
    "sensitivity_cases": "sensitivity_cases.csv",
}

_PHASES = ("stage1", "ballistic")


def _require_dir(result_dir: str) -> Path:
    if not result_dir:
        raise ResultsGone("no result directory")
    p = Path(result_dir)
    if not p.is_dir():
        raise ResultsGone(f"result directory missing: {result_dir}")
    return p


def available_tables(result_dir: str) -> List[str]:
    rd = _require_dir(result_dir)
    return [name for name, fn in _LOGICAL_TABLES.items() if (rd / fn).is_file()]


def _table_path(result_dir: str, name: str) -> Path:
    """Resolve a logical table name to a path, rejecting anything not whitelisted. The name is
    matched against _LOGICAL_TABLES keys, so path separators / traversal never reach the FS."""
    rd = _require_dir(result_dir)
    fn = _LOGICAL_TABLES.get(name)
    if fn is None:
        raise ResultError(f"unknown table: {name}")
    p = rd / fn
    if not p.is_file():
        raise ResultError(f"table not present: {name}")
    return p


def _rows_json_safe(df: pd.DataFrame) -> list:
    """DataFrame -> list-of-rows with NaN/Inf turned into None. FastAPI's JSON encoder rejects
    non-finite floats (allow_nan=False), and real flight logs contain NaN (pre-launch samples,
    ungated diagnostics); a plain df.where(notnull, None) does not help because assigning None
    into a float column coerces back to NaN. So sanitise on the native-Python values."""
    rows = df.values.tolist()
    return [[None if isinstance(v, float) and not math.isfinite(v) else v for v in row]
            for row in rows]


def read_table(result_dir: str, name: str) -> dict:
    """Return a light table as {columns:[...], rows:[[...]]} (JSON-friendly)."""
    df = pd.read_csv(_table_path(result_dir, name))
    return {"columns": list(df.columns), "rows": _rows_json_safe(df)}


def list_case_logs(result_dir: str) -> List[dict]:
    """Enumerate per-case logs as [{case, phase, kind, file}]. Covers MC/area (cases/ with
    case-prefixed names) and trajectory (result_*/ single log, assigned case 0)."""
    rd = _require_dir(result_dir)
    out: List[dict] = []
    cases_dir = rd / "cases"
    if cases_dir.is_dir():
        for f in sorted(os.listdir(cases_dir)):
            kind = _log_kind(f)
            if kind is None:
                continue
            head = f.split("_", 1)[0]
            if not head.isdigit():
                continue
            out.append({"case": int(head), "phase": _log_phase(f), "kind": kind,
                        "file": str(cases_dir / f)})
    else:
        for f in sorted(glob.glob(str(rd / "result_*" / "*_flight_log.csv"))):
            out.append({"case": 0, "phase": _log_phase(os.path.basename(f)),
                        "kind": "flight", "file": f})
    return out


def _log_kind(fname: str) -> Optional[str]:
    if fname.endswith("_flight_log.csv"):
        return "flight"
    if fname.endswith("_iip_log.csv"):
        return "iip"
    return None


def _log_phase(fname: str) -> str:
    return "ballistic" if "_ballistic_" in fname else "stage1"


def _flight_columns(logs: List[dict]) -> List[str]:
    for log in logs:
        if log["kind"] == "flight":
            try:
                return list(pd.read_csv(log["file"], nrows=0).columns)
            except Exception:
                return []
    return []


def _metrics_columns(result_dir: str) -> List[str]:
    cols: List[str] = []
    for name in available_tables(result_dir):
        if name.endswith("result_table"):
            try:
                for c in pd.read_csv(_table_path(result_dir, name), nrows=0).columns:
                    if c not in cols:
                        cols.append(c)
            except Exception:
                pass
    return cols


def result_meta(result_dir: str, mode: str) -> dict:
    rd = _require_dir(result_dir)
    logs = list_case_logs(result_dir)
    cases = sorted({log["case"] for log in logs})
    phases = sorted({log["phase"] for log in logs if log["kind"] == "flight"})
    iip_available = any(log["kind"] == "iip" for log in logs)
    # Per-phase real case numbers so the UI can list actual cases (skips/missing phases leave
    # gaps), instead of synthesising id:0..N-1 which would point at non-existent cases (review N-8).
    cases_by_phase: dict = {}
    for log in logs:
        if log["kind"] == "flight":
            cases_by_phase.setdefault(log["phase"], set()).add(log["case"])
    cases_by_phase = {ph: sorted(nums) for ph, nums in cases_by_phase.items()}
    return {
        "mode": mode,
        "tables": available_tables(result_dir),
        "case_count": len(cases),
        "phases": phases,
        "cases_by_phase": cases_by_phase,
        "kinds": sorted({log["kind"] for log in logs}) or ["flight"],
        "flight_columns": _flight_columns(logs),
        "metrics_columns": _metrics_columns(result_dir),
        "iip_available": iip_available,
        "kml": sorted(list_kml(result_dir).keys()),
        "summaries": [os.path.basename(p) for p in _summary_paths(rd)],
    }


# ── MC dispersion KML (for browser download and external 3D viewers) ────────────
# Filenames (post_montecarlo/post_kml, prefix in {'', 'decent', 'ballistic'}):
#   envelope: {prefix}_impact_3sigma_envelop.kml
#   ellipse : {prefix}_ellipse_impact_3sigma_envelop.kml  ('' prefix -> ellipse_impact_...)
#   points  : {prefix}_impact_points.kml
# envelope and ellipse share the same suffix, so the discriminator is the 'ellipse' token, not the
# suffix (review N-7). Logical name = "{scenario}_{kind}" (scenario '' -> just kind).
_ENV_SUFFIX = "_impact_3sigma_envelop.kml"
_PTS_SUFFIX = "_impact_points.kml"


def _classify_kml(fname: str):
    if fname.endswith(_PTS_SUFFIX):
        return fname[:-len(_PTS_SUFFIX)], "points"
    if fname.endswith(_ENV_SUFFIX):
        stem = fname[:-len(_ENV_SUFFIX)]
        if "ellipse" in stem:
            scen = stem.replace("_ellipse", "").replace("ellipse", "")
            return scen, "ellipse"
        return stem, "envelope"
    return None, None


def list_kml(result_dir: str) -> dict:
    """Discover MC dispersion KML files as {logical_name: filename}."""
    rd = _require_dir(result_dir)
    out: dict = {}
    for f in sorted(os.listdir(rd)):
        if not f.endswith(".kml"):
            continue
        scen, kind = _classify_kml(f)
        if kind is None:
            continue
        out[f"{scen}_{kind}" if scen else kind] = f
    return out


def kml_path(result_dir: str, name: str) -> Path:
    """Resolve a logical KML name to a path, rejecting anything not discovered (no path from
    the parameter is joined to the FS; only the discovered filename is used)."""
    catalog = list_kml(result_dir)
    fn = catalog.get(name)
    if fn is None:
        raise ResultError(f"unknown kml: {name}")
    return Path(result_dir) / fn


def _summary_paths(rd: Path) -> List[str]:
    found = sorted(glob.glob(str(rd / "*_summary.txt")))
    found += sorted(glob.glob(str(rd / "result_*" / "_summary.txt")))
    return found


def read_summaries(result_dir: str):
    """Parse every *_summary.txt into [(key, value, unit)]. Mirrors the UI's summary parser."""
    rd = _require_dir(result_dir)
    items = []
    for path in _summary_paths(rd):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or "," not in line:
                        continue
                    key, rest = line.split(",", 1)
                    key, rest = key.strip(), rest.strip()
                    if rest.endswith("]") and "[" in rest:
                        b = rest.rfind("[")
                        value, unit = rest[:b].strip(), rest[b:]
                    else:
                        value, unit = rest, ""
                    items.append((key, value, unit))
        except OSError:
            continue
    return items


def _metric_table_for_phase(result_dir: str, phase: str) -> str:
    """Which result_table holds a phase's per-case metrics. stage1 metrics live in
    decent_result_table.csv when a descent/ballistic split exists, else result_table.csv."""
    if phase == "ballistic":
        return "ballistic_result_table"
    rd = _require_dir(result_dir)
    if (rd / _LOGICAL_TABLES["decent_result_table"]).is_file():
        return "decent_result_table"
    return "result_table"


def resolve_select(result_dir: str, select: str) -> List[dict]:
    """Resolve a case-selection expression to [{case, metric?}] (design §4.1).

      nominal                          -> case 0
      id:3,17,204                      -> those case numbers
      top:N:<metric>[:<phase>]         -> N highest, phase default stage1
      bottom:N:<metric>[:<phase>]      -> N lowest
    """
    _require_dir(result_dir)
    select = (select or "").strip()
    if select == "nominal":
        return [{"case": 0}]
    if select.startswith("id:"):
        try:
            nums = [int(x) for x in select[3:].split(",") if x.strip() != ""]
        except ValueError:
            raise ResultError(f"malformed id selector: {select}")
        if not nums:
            raise ResultError("empty id selector")
        return [{"case": n} for n in nums]
    if select.startswith("top:") or select.startswith("bottom:"):
        return _resolve_ranked(result_dir, select)
    if select.startswith("filter:"):
        return _resolve_filter(result_dir, select)
    raise ResultError(f"unknown select expression: {select}")


_FILTER_OPS = ("<=", ">=", "<", ">")


def _resolve_filter(result_dir: str, select: str) -> List[dict]:
    """filter:<metric><op><value>[:<phase>] -> all cases matching the threshold (design §8).

    No pandas query/eval: the metric is checked against the table columns, the value is parsed as
    a float, the operator is whitelisted, and a boolean mask is applied (no string interpolation
    into an eval surface; review N-3/SEC)."""
    body = select[len("filter:"):]
    segs = body.split(":")
    expr = segs[0]
    phase = segs[1] if len(segs) >= 2 and segs[1] else "stage1"
    if phase not in _PHASES:
        raise ResultError(f"unknown phase in selector: {phase}")
    op = next((o for o in _FILTER_OPS if o in expr), None)
    if op is None:
        raise ResultError(f"malformed filter (need one of {_FILTER_OPS}): {select}")
    metric, _, value_s = expr.partition(op)
    metric = metric.strip()
    try:
        value = float(value_s.strip())
    except ValueError:
        raise ResultError(f"filter value not numeric: {select}")
    df = pd.read_csv(_table_path(result_dir, _metric_table_for_phase(result_dir, phase)))
    if "case" not in df.columns:
        raise ResultError("table has no 'case' column")
    if metric not in df.columns:
        raise ResultError(f"unknown metric: {metric}")
    col = pd.to_numeric(df[metric], errors="coerce")
    mask = {"<": col < value, "<=": col <= value,
            ">": col > value, ">=": col >= value}[op]
    hit = df[mask.fillna(False)]
    return [{"case": int(r["case"]), "metric": float(r[metric])} for _, r in hit.iterrows()]


def _resolve_ranked(result_dir: str, select: str) -> List[dict]:
    parts = select.split(":")
    if len(parts) < 3:
        raise ResultError(f"malformed rank selector: {select}")
    direction, n_str, metric = parts[0], parts[1], parts[2]
    phase = parts[3] if len(parts) >= 4 else "stage1"
    if phase not in _PHASES:
        raise ResultError(f"unknown phase in selector: {phase}")
    try:
        n = int(n_str)
    except ValueError:
        raise ResultError(f"malformed count in selector: {select}")
    if n <= 0:
        raise ResultError("selector count must be positive")

    df = pd.read_csv(_table_path(result_dir, _metric_table_for_phase(result_dir, phase)))
    if metric not in df.columns:
        raise ResultError(f"unknown metric: {metric}")
    if "case" not in df.columns:
        raise ResultError("table has no 'case' column")
    ascending = direction == "bottom"
    ranked = df.sort_values(metric, ascending=ascending, kind="mergesort").head(n)
    return [{"case": int(r["case"]), "metric": float(r[metric])}
            for _, r in ranked.iterrows()]


# ── extract (design §4.2) ───────────────────────────────────────────────────

_TIME_COL = "Time [s]"


def extract(result_dir: str, select: str, phase: str = "all", kind: str = "flight",
            columns: Optional[List[str]] = None, t_start: Optional[float] = None,
            t_end: Optional[float] = None, max_points: int = 2000) -> dict:
    """Selectively extract heavy per-case logs (design §4.2).

    Returns {"logs": [{case, phase, kind, columns, rows, n_points, decimated}],
             "missing": [{case, phase, kind, reason}]}. The API layer formats this as
             json/csv/zip; keeping the packaging out of here makes it unit-testable.

    Limits (ResultError -> 422): resolved cases <= MAX_CASES, max_points <= MAX_POINTS_CAP,
    total cells <= MAX_TOTAL_CELLS, and max_points==0 (no decimation) only for
    <= NO_DECIMATION_MAX_CASES cases. Unknown columns and phase/kind are rejected.
    """
    _require_dir(result_dir)
    if phase not in ("stage1", "ballistic", "all"):
        raise ResultError(f"unknown phase: {phase}")
    if kind not in ("flight", "iip"):
        raise ResultError(f"unknown kind: {kind}")
    if max_points < 0:
        raise ResultError("max_points must be >= 0")
    if max_points > MAX_POINTS_CAP:
        raise ResultError(f"max_points exceeds cap {MAX_POINTS_CAP}")

    resolved = resolve_select(result_dir, select)
    case_nums = [r["case"] for r in resolved]
    if len(case_nums) > MAX_CASES:
        raise ResultError(f"too many cases ({len(case_nums)} > {MAX_CASES})")
    if max_points == 0 and len(case_nums) > NO_DECIMATION_MAX_CASES:
        raise ResultError(
            f"max_points=0 (no decimation) allowed only for <= {NO_DECIMATION_MAX_CASES} cases")

    by_case: dict = {}
    for log in list_case_logs(result_dir):
        by_case.setdefault((log["case"], log["phase"], log["kind"]), log["file"])

    wanted_phases = ("stage1", "ballistic") if phase == "all" else (phase,)
    logs: List[dict] = []
    missing: List[dict] = []
    total_cells = 0
    for case in case_nums:
        for ph in wanted_phases:
            path = by_case.get((case, ph, kind))
            if path is None:
                missing.append({"case": case, "phase": ph, "kind": kind, "reason": "not present"})
                continue
            log = _read_log(path, columns, t_start, t_end, max_points)
            log.update(case=case, phase=ph, kind=kind)
            total_cells += log["n_points"] * len(log["columns"])
            if total_cells > MAX_TOTAL_CELLS:
                raise ResultError(f"response too large (> {MAX_TOTAL_CELLS} cells); narrow the request")
            logs.append(log)
    return {"logs": logs, "missing": missing}


def _read_log(path: str, columns, t_start, t_end, max_points) -> dict:
    header = list(pd.read_csv(path, nrows=0).columns)
    time_col = _TIME_COL if _TIME_COL in header else (header[0] if header else None)
    if columns:
        unknown = [c for c in columns if c not in header]
        if unknown:
            raise ResultError(f"unknown columns: {unknown}")
        usecols = list(dict.fromkeys(([time_col] if time_col else []) + list(columns)))
    else:
        usecols = None
    df = pd.read_csv(path, usecols=usecols)
    if usecols:  # preserve requested order (time first)
        df = df[[c for c in usecols if c in df.columns]]
    if time_col and time_col in df.columns and (t_start is not None or t_end is not None):
        if t_start is not None:
            df = df[df[time_col] >= t_start]
        if t_end is not None:
            df = df[df[time_col] <= t_end]
    decimated = False
    if max_points and len(df) > max_points:
        df = _decimate(df, max_points)
        decimated = True
    return {"columns": list(df.columns), "n_points": int(len(df)), "decimated": decimated,
            "rows": _rows_json_safe(df)}


def _decimate(df: pd.DataFrame, max_points: int) -> pd.DataFrame:
    """Equidistant index decimation that always keeps the first and last points (design §4.2)."""
    idx = np.unique(np.linspace(0, len(df) - 1, max_points).round().astype(int))
    return df.iloc[idx]


# ── impact dispersion ellipses (shared by the UI's echarts render and the plots API) ────

# nσ ellipse convention: semi-axes = nσ·√λ of the impact covariance. The 2-D containment of an
# nσ ellipse is NOT the 1-D 68/95/99.7% (it is ~39/86/99% for 1/2/3σ); callers must label the
# convention rather than imply 1-D probabilities (design §5 / review Y7).
def compute_impact_ellipses(lat_list: list, lon_list: list):
    """Compute 1σ/2σ/3σ impact ellipses in both NE and lat/lon coordinates.

    Returns east, north arrays [m], mean_lat, mean_lon,
    ne_ellipses [(nsig, color, [[e,n],...])],
    ll_ellipses [(nsig, color, [[lat,lon],...])].
    """
    lats = np.array(lat_list, dtype=float)
    lons = np.array(lon_list, dtype=float)
    mean_lat = float(lats.mean())
    mean_lon = float(lons.mean())
    R = 6_371_000.0
    cos_lat = float(np.cos(np.radians(mean_lat)))
    north = (lats - mean_lat) * (np.pi / 180) * R
    east  = (lons - mean_lon) * (np.pi / 180) * R * cos_lat

    ne_ellipses: list = []
    ll_ellipses: list = []
    if len(lats) >= 3:
        try:
            cov = np.cov(np.stack([east, north]))
            eigvals, eigvecs = np.linalg.eigh(cov)
            order = np.argsort(eigvals)[::-1]
            eigvals, eigvecs = eigvals[order], eigvecs[:, order]
            theta = np.linspace(0, 2 * np.pi, 120)
            cos_t, sin_t = np.cos(theta), np.sin(theta)
            for nsig, clr in [(1, '#4caf50'), (2, '#ff9800'), (3, '#f44336')]:
                a = nsig * float(np.sqrt(max(float(eigvals[0]), 0.0)))
                b = nsig * float(np.sqrt(max(float(eigvals[1]), 0.0)))
                ne_pts: list = []
                ll_pts: list = []
                for ct, st in zip(cos_t, sin_t):
                    v = eigvecs @ np.array([a * ct, b * st])
                    e, nv = float(v[0]), float(v[1])
                    ne_pts.append([e, nv])
                    ll_pts.append([
                        mean_lat + nv / R * (180 / np.pi),
                        mean_lon + e / (R * cos_lat) * (180 / np.pi),
                    ])
                ne_pts.append(ne_pts[0])
                ll_pts.append(ll_pts[0])
                ne_ellipses.append((nsig, clr, ne_pts))
                ll_ellipses.append((nsig, clr, ll_pts))
        except Exception:
            pass
    return east, north, mean_lat, mean_lon, ne_ellipses, ll_ellipses
