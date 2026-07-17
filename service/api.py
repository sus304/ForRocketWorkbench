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
import shutil
import time
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from runner_tool.run_manifest import RunManifest
from service.store import JobStore, PREPARING, QUEUED, RUNNING, TERMINAL_STATUSES
from service.uploads import pack_result, safe_extract, UploadError
from service.worker import Worker

_MODES = {"trajectory", "area", "montecarlo", "sensitivity"}
_ACTIVE = {PREPARING, QUEUED, RUNNING}


def _iso(dt):
    return dt.isoformat() if dt else None


def create_app(store: JobStore, worker: Worker, token: str) -> FastAPI:
    app = FastAPI(title="ForRocket Workbench Job Service")

    def require_token(authorization: Optional[str] = Header(None)):
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
            "capability": {"can_cancel": job.status in _ACTIVE},
            "progress": progress_of(job),
        }

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
        try:
            blob = pack_result(rd, full=full)
        except UploadError as e:
            raise HTTPException(409, str(e))
        return StreamingResponse(
            io.BytesIO(blob),
            media_type="application/gzip",
            headers={"Content-Disposition": f'attachment; filename="job{job_id}_result.tar.gz"'},
        )

    return app
