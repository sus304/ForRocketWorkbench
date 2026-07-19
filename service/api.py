"""HTTP API for the compute service (design §5, §7).

FastAPI app over a JobStore + Worker. Every endpoint except /health requires a bearer token
(WB_API_TOKEN); network exposure is further constrained by binding only to loopback or the
tailscale interface (see service.serve). Job submission uploads the input closure, which is
extracted with the hardened safe_extract before the job becomes runnable.
"""
from __future__ import annotations

import hmac
import io
import json
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from runner_tool.run_manifest import RunManifest
from service import plots, results
from service.results import ResultError, ResultsGone
from service.store import JobStore, PREPARING, QUEUED, RUNNING, TERMINAL_STATUSES
from service.uploads import pack_result, safe_extract, UploadError
from service.worker import Worker

_MODES = {"trajectory", "area", "montecarlo", "sensitivity"}
_ACTIVE = {PREPARING, QUEUED, RUNNING}

# Provisional cap for the full-log tarball (design §4.4 / review Y1): pack_result builds the tar
# in memory, so a 300GB work_dir would OOM the service. Estimate size first and refuse over this.
FULL_DOWNLOAD_MAX_BYTES = 5 * 1024 ** 3


def _iso(dt):
    return dt.isoformat() if dt else None


def create_app(store: JobStore, worker: Worker, token: str) -> FastAPI:
    app = FastAPI(title="ForRocket Workbench Job Service")

    def require_token(authorization: Optional[str] = Header(None)):
        # Fail closed on an empty token: without this, token="" makes "Bearer " authenticate every
        # request (design/review Y15). serve.run() also refuses to start with an empty token.
        if not token:
            raise HTTPException(status_code=401, detail="service token not configured")
        expected = "Bearer " + token
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="invalid or missing token")

    auth = [Depends(require_token)]

    def progress_of(job) -> Optional[dict]:
        # Live per-case progress for a running Monte Carlo job, from the completion manifest
        # the runner maintains (design §4.2). None for other modes/states.
        if job.mode != "montecarlo" or job.status != RUNNING or not job.work_dir:
            return None
        wd = Path(job.work_dir)
        if not wd.is_dir():
            return None
        try:
            done = (wd / RunManifest.FILENAME).read_bytes().count(b"\n")
        except OSError:
            done = 0
        total = 0
        try:
            cfg = json.loads((worker.run_dir_for(job.id) / "config_montecarlo.json").read_text())
            total = int(cfg.get("MonteCarlo Case Count") or 0)
        except (OSError, ValueError, TypeError):
            total = 0
        return {"done": done, "total": total}

    def _result_api_available(job) -> bool:
        # Capability by artifact existence, not status: a completed job whose work_dir was swept
        # by retention can no longer serve the result API (design §4 / review Y4).
        return bool(job.result_dir) and Path(job.result_dir).is_dir()

    def job_dict(job) -> dict:
        return {
            "id": job.id,
            "mode": job.mode,
            "model_name": job.model_name,
            "status": job.status,
            "use_max_thread": job.use_max_thread,
            "enqueued_at": _iso(job.enqueued_at),
            "started_at": _iso(job.started_at),
            "finished_at": _iso(job.finished_at),
            "work_dir": job.work_dir,
            "result_dir": job.result_dir,
            "error_message": job.error_message,
            "capability": {"can_cancel": job.status in _ACTIVE,
                           "result_api": _result_api_available(job)},
            "progress": progress_of(job),
        }

    def resolve_result_dir(job_id: int):
        """Return (result_dir, mode) validated to sit under data_root, or raise the right HTTP
        error: 404 unknown job, 409 result not ready, 410 work_dir swept, 400 escapes root."""
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        if not job.result_dir:
            raise HTTPException(409, "result not ready")
        rd = Path(job.result_dir).resolve()
        data_root = worker.data_root.resolve()
        if data_root != rd and data_root not in rd.parents:
            raise HTTPException(400, "result path outside data root")
        if not rd.is_dir():
            raise HTTPException(410, "result no longer available")
        return str(rd), job.mode

    def result_error(exc: Exception):
        # Map the pure layer's domain errors to HTTP. ResultsGone is a subclass of ResultError,
        # so check it first.
        if isinstance(exc, ResultsGone):
            return HTTPException(410, str(exc))
        return HTTPException(422, str(exc))

    def running_stall_seconds() -> Optional[float]:
        # Seconds since a running MC job's manifest last advanced. A large value on an
        # unattended server means the solver has stalled/hung (design §4.2 observability).
        for job in store.list(status=RUNNING):
            if job.mode == "montecarlo" and job.work_dir:
                mf = Path(job.work_dir) / RunManifest.FILENAME
                try:
                    return max(0.0, time.time() - mf.stat().st_mtime)
                except OSError:
                    return None
        return None

    def disk_free() -> Optional[list]:
        root = worker.data_root
        probe = root if root.exists() else root.parent
        try:
            usage = shutil.disk_usage(str(probe))
            return [usage.free, usage.total]
        except OSError:
            return None

    @app.get("/health")
    def health():
        du = disk_free()
        return {
            "status": "ok",
            "worker_alive": worker.is_alive(),
            "running_job": worker.current_job_id(),
            "running_stall_seconds": running_stall_seconds(),
            "disk_free_bytes": du[0] if du else None,
            "disk_total_bytes": du[1] if du else None,
        }

    @app.get("/jobs", dependencies=auth)
    def list_jobs(status: Optional[str] = Query(None)):
        return {"jobs": [job_dict(j) for j in store.list(status=status)]}

    @app.get("/jobs/{job_id}", dependencies=auth)
    def get_job(job_id: int):
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        return job_dict(job)

    @app.post("/jobs", dependencies=auth)
    async def submit_job(
        mode: str = Form(...),
        use_max_thread: bool = Form(False),
        model_name: str = Form(""),
        payload: UploadFile = File(...),
    ):
        if mode not in _MODES:
            raise HTTPException(400, f"unknown mode: {mode}")
        data = await payload.read()
        # create the job in `preparing` so the worker cannot claim it before its inputs are
        # staged (design §5); only mark_queued() makes it runnable.
        job_id = store.create_preparing(mode=mode, model_name=model_name,
                                        use_max_thread=use_max_thread)
        run_dir = worker.run_dir_for(job_id)
        try:
            safe_extract(data, run_dir)
        except UploadError as e:
            store.mark_failed(job_id, f"upload rejected: {e}")
            raise HTTPException(400, f"upload rejected: {e}")
        store.mark_queued(job_id)
        return {"id": job_id, "status": QUEUED}

    @app.post("/jobs/{job_id}/cancel", dependencies=auth)
    def cancel_job(job_id: int):
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        cancelled = worker.cancel(job_id)
        return {"id": job_id, "cancelled": cancelled, "status": store.get(job_id).status}

    @app.get("/jobs/{job_id}/result.tar.gz", dependencies=auth)
    def download_result(job_id: int, full: bool = Query(False)):
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        if not job.result_dir:
            raise HTTPException(409, "result not ready")
        rd = Path(job.result_dir).resolve()
        data_root = worker.data_root.resolve()
        if data_root != rd and data_root not in rd.parents:
            raise HTTPException(400, "result path outside data root")
        if full:
            total = sum(f.stat().st_size for f in rd.rglob("*") if f.is_file())
            if total > FULL_DOWNLOAD_MAX_BYTES:
                raise HTTPException(
                    413, f"full result is {total} bytes (> {FULL_DOWNLOAD_MAX_BYTES}); "
                         "use selective extract or fetch over SSH")
        try:
            blob = pack_result(rd, full=full)
        except UploadError as e:
            raise HTTPException(409, str(e))
        return StreamingResponse(
            io.BytesIO(blob),
            media_type="application/gzip",
            headers={"Content-Disposition": f'attachment; filename="job{job_id}_result.tar.gz"'},
        )

    # ── remote result API (docs/result_retrieval_design.md §4-5) ──────────────
    _IMAGE_MEDIA = {"png": "image/png", "svg": "image/svg+xml"}

    def _attachment(filename: str) -> dict:
        # Always download, no MIME sniffing (design §6 / review B5).
        return {"Content-Disposition": f'attachment; filename="{filename}"',
                "X-Content-Type-Options": "nosniff"}

    @app.get("/jobs/{job_id}/result/meta", dependencies=auth)
    def result_meta(job_id: int):
        rd, mode = resolve_result_dir(job_id)
        try:
            return results.result_meta(rd, mode)
        except ResultError as e:
            raise result_error(e)

    @app.get("/jobs/{job_id}/result/summary", dependencies=auth)
    def result_summary(job_id: int):
        rd, _ = resolve_result_dir(job_id)
        try:
            return {"items": [{"key": k, "value": v, "unit": u}
                              for k, v, u in results.read_summaries(rd)]}
        except ResultError as e:
            raise result_error(e)

    @app.get("/jobs/{job_id}/result/tables/{name}", dependencies=auth)
    def result_table(job_id: int, name: str):
        rd, _ = resolve_result_dir(job_id)
        try:
            return results.read_table(rd, name)
        except ResultError as e:
            raise result_error(e)

    @app.get("/jobs/{job_id}/result/cases", dependencies=auth)
    def result_cases(job_id: int, select: str = Query(...)):
        rd, _ = resolve_result_dir(job_id)
        try:
            return {"cases": results.resolve_select(rd, select)}
        except ResultError as e:
            raise result_error(e)

    @app.get("/jobs/{job_id}/result/extract", dependencies=auth)
    def result_extract(job_id: int, select: str = Query(...), phase: str = Query("all"),
                       kind: str = Query("flight"), columns: Optional[str] = Query(None),
                       t_start: Optional[float] = Query(None), t_end: Optional[float] = Query(None),
                       max_points: int = Query(2000), format: str = Query("json")):
        rd, _ = resolve_result_dir(job_id)
        cols = [c for c in columns.split(",") if c] if columns else None
        try:
            ex = results.extract(rd, select=select, phase=phase, kind=kind, columns=cols,
                                 t_start=t_start, t_end=t_end, max_points=max_points)
        except ResultError as e:
            raise result_error(e)
        if format == "json":
            return ex
        if format == "csv":
            if len(ex["logs"]) != 1:
                raise HTTPException(422, "format=csv needs a selection resolving to one log")
            csv = _log_to_csv(ex["logs"][0])
            return StreamingResponse(io.BytesIO(csv.encode()), media_type="text/csv",
                                     headers=_attachment(f"job{job_id}_extract.csv"))
        if format == "zip":
            return _zip_logs_response(job_id, ex["logs"])
        raise HTTPException(422, f"unknown format: {format}")

    @app.get("/jobs/{job_id}/result/kml", dependencies=auth)
    def result_kml(job_id: int, name: str = Query(...)):
        rd, _ = resolve_result_dir(job_id)
        try:
            path = results.kml_path(rd, name)
        except ResultError as e:
            raise result_error(e)
        if not path.is_file():
            raise HTTPException(410, "kml no longer available")
        return StreamingResponse(
            io.BytesIO(path.read_bytes()), media_type="application/vnd.google-earth.kml+xml",
            headers=_attachment(f"job{job_id}_{name}.kml"))

    @app.get("/jobs/{job_id}/result/plots/{kind}", dependencies=auth)
    def result_plot(job_id: int, kind: str, format: str = Query("png"),
                    select: Optional[str] = Query(None), column: Optional[str] = Query(None),
                    phase: str = Query("stage1"), t_start: Optional[float] = Query(None),
                    t_end: Optional[float] = Query(None), table: Optional[str] = Query(None),
                    metric: Optional[str] = Query(None), bins: int = Query(30),
                    axes: str = Query("ne")):
        rd, _ = resolve_result_dir(job_id)
        if format not in _IMAGE_MEDIA:
            raise HTTPException(422, f"unknown format: {format}")
        try:
            if kind == "timeseries":
                if not select or not column:
                    raise HTTPException(422, "timeseries needs select and column")
                blob = plots.timeseries(rd, select=select, column=column, phase=phase,
                                        t_start=t_start, t_end=t_end, fmt=format)
            elif kind == "histogram":
                if not table or not metric:
                    raise HTTPException(422, "histogram needs table and metric")
                blob = plots.histogram(rd, table=table, metric=metric, bins=bins, fmt=format)
            elif kind == "dispersion":
                if not table:
                    raise HTTPException(422, "dispersion needs table")
                blob = plots.dispersion(rd, table=table, axes=axes, fmt=format)
            else:
                raise HTTPException(422, f"unknown plot kind: {kind}")
        except ResultError as e:
            raise result_error(e)
        media = _IMAGE_MEDIA[format]
        return StreamingResponse(io.BytesIO(blob), media_type=media,
                                 headers=_attachment(f"job{job_id}_{kind}.{format}"))

    return app


def _log_to_csv(log: dict) -> str:
    import pandas as pd
    return pd.DataFrame(log["rows"], columns=log["columns"]).to_csv(index=False)


def _zip_logs_response(job_id: int, logs):
    """Stream a zip of one CSV per log via a temp file (not an in-memory BytesIO) so a wide
    request does not balloon service memory (design §4.2 / review Y5)."""
    import tempfile
    import zipfile

    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for log in logs:
                fname = f"case{log['case']}_{log['phase']}_{log['kind']}.csv"
                zf.writestr(fname, _log_to_csv(log))
        tmp.flush()
        tmp.close()
        path = tmp.name

        def _iter():
            with open(path, "rb") as f:
                while chunk := f.read(65536):
                    yield chunk
            os.unlink(path)

        return StreamingResponse(
            _iter(), media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="job{job_id}_extract.zip"',
                     "X-Content-Type-Options": "nosniff"})
    except Exception:
        tmp.close()
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
        raise
