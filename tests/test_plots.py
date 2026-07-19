"""Smoke tests for service.plots — server-side document images (design §5). Assert the response
is a non-empty image of the requested format and that limits/unknown fields are rejected. No
pixel comparison. Binary-free: reuses the synthetic MC work_dir from test_results.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from service import plots, results
from tests.test_results import mc_work_dir  # noqa: F401 — pytest fixture reuse


def _is_png(b: bytes) -> bool:
    return b[:8] == b"\x89PNG\r\n\x1a\n"


def _is_svg(b: bytes) -> bool:
    head = b[:512].lstrip()
    return head.startswith(b"<?xml") or head.startswith(b"<svg") or b"<svg" in b[:512]


def test_timeseries_png_and_svg(mc_work_dir):  # noqa: F811
    png = plots.timeseries(str(mc_work_dir), select="id:0,1", column="Altitude [m]",
                           phase="stage1", fmt="png")
    assert _is_png(png) and len(png) > 200
    svg = plots.timeseries(str(mc_work_dir), select="id:0", column="Altitude [m]",
                           phase="stage1", fmt="svg")
    assert _is_svg(svg)


def test_histogram_png(mc_work_dir):  # noqa: F811
    png = plots.histogram(str(mc_work_dir), table="ballistic_result_table",
                          metric="downrange_impact", bins=5, fmt="png")
    assert _is_png(png) and len(png) > 200


def test_dispersion_png_both_axes(mc_work_dir):  # noqa: F811
    for axes in ("ne", "latlon"):
        png = plots.dispersion(str(mc_work_dir), table="ballistic_result_table",
                               axes=axes, fmt="png")
        assert _is_png(png)


def test_plots_reject_unknown_and_oversize(mc_work_dir):  # noqa: F811
    with pytest.raises(results.ResultError):
        plots.timeseries(str(mc_work_dir), select="id:0", column="No Such", fmt="png")
    with pytest.raises(results.ResultError):
        plots.histogram(str(mc_work_dir), table="ballistic_result_table",
                        metric="nope", bins=5, fmt="png")
    with pytest.raises(results.ResultError):
        plots.timeseries(str(mc_work_dir), select="id:0", column="Altitude [m]",
                         fmt="png", width=100, height=100, dpi=100)  # 10000*10000 px
    with pytest.raises(results.ResultError):
        plots.histogram(str(mc_work_dir), table="ballistic_result_table",
                        metric="downrange_impact", bins=plots.MAX_BINS + 1, fmt="png")


def test_unknown_format_rejected(mc_work_dir):  # noqa: F811
    with pytest.raises(results.ResultError):
        plots.timeseries(str(mc_work_dir), select="id:0", column="Altitude [m]", fmt="gif")


def test_plots_does_not_import_pyplot():
    """Lock the OO-API constraint (design Y2): importing service.plots must not pull in pyplot,
    whose process-global current-figure state is unsafe under the FastAPI threadpool."""
    import subprocess
    import sys
    code = ("import service.plots, sys; "
            "sys.exit(1 if 'matplotlib.pyplot' in sys.modules else 0)")
    assert subprocess.call([sys.executable, "-c", code], cwd=str(Path(__file__).parent.parent)) == 0
