"""Tests for the new service-native GUI bootstrap (design §9, Phase 9).

The GUI talks to the compute service only over the HTTP client (service.client), never
in-process. This module resolves the connection: the service URL, the bearer token (a local
secret for use case ②), and the local data root the supervisor spawns the service against.
Only the URL differs between ② (localhost) and ③ (tailnet), per the "localhost is the
degenerate server" principle (design §1.1).
"""
import os

import pytest

from web.service_ui import config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("WB_SERVICE_URL", "WB_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)


# --- token -------------------------------------------------------------------

def test_token_is_created_once_and_reused(tmp_path):
    first = config.load_or_create_token(tmp_path)
    assert first  # non-empty secret
    second = config.load_or_create_token(tmp_path)
    assert second == first  # persisted, not regenerated


def test_token_env_overrides_file(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_API_TOKEN", "env-secret")
    assert config.load_or_create_token(tmp_path) == "env-secret"
    # the env value must not be written to disk as the local secret
    assert not (tmp_path / config.TOKEN_FILENAME).exists()


def test_token_file_is_not_world_readable(tmp_path):
    config.load_or_create_token(tmp_path)
    token_file = tmp_path / config.TOKEN_FILENAME
    mode = token_file.stat().st_mode & 0o777
    assert mode & 0o077 == 0  # no group/other access


# --- service url -------------------------------------------------------------

def test_service_url_defaults_to_loopback():
    assert config.service_url() == "http://127.0.0.1:8760"


def test_service_url_respects_env(monkeypatch):
    monkeypatch.setenv("WB_SERVICE_URL", "http://100.101.102.103:8760")
    assert config.service_url() == "http://100.101.102.103:8760"




# --- client ------------------------------------------------------------------

def test_get_client_uses_url_and_token(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_SERVICE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("WB_API_TOKEN", "tok123")
    client = config.get_client(data_root=tmp_path)
    assert client.base == "http://127.0.0.1:9999"
    assert client.headers["Authorization"] == "Bearer tok123"
