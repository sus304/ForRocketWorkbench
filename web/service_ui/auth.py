"""Session-login helpers for the VM-resident UI (docs/result_retrieval_design.md §3.3 / R1).

The UI holds the service bearer token and proxies calls for the browser, so the tailnet-facing
UI must authenticate its users — otherwise any tailnet node could drive submit/cancel/results
through the UI without a token, defeating the service's token layer (design §7). app_server wires
an auth middleware around these pure helpers; the constant-time password check and the public-path
allowlist are unit-tested here, the NiceGUI flow is verified in the browser.
"""
from __future__ import annotations

import hmac

# Paths reachable without a session: the login page itself and NiceGUI's own framework/static
# routes (websocket, assets) that must load for the login page to work.
_PUBLIC_PREFIXES = ("/login", "/_nicegui", "/static", "/favicon", "/health")


def is_public_path(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") or path.startswith(p)
               for p in _PUBLIC_PREFIXES)


def check_password(supplied: str, expected: str) -> bool:
    """Constant-time password comparison. An empty configured password denies all (fail closed):
    app_server refuses to start without WB_UI_PASSWORD, so this only guards against misuse."""
    if not expected:
        return False
    return hmac.compare_digest(supplied or "", expected)
