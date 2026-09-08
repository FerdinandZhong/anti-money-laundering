"""run_verification_worker: parses verdicts from a tool-calling reply, records
tool events, and fails soft (returns None) when no MCP server is configured.

The MCP layer and LLM are stubbed — the loop itself is covered in
test_llm_client::chat_with_tools.
"""
from agents import workers

_FINDINGS = [
    {"worker": "profile",   "findings": "• Customer is a PEP in high-risk jurisdiction"},
    {"worker": "screening", "findings": "• Possible sanctions match on counterparty"},
]


def test_returns_none_when_no_mcp_configured(monkeypatch):
    monkeypatch.setattr(workers, "mcp_verification_tools", lambda: ([], lambda n, a: ""))
    assert workers.run_verification_worker("CASE-1", _FINDINGS) is None


def test_parses_verdicts_and_tool_events(monkeypatch):
    # a non-empty tool set → verification runs
    monkeypatch.setattr(
        workers, "mcp_verification_tools",
        lambda: ([{"type": "function", "function": {"name": "sanctions_check", "parameters": {}}}],
                 lambda n, a: "result"),
    )
    monkeypatch.setattr(workers, "_ev", lambda *a, **k: "EVD-verification")

    reply = (
        'Here you go: {"verdicts":['
        '{"claim":"PEP status","verdict":"confirmed","sources":["https://reg.example/x"]},'
        '{"claim":"sanctions match","verdict":"REFUTED","sources":[]},'
        '{"claim":"other","verdict":"nonsense","sources":[]}]}'
    )

    def fake_cwt(messages, tools, execute, max_iters=4, on_event=None):
        if on_event:
            on_event("sanctions_check", {"name": "ACME"}, "no match")
        return reply

    monkeypatch.setattr(workers, "chat_with_tools", fake_cwt)

    out = workers.run_verification_worker("CASE-1", _FINDINGS)
    assert out is not None
    assert out["worker"] == "verification"
    verdicts = out["verdicts"]
    assert [v["verdict"] for v in verdicts] == ["confirmed", "refuted", "unverified"]  # normalized
    assert verdicts[0]["sources"] == ["https://reg.example/x"]
    assert len(out["tool_events"]) == 1
    assert out["tool_events"][0]["name"] == "sanctions_check"


def test_survives_unparseable_reply(monkeypatch):
    monkeypatch.setattr(
        workers, "mcp_verification_tools",
        lambda: ([{"type": "function", "function": {"name": "t", "parameters": {}}}], lambda n, a: ""),
    )
    monkeypatch.setattr(workers, "_ev", lambda *a, **k: "EVD-x")
    monkeypatch.setattr(workers, "chat_with_tools", lambda *a, **k: "sorry, no JSON here")

    out = workers.run_verification_worker("CASE-1", _FINDINGS)
    assert out is not None and out["verdicts"] == []
