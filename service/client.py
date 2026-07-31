"""HTTP client for the compute service, shared by the `wb` CLI and the GUI (design §4.3).

The same client serves use case ② (base_url = http://127.0.0.1:<port>) and ③ (base_url =
the server's tailnet address): only the URL differs, per the "localhost is the degenerate
server" principle (§1.1). A requests.Session is used by default; tests inject a FastAPI
TestClient.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from service.uploads import pack_closure, safe_extract

try:
    import requests
except Exception:  # pragma: no cover
    requests = None


class ServiceClient:
    def __init__(self, base_url: str, token: str, session=None):
        self.base = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}
        if session is not None:
            self.s = session
        elif requests is not None:
            self.s = requests.Session()
        else:  # pragma: no cover
            raise RuntimeError("requests is required unless a session is supplied")

    def _url(self, path: str) -> str:
        return self.base + path

    def submit(self, project_dir, mode: str, model_name: str = "",
               use_max_thread: bool = False) -> dict:
        blob = pack_closure(project_dir, mode)
        r = self.s.post(
            self._url("/jobs"),
            headers=self.headers,
            data={"mode": mode, "model_name": model_name,
                  "use_max_thread": "true" if use_max_thread else "false"},
            files={"payload": ("closure.tar.gz", blob, "application/gzip")},
        )
        r.raise_for_status()
        return r.json()

    def submit_project(self, project: str, mode: str, use_max_thread: bool = False) -> dict:
        """Submit a run from a server-stored project (no upload; the service packs the closure
        from its own store). The UI-refresh main submit path."""
        r = self.s.post(
            self._url("/jobs"),
            headers=self.headers,
            data={"mode": mode, "project": project,
                  "use_max_thread": "true" if use_max_thread else "false"},
        )
        r.raise_for_status()
        return r.json()

    def status(self, job_id: int) -> dict:
        r = self.s.get(self._url(f"/jobs/{job_id}"), headers=self.headers)
        r.raise_for_status()
        return r.json()

    def list_jobs(self, status: Optional[str] = None) -> list:
        params = {"status": status} if status else {}
        r = self.s.get(self._url("/jobs"), headers=self.headers, params=params)
        r.raise_for_status()
        return r.json()["jobs"]

    def cancel(self, job_id: int) -> dict:
        r = self.s.post(self._url(f"/jobs/{job_id}/cancel"), headers=self.headers)
        r.raise_for_status()
        return r.json()

    def delete_job(self, job_id: int) -> dict:
        r = self.s.delete(self._url(f"/jobs/{job_id}"), headers=self.headers)
        r.raise_for_status()
        return r.json()

    def set_memo(self, job_id: int, memo: str) -> dict:
        r = self.s.put(self._url(f"/jobs/{job_id}/memo"), headers=self.headers,
                       data={"memo": memo})
        r.raise_for_status()
        return r.json()

    def pull(self, job_id: int, dest, full: bool = False) -> Path:
        params = {"full": "1"} if full else {}
        r = self.s.get(self._url(f"/jobs/{job_id}/result.tar.gz"),
                       headers=self.headers, params=params)
        r.raise_for_status()
        safe_extract(r.content, dest)
        return Path(dest)

    def health(self) -> dict:
        r = self.s.get(self._url("/health"))
        r.raise_for_status()
        return r.json()

    # ── server-side project store (design ui_refresh §3) ─────────────────────

    def list_projects(self) -> list:
        r = self.s.get(self._url("/projects"), headers=self.headers)
        r.raise_for_status()
        return r.json()["projects"]

    def create_project(self, name: str) -> dict:
        r = self.s.post(self._url("/projects"), headers=self.headers, data={"name": name})
        r.raise_for_status()
        return r.json()

    def copy_project(self, name: str, dest: str) -> dict:
        r = self.s.post(self._url(f"/projects/{name}/copy"), headers=self.headers,
                        data={"dest": dest})
        r.raise_for_status()
        return r.json()

    def delete_project(self, name: str) -> dict:
        r = self.s.delete(self._url(f"/projects/{name}"), headers=self.headers)
        r.raise_for_status()
        return r.json()

    def get_project_config(self, name: str) -> dict:
        r = self.s.get(self._url(f"/projects/{name}/config"), headers=self.headers)
        r.raise_for_status()
        return r.json()

    def put_project_config(self, name: str, files: dict, if_match: str = None) -> dict:
        import json as _json
        data = {"files": _json.dumps(files)}
        if if_match is not None:
            data["if_match"] = if_match
        r = self.s.put(self._url(f"/projects/{name}/config"), headers=self.headers, data=data)
        r.raise_for_status()
        return r.json()

    def upload_project(self, name: str, zip_bytes: bytes) -> dict:
        r = self.s.post(self._url(f"/projects/{name}/upload"), headers=self.headers,
                        files={"payload": ("project.zip", zip_bytes, "application/zip")})
        r.raise_for_status()
        return r.json()

    def download_project(self, name: str) -> bytes:
        r = self.s.get(self._url(f"/projects/{name}/download"), headers=self.headers)
        r.raise_for_status()
        return r.content

    def list_project_files(self, name: str) -> dict:
        """{'files': [{path,size,is_config}], 'referenced': [path,...]} for the project's input
        files (config values are edited via get/put_project_config)."""
        r = self.s.get(self._url(f"/projects/{name}/files"), headers=self.headers)
        r.raise_for_status()
        return r.json()

    def download_project_file(self, name: str, path: str) -> bytes:
        r = self.s.get(self._url(f"/projects/{name}/files/download"),
                       headers=self.headers, params={"path": path})
        r.raise_for_status()
        return r.content

    def upload_project_file(self, name: str, path: str, data: bytes) -> dict:
        r = self.s.post(self._url(f"/projects/{name}/files"), headers=self.headers,
                        data={"path": path},
                        files={"payload": (path.rsplit("/", 1)[-1], data,
                                           "application/octet-stream")})
        r.raise_for_status()
        return r.json()

    def delete_project_file(self, name: str, path: str) -> dict:
        r = self.s.delete(self._url(f"/projects/{name}/files"),
                          headers=self.headers, params={"path": path})
        r.raise_for_status()
        return r.json()

    # ── remote result API (design §4-5). The GUI and `wb extract` reach results through these
    # rather than reading result_dir directly, so decimation/limits are enforced in one place
    # and the mixed-topology (local UI -> remote service) path keeps working (§3.4). ──────────

    def result_meta(self, job_id: int) -> dict:
        r = self.s.get(self._url(f"/jobs/{job_id}/result/meta"), headers=self.headers)
        r.raise_for_status()
        return r.json()

    def result_summary(self, job_id: int) -> list:
        r = self.s.get(self._url(f"/jobs/{job_id}/result/summary"), headers=self.headers)
        r.raise_for_status()
        return r.json()["items"]

    def result_table(self, job_id: int, name: str) -> dict:
        r = self.s.get(self._url(f"/jobs/{job_id}/result/tables/{name}"), headers=self.headers)
        r.raise_for_status()
        return r.json()

    def result_cases(self, job_id: int, select: str) -> list:
        r = self.s.get(self._url(f"/jobs/{job_id}/result/cases"),
                       headers=self.headers, params={"select": select})
        r.raise_for_status()
        return r.json()["cases"]

    def extract(self, job_id: int, select: str, **params) -> dict:
        """Extract per-case logs as JSON (column-oriented). params: phase/kind/columns/
        t_start/t_end/max_points (columns may be a list or comma string)."""
        q = _extract_params(select, params)
        r = self.s.get(self._url(f"/jobs/{job_id}/result/extract"), headers=self.headers, params=q)
        r.raise_for_status()
        return r.json()

    def extract_file(self, job_id: int, select: str, fmt: str = "csv", **params) -> bytes:
        """Extract as a downloadable file (fmt='csv' single log, or 'zip' bundle). Returns bytes
        for the UI to proxy to the browser (design §6)."""
        q = _extract_params(select, params)
        q["format"] = fmt
        r = self.s.get(self._url(f"/jobs/{job_id}/result/extract"), headers=self.headers, params=q)
        r.raise_for_status()
        return r.content

    def plot(self, job_id: int, kind: str, fmt: str = "png", **params) -> bytes:
        """Fetch a document image (kind timeseries/histogram/dispersion) as PNG/SVG bytes."""
        q = {k: v for k, v in params.items() if v is not None}
        q["format"] = fmt
        r = self.s.get(self._url(f"/jobs/{job_id}/result/plots/{kind}"),
                       headers=self.headers, params=q)
        r.raise_for_status()
        return r.content


def _extract_params(select: str, params: dict) -> dict:
    q = {"select": select}
    for k, v in params.items():
        if v is None:
            continue
        if k == "columns" and isinstance(v, (list, tuple)):
            v = ",".join(v)
        q[k] = v
    return q
