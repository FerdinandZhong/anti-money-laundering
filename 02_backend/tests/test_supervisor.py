import pytest


@pytest.fixture(autouse=True)
def _stub_chat(monkeypatch):
    """run_investigation fans out to 4 real workers (each hits the source layer
    + LLM) then streams a narrative token generator. Stub the LLM call so the
    test only exercises the supervisor's own event-sequencing/SSE contract."""
    from agents import supervisor

    def _fake_chat(messages, stream=False):
        assert stream is True
        return iter(["Hello", " world"])

    monkeypatch.setattr(supervisor, "chat", _fake_chat)


def _fake_worker(name):
    def _run(**kwargs):
        return {"worker": name, "findings": f"• {name} finding", "evidence_ids": [f"EVD-{name}"]}
    return _run


def _stub_workers(monkeypatch, supervisor, pattern_worker=None):
    monkeypatch.setattr(supervisor, "run_profile_worker", _fake_worker("profile"))
    monkeypatch.setattr(supervisor, "run_pattern_worker", pattern_worker or _fake_worker("pattern"))
    monkeypatch.setattr(supervisor, "run_network_worker", _fake_worker("network"))
    monkeypatch.setattr(supervisor, "run_screening_worker", _fake_worker("screening"))


def test_run_investigation_event_sequence_and_shapes(monkeypatch):
    from agents import supervisor
    _stub_workers(monkeypatch, supervisor)

    events = list(supervisor.run_investigation("CASE-1", "ALERT-1", "CUST-1", "ACC-1"))
    types = [e["type"] for e in events]
    phases = [e["phase"] for e in events if e["type"] == "phase"]

    assert phases == ["COLLECTING", "ANALYZING", "REVIEWED"]
    assert types.count("worker_start") == 4
    assert types.count("worker_done") == 4
    assert types.count("token") == 2
    assert "".join(e["text"] for e in events if e["type"] == "token") == "Hello world"
    assert types[-1] == "done"

    worker_done_names = {e["worker"] for e in events if e["type"] == "worker_done"}
    assert worker_done_names == {"profile", "pattern", "network", "screening"}
    for e in events:
        if e["type"] == "worker_done":
            assert set(e.keys()) == {"type", "worker", "findings", "evidence_ids"}


def test_run_investigation_survives_a_worker_exception(monkeypatch):
    """A worker raising must not kill the generator — supervisor.py wraps
    fut.result() and yields an Error: finding instead of propagating."""
    from agents import supervisor

    def _boom(**kwargs):
        raise RuntimeError("source layer unreachable")

    _stub_workers(monkeypatch, supervisor, pattern_worker=_boom)

    events = list(supervisor.run_investigation("CASE-1", "ALERT-1", "CUST-1", "ACC-1"))

    done_events = {e["worker"]: e for e in events if e["type"] == "worker_done"}
    assert set(done_events) == {"profile", "pattern", "network", "screening"}
    assert done_events["pattern"]["findings"].startswith("Error:")
    assert done_events["pattern"]["evidence_ids"] == []
    # the pipeline still completes despite the worker failure
    assert events[-1]["type"] == "done"
