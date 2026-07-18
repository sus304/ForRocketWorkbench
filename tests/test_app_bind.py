"""The NiceGUI frontend must not be reachable on the university LAN (design §13-3).

NiceGUI defaults to 0.0.0.0, which exposed the GUI on the LAN. The frontend now binds only to
loopback (use case ②, the default) or a tailscale-interface address (use case ③), reusing the
same bind-host policy as the compute service (service.serve.validate_bind_host).
"""
import importlib

import pytest

import app as app_module
from service.serve import BindError


def test_ui_host_defaults_to_loopback(monkeypatch):
    monkeypatch.delenv("WB_UI_HOST", raising=False)
    assert app_module._ui_host() == "127.0.0.1"


def test_ui_host_allows_tailnet_address(monkeypatch):
    monkeypatch.setenv("WB_UI_HOST", "100.101.102.103")
    assert app_module._ui_host() == "100.101.102.103"


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "10.0.0.1"])
def test_ui_host_refuses_lan_and_wildcard(monkeypatch, host):
    monkeypatch.setenv("WB_UI_HOST", host)
    with pytest.raises(BindError):
        app_module._ui_host()
