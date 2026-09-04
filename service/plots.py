"""Server-side document images for the remote result API (docs/result_retrieval_design.md §5).

Three kinds: timeseries, histogram, dispersion. Rendered with matplotlib's object-oriented API
(Figure + FigureCanvasAgg) and never pyplot: pyplot keeps a process-global "current figure" that
is not thread-safe, and these run in the FastAPI threadpool where concurrent requests would
corrupt each other's figures (design §4.3 / review Y2). Figures are drawn full-resolution (no
decimation) so report plots keep sharp peaks (design §5 / review Y6). Text is English, no title,
per the document guidelines.
"""
from __future__ import annotations

import io
from typing import List, Optional

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from post_tool import post_ellipse
from service import results
from service.results import ResultError

# Size guards (design §5 / review): an unbounded width*dpi × height*dpi allocation can OOM the
# service (which also supervises the worker), so cap the pixel budget and bin count.
MAX_PIXELS = 6_000 * 6_000
MAX_BINS = 200
_FORMATS = ("png", "svg")

_TIME_COL = "Time [s]"


def _ellipse_label(k: float) -> str:
    """Legend entry for one dispersion ellipse: the k value and what it actually contains."""
    return f"k={k:g} ({post_ellipse.containment_2d(k):.2f}%)"


def _new_fig(width: float, height: float, dpi: int) -> Figure:
    if width <= 0 or height <= 0 or dpi <= 0:
        raise ResultError("width/height/dpi must be positive")
    if (width * dpi) * (height * dpi) > MAX_PIXELS:
        raise ResultError(f"image too large (> {MAX_PIXELS} px); reduce size or dpi")
    fig = Figure(figsize=(width, height), dpi=dpi)
    FigureCanvasAgg(fig)  # attach an Agg canvas; no pyplot / global state
    return fig


def _render(fig: Figure, fmt: str) -> bytes:
    if fmt not in _FORMATS:
        raise ResultError(f"unknown format: {fmt}")
    buf = io.BytesIO()
    fig.savefig(buf, format=fmt, bbox_inches="tight")
    return buf.getvalue()


def _flight_log_for(result_dir: str, case: int, phase: str) -> Optional[str]:
    for log in results.list_case_logs(result_dir):
        if log["kind"] == "flight" and log["case"] == case and log["phase"] == phase:
            return log["file"]
    return None


def timeseries(result_dir: str, select: str, column: str, phase: str = "stage1",
               t_start: Optional[float] = None, t_end: Optional[float] = None,
               fmt: str = "png", width: float = 8.0, height: float = 4.5,
               dpi: int = 150) -> bytes:
    """Time history of one column for the selected cases, overlaid, full-resolution."""
    if fmt not in _FORMATS:
        raise ResultError(f"unknown format: {fmt}")
    if phase not in ("stage1", "ballistic"):
        raise ResultError(f"unknown phase: {phase}")
    resolved = results.resolve_select(result_dir, select)
    if len(resolved) > results.MAX_CASES:
        raise ResultError(f"too many cases ({len(resolved)} > {results.MAX_CASES})")

    fig = _new_fig(width, height, dpi)
    ax = fig.subplots()
    plotted = 0
    for r in resolved:
        case = r["case"]
        path = _flight_log_for(result_dir, case, phase)
        if path is None:
            continue
        header = list(pd.read_csv(path, nrows=0).columns)
        if column not in header:
            raise ResultError(f"unknown column: {column}")
        tcol = _TIME_COL if _TIME_COL in header else header[0]
        df = pd.read_csv(path, usecols=[tcol, column])
        if t_start is not None:
            df = df[df[tcol] >= t_start]
        if t_end is not None:
            df = df[df[tcol] <= t_end]
        ax.plot(df[tcol], df[column], label=f"case {case}", linewidth=1.0)
        plotted += 1
    if plotted == 0:
        raise ResultError("no matching case logs for selection/phase")
    ax.set_xlabel(_TIME_COL)
    ax.set_ylabel(column)
    ax.grid(True, alpha=0.3)
    if plotted > 1:
        ax.legend(fontsize="small")
    return _render(fig, fmt)


