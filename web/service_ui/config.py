"""GUI-to-service connection bootstrap (design §1.1, §7, Phase 9).

Resolves the three things the GUI needs to reach the compute service:

- **service URL** — `WB_SERVICE_URL`, default the loopback service (use case ②). Point it at
  the server's tailnet address for ③; nothing else in the GUI changes (design §1.1).
- **bearer token** — `WB_API_TOKEN` if set, else a per-machine local secret persisted under
  the data root (§7: for ② an auto-generated local secret suffices). Kept out of the repo/DB;
  the file is created 0600 and lives under the gitignored data root.
- **data root** — where the local service (spawned by the supervisor for ②) keeps its store
  and run tree.

The GUI never embeds the worker: it launches the service as a separate supervised process so
a UI crash cannot kill a running job (design §4.3).
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from service.client import ServiceClient

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

TOKEN_FILENAME = ".token"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8760
DEFAULT_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"


def default_data_root() -> Path:
    """Local data root for the ② service (store + run tree). Gitignored."""
    return Path(os.environ.get("WB_DATA_ROOT", str(_REPO_ROOT / "service_data")))


def load_or_create_token(data_root) -> str:
    """Return the API token. `WB_API_TOKEN` wins (and is never written to disk); otherwise a
    local secret is read from — or created in — `<data_root>/.token` (0600)."""
    env = os.environ.get("WB_API_TOKEN")
    if env:
        return env
    data_root = Path(data_root)
    token_file = data_root / TOKEN_FILENAME
    if token_file.exists():
        tok = token_file.read_text().strip()
        if tok:
            return tok
    data_root.mkdir(parents=True, exist_ok=True)
    tok = secrets.token_urlsafe(32)
    # Create restrictively (0600) so a shared machine cannot read the local secret.
    fd = os.open(str(token_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, tok.encode())
    finally:
        os.close(fd)
    return tok


def service_url() -> str:
    return os.environ.get("WB_SERVICE_URL", DEFAULT_URL)


def get_client(data_root=None, session=None) -> ServiceClient:
    root = default_data_root() if data_root is None else Path(data_root)
    return ServiceClient(service_url(), load_or_create_token(root), session=session)
