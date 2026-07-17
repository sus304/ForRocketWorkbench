"""Optional, service-agnostic completion/alert notification (design §8).

Notification is decoupled and off by default: with no WB_NOTIFY_URL there is no push at all
(status stays visible via the API/UI). When a URL is set, a single generic webhook POST is
made; the kind is auto-detected (ntfy / Slack / generic) or forced via WB_NOTIFY_KIND. ntfy
is recommended because it needs no corporate key and can be self-hosted on the VM. Delivery
failures are retried a few times and then swallowed: a down notifier must never fail a job.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

try:
    import requests
    _default_post = requests.post
except Exception:  # pragma: no cover - requests is a declared dependency
    _default_post = None


class Notifier:
    def __init__(self, url: Optional[str] = None, kind: Optional[str] = None,
                 post: Optional[Callable] = None, retries: int = 2, timeout: float = 5.0):
        self.url = os.environ.get("WB_NOTIFY_URL", "") if url is None else url
        self.kind = kind or os.environ.get("WB_NOTIFY_KIND", "") or self._detect(self.url)
        self._post = post or _default_post
        self.retries = retries
        self.timeout = timeout

    @staticmethod
    def _detect(url: str) -> str:
        if not url:
            return "none"
        if "hooks.slack.com" in url:
            return "slack"
        if "ntfy" in url:
            return "ntfy"
        return "generic"

    def notify(self, title: str, message: str, priority: str = "default") -> bool:
        """Post a notification. Returns True on success, False if disabled or all attempts
        failed. Never raises."""
        if not self.url or self._post is None:
            return False
        for _ in range(self.retries + 1):
            try:
                self._send(title, message, priority)
                return True
            except Exception:
                continue
        return False

    def _send(self, title: str, message: str, priority: str) -> None:
        if self.kind == "ntfy":
            self._post(self.url, data=message.encode("utf-8"),
                       headers={"Title": title, "Priority": priority}, timeout=self.timeout)
        elif self.kind == "slack":
            self._post(self.url, json={"text": f"*{title}*\n{message}"}, timeout=self.timeout)
        else:
            self._post(self.url, json={"title": title, "message": message, "priority": priority},
                       timeout=self.timeout)