def histogram(result_dir: str, table: str, metric: str, bins: int = 30,
              fmt: str = "png", width: float = 6.0, height: float = 4.0,
              dpi: int = 150) -> bytes:
    """Distribution of a metric column from a light result table."""
    if fmt not in _FORMATS:
        raise ResultError(f"unknown format: {fmt}")
    if bins <= 0 or bins > MAX_BINS:
        raise ResultError(f"bins must be in 1..{MAX_BINS}")
    tbl = results.read_table(result_dir, table)  # validates table name / existence
    if metric not in tbl["columns"]:
        raise ResultError(f"unknown metric: {metric}")
    col = tbl["columns"].index(metric)
    values = np.array([row[col] for row in tbl["rows"] if row[col] is not None], dtype=float)
    if values.size == 0:
        raise ResultError(f"no data for metric: {metric}")
    fig = _new_fig(width, height, dpi)
    ax = fig.subplots()
    ax.hist(values, bins=bins, color="#1f77b4", edgecolor="white")
    ax.set_xlabel(metric)
    ax.set_ylabel("count")
    ax.grid(True, alpha=0.3)
    return _render(fig, fmt)


def dispersion(result_dir: str, table: str, axes: str = "ne", fmt: str = "png",
               width: float = 6.0, height: float = 6.0, dpi: int = 150) -> bytes:
    """Impact scatter + 1σ/2σ/3σ dispersion ellipses (no map background; design §5)."""
    if fmt not in _FORMATS:
        raise ResultError(f"unknown format: {fmt}")
    if axes not in ("ne", "latlon"):
        raise ResultError(f"unknown axes: {axes}")
    tbl = results.read_table(result_dir, table)
    cols = tbl["columns"]
    for needed in ("lat_impact", "lon_impact"):
        if needed not in cols:
            raise ResultError(f"table {table} lacks {needed}")
    lat_i, lon_i = cols.index("lat_impact"), cols.index("lon_impact")
    lat = [row[lat_i] for row in tbl["rows"] if row[lat_i] is not None]
    lon = [row[lon_i] for row in tbl["rows"] if row[lon_i] is not None]
    if len(lat) == 0:
        raise ResultError("no impact points")

    east, north, mean_lat, mean_lon, ne_ell, ll_ell, ell_err = results.compute_impact_ellipses(lat, lon)
    fig = _new_fig(width, height, dpi)
    ax = fig.subplots()
    if axes == "ne":
        ax.scatter(east, north, s=8, color="#333333", alpha=0.6)
        for k, clr, pts in ne_ell:
            arr = np.array(pts)
            ax.plot(arr[:, 0], arr[:, 1], color=clr, label=_ellipse_label(k))
        ax.set_xlabel("East [m]")
        ax.set_ylabel("North [m]")
        ax.set_aspect("equal", adjustable="datalim")
    else:
        ax.scatter(lon, lat, s=8, color="#333333", alpha=0.6)
        for k, clr, pts in ll_ell:
            arr = np.array(pts)
            ax.plot(arr[:, 1], arr[:, 0], color=clr, label=_ellipse_label(k))
        ax.set_xlabel("Longitude [deg]")
        ax.set_ylabel("Latitude [deg]")
    # The legend gives each ellipse's 2-D containment; the note gives the convention behind it,
    # so the figure never leaves "3σ" to be read as the 1-D 99.73% (design §5 / review Y7).
    note = "ellipse semi-axes = k·√λ; % is 2-D containment, not the 1-D 68/95/99.7%"
    if ell_err:
        note = f"ellipse not drawn: {ell_err}"
    ax.annotate(note, xy=(0.01, 0.01), xycoords="axes fraction",
                fontsize="x-small", color="#666666")
    ax.grid(True, alpha=0.3)
    if ne_ell or ll_ell:
        ax.legend(fontsize="small")
    return _render(fig, fmt)
