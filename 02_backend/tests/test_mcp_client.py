"""mcp_client: fail-soft when unconfigured, parse list_tools, probe result shape.

The async transport + event loop are never exercised here — we patch the sync
bridge `_run` to close the (unawaited) coroutine and return canned data, so the
tests stay fast and offline while still covering the parsing/fail-soft logic.
"""
import pytest

from common import mcp_client


def _patch_run(monkeypatch, ret=None, raises=None):
    def fake_run(coro, timeout=30.0):
        coro.close()   # we never await it; close to avoid "coroutine never awaited"
        if raises:
            raise raises
        return ret
    monkeypatch.setattr(mcp_client, "_run", fake_run)


def test_list_tools_sync_none_when_unconfigured(monkeypatch):
    monkeypatch.setattr(mcp_client, "_server", lambda name: None)
    assert mcp_client.list_tools_sync("nope") is None


def test_list_tools_sync_parses_when_configured(monkeypatch):
    monkeypatch.setattr(mcp_client, "_server", lambda name: {"url": "https://x/mcp", "api_key": None})
    _patch_run(monkeypatch, ret=[{"name": "sanctions_check", "description": "d", "input_schema": {}}])
    tools = mcp_client.list_tools_sync("srv")
    assert [t["name"] for t in tools] == ["sanctions_check"]


def test_call_tool_sync_none_when_unconfigured(monkeypatch):
    monkeypatch.setattr(mcp_client, "_server", lambda name: None)
    assert mcp_client.call_tool_sync("nope", "t", {}) is None


def test_call_tool_sync_wraps_failure_as_error(monkeypatch):
    monkeypatch.setattr(mcp_client, "_server", lambda name: {"url": "https://x/mcp", "api_key": None})
    _patch_run(monkeypatch, raises=RuntimeError("boom"))
    res = mcp_client.call_tool_sync("srv", "t", {})
    assert isinstance(res, dict) and "error" in res


def test_probe_ok_and_failure(monkeypatch):
    _patch_run(monkeypatch, ret=[{"name": "t1"}, {"name": "t2"}])
    ok, res = mcp_client.probe("https://x/mcp", None)
    assert ok and [t["name"] for t in res] == ["t1", "t2"]

    _patch_run(monkeypatch, raises=ConnectionError("no route"))
    ok, res = mcp_client.probe("https://x/mcp", None)
    assert not ok and res.startswith("ConnectionError")


def test_enabled_servers_empty_without_db(monkeypatch):
    # get_connection raises with no DB file → enabled_servers must fail soft to [].
    # Patch both bindings (config + db's own copy) — see conftest for why.
    import common.config as config_mod
    import common.db as db_mod
    monkeypatch.setattr(config_mod, "get_db_path", lambda: "/nonexistent/aml.db")
    monkeypatch.setattr(db_mod, "get_db_path", lambda: "/nonexistent/aml.db")
    assert mcp_client.enabled_servers() == []
