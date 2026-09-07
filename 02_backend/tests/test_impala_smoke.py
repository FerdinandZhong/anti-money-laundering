import pytest


def test_check_connectivity_reports_tcp_preflight_failure():
    """Unreachable host -> structured failure, no exception, no real network
    hang (0.2s timeout via _preflight's default path)."""
    import scripts.impala_smoke as smoke

    result = smoke.check_connectivity(host="127.0.0.1", port=1, candidate_paths=["x"])
    assert result["ok"] is False
    assert result["stage"] == "tcp_preflight"
    assert result["http_path"] is None


def test_check_connectivity_tries_each_candidate_path(monkeypatch):
    """When TCP succeeds but auth fails on every path, all candidates should
    be attempted and reported."""
    import scripts.impala_smoke as smoke

    monkeypatch.setattr(smoke, "_preflight", lambda host, port, timeout=6: (True, ""))
    monkeypatch.setattr(smoke, "_password", lambda: "fake-password")

    class _FakeConnectModule:
        @staticmethod
        def connect(**kwargs):
            raise RuntimeError(f"auth rejected for http_path={kwargs['http_path']}")

    monkeypatch.setitem(__import__("sys").modules, "impala.dbapi", _FakeConnectModule())

    result = smoke.check_connectivity(candidate_paths=["path-a", "path-b"])
    assert result["ok"] is False
    assert result["stage"] == "auth"
    assert "path-a" in result["message"] and "path-b" in result["message"]


def test_check_connectivity_succeeds_on_first_matching_path(monkeypatch):
    import scripts.impala_smoke as smoke

    monkeypatch.setattr(smoke, "_preflight", lambda host, port, timeout=6: (True, ""))
    monkeypatch.setattr(smoke, "_password", lambda: "fake-password")

    class _FakeCursor:
        def execute(self, sql):
            pass

        def fetchall(self):
            return [(1,)]

        def close(self):
            pass

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

        def close(self):
            pass

    class _FakeConnectModule:
        @staticmethod
        def connect(**kwargs):
            if kwargs["http_path"] != "the-right-one":
                raise RuntimeError("wrong path")
            return _FakeConn()

    monkeypatch.setitem(__import__("sys").modules, "impala.dbapi", _FakeConnectModule())

    result = smoke.check_connectivity(candidate_paths=["wrong-a", "the-right-one", "wrong-b"])
    assert result["ok"] is True
    assert result["http_path"] == "the-right-one"
