# 02_backend/tests/test_workbench_mcp.py
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import workbench, mcp_client


def _mcp_configured(monkeypatch, tools=("create_job", "create_job_run",
                                        "get_job_run", "create_model",
                                        "create_model_build", "create_model_deployment")):
    monkeypatch.setattr(mcp_client, "embedded_params",
                        lambda name: {"host": "https://ml-x", "api_key": "k",
                                      "project_id": "pid"} if name == "workbench-mcp" else None)
    monkeypatch.setattr(mcp_client, "list_embedded_tools",
                        lambda name: [{"name": t} for t in tools])


def test_mode_local_when_nothing(monkeypatch):
    monkeypatch.setattr(mcp_client, "embedded_params", lambda name: None)
    for k in ("CAI_WORKBENCH_HOST", "CAI_WORKBENCH_PROJECT_ID", "CAI_WORKBENCH_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert workbench.mode() == "local"
    assert workbench.configured() is False


def test_mode_mcp_when_tools_params(monkeypatch):
    _mcp_configured(monkeypatch)
    assert workbench.mode() == "mcp"
    assert workbench.configured() is True


def test_create_job_routes_through_mcp(monkeypatch):
    _mcp_configured(monkeypatch)
    calls = []
    def fake_call(name, tool, args):
        calls.append((tool, args))
        return json.dumps({"id": "job-42"})
    monkeypatch.setattr(mcp_client, "call_embedded", fake_call)
    job_id = workbench.create_training_job("aml-retrain", "02_backend/ml/train.py")
    assert job_id == "job-42"
    assert calls[0][0] == "create_job"


def test_mcp_error_raises_workbench_error(monkeypatch):
    _mcp_configured(monkeypatch)
    monkeypatch.setattr(mcp_client, "call_embedded",
                        lambda name, tool, args: {"error": "boom"})
    import pytest
    with pytest.raises(workbench.WorkbenchError):
        workbench.create_training_job("aml-retrain", "x.py")


def test_missing_tool_name_raises(monkeypatch):
    _mcp_configured(monkeypatch, tools=("something_else",))
    import pytest
    with pytest.raises(workbench.WorkbenchError):
        workbench.create_training_job("aml-retrain", "x.py")


def test_canary_deploy_routes_through_mcp(monkeypatch):
    _mcp_configured(monkeypatch, tools=("list_models", "create_model",
                                        "create_model_build", "create_model_deployment"))
    calls = []

    def fake_call(name, tool, args):
        calls.append((tool, args))
        if tool == "list_models":
            return json.dumps({"models": []})          # no existing model → force create
        if tool == "create_model":
            return json.dumps({"id": "m-1"})
        if tool == "create_model_build":
            return json.dumps({"id": "b-1"})
        if tool == "create_model_deployment":
            return json.dumps({"id": "d-1"})
        return json.dumps({})

    monkeypatch.setattr(mcp_client, "call_embedded", fake_call)
    result = workbench.canary_deploy(
        model_version="v1",
        model_name="aml-risk-model",
        script="02_backend/ml/train.py",
    )
    assert result["model_id"] == "m-1"
    assert result["build_id"] == "b-1"
    assert result["deployment_id"] == "d-1"
    tool_names = [c[0] for c in calls]
    assert "create_model_deployment" in tool_names
