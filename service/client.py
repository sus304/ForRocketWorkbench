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
