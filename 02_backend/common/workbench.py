"""Cloudera AI Workbench client — CML API v2 (jobs + model deployments).

Mirrors common/caii.py: bearer auth (CAI_WORKBENCH_API_KEY env, or /tmp/jwt),
requests-based, and fails soft — locally (no host/key/project) `configured()`
returns False and callers fall back to a local retrain + simulated canary.

Used by agents/retraining.py to drive the retraining pipeline:
  create_training_job -> run_job -> (poll) get_job_run -> canary_deploy

Direct REST v2 by design — the stdio MCP server (github.com/cloudera/
CAI_Workbench_MCP_Server) wraps these same cmlapi operations for external agent
hosts; the backend calls the API directly instead of spawning it.

# ponytail: CML API v2 has no traffic-split canary. "canary" = a fresh model
# build deployed alongside the old one; the traffic flip lives in the ops
# `deployments` table (CANARY -> CHAMPION), done by the retraining workflow.
"""
import os
import json

_JWT_PATH = "/tmp/jwt"


class WorkbenchError(RuntimeError):
    """Raised on any Workbench API failure so the workflow can fall back."""


# ── config / credential resolution (mirrors caii.py) ─────────────────────────

def _cfg() -> dict:
    from common.config import get_config
    return get_config().get("workbench") or {}


def _host() -> str:
    """Workbench base host, e.g. https://ml-xxxx.cloudera.site (no trailing /)."""
    host = (os.environ.get("CAI_WORKBENCH_HOST") or _cfg().get("host") or "").strip()
    return host.rstrip("/")


def _project() -> str:
    return (os.environ.get("CAI_WORKBENCH_PROJECT_ID") or _cfg().get("project_id") or "").strip()


def _token() -> str:
    """Bearer: CAI_WORKBENCH_API_KEY / CDP_TOKEN env, else /tmp/jwt (JSON
    access_token or plain)."""
    for key in ("CAI_WORKBENCH_API_KEY", "CDP_TOKEN_OVERRIDE", "CDP_TOKEN"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    try:
        with open(_JWT_PATH, encoding="utf-8") as f:
            text = f.read().strip()
    except OSError:
        return ""
    if not text:
        return ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    return str(data.get("access_token") or "").strip() if isinstance(data, dict) else ""


def mode() -> str:
    """'mcp' (Tools-tab params present) | 'rest' (env/config present) | 'local'."""
    from common import mcp_client
    if mcp_client.embedded_params("workbench-mcp") is not None:
        return "mcp"
    if _host() and _project() and _token():
        return "rest"
    return "local"


def configured() -> bool:
    """True when the retraining workflow can reach a real Workbench (MCP or REST)."""
    return mode() != "local"


# ── MCP routing (embedded CAI_Workbench_MCP_Server) ──────────────────────────

def _mcp_tool(candidates: list[str]) -> str:
    """Resolve the actual tool name exposed by the server; the 105-tool server
    wraps cmlapi so names follow its conventions, but we verify at runtime."""
    from common import mcp_client
    listed = mcp_client.list_embedded_tools("workbench-mcp") or []
    names = {t["name"] for t in listed}
    for c in candidates:
        if c in names:
            return c
    raise WorkbenchError(f"workbench-mcp exposes none of {candidates}")


def _mcp_call(candidates: list[str], args: dict) -> dict:
    from common import mcp_client
    res = mcp_client.call_embedded("workbench-mcp", _mcp_tool(candidates), args)
    if isinstance(res, dict) and "error" in res:
        raise WorkbenchError(str(res["error"]))
    try:
        out = json.loads(res) if isinstance(res, str) else res
    except ValueError:
        raise WorkbenchError(f"workbench-mcp returned non-JSON: {str(res)[:200]}")
    return out if isinstance(out, dict) else {}


# ── thin REST helpers ────────────────────────────────────────────────────────

def _base() -> str:
    return f"{_host()}/api/v2/projects/{_project()}"


def _req(method: str, path: str, body: dict | None = None, timeout: float = 30.0) -> dict:
    if not configured():
        raise WorkbenchError("Workbench not configured (host/project/api_key missing)")
    import requests
    url = f"{_base()}{path}"
    try:
        resp = requests.request(
            method, url,
            headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
            json=body,
            timeout=timeout,
        )
        resp.raise_for_status()
    except Exception as e:  # network, HTTP, timeout — all become WorkbenchError
        raise WorkbenchError(f"{method} {path} failed: {e}") from e
    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError:
        return {}


# ── jobs (step 1 + 2) ────────────────────────────────────────────────────────

def create_training_job(name: str, script: str, runtime_id: str | None = None,
                        cpu: float = 1.0, memory: float = 4.0) -> str:
    """POST /jobs — create a manual training job. Returns job_id."""
    if mode() == "mcp":
        body: dict = {"name": name, "script": script, "kernel": "python3",
                      "cpu": cpu, "memory": memory}
        if runtime_id:
            body["runtime_identifier"] = runtime_id
        out = _mcp_call(["create_job"], body)
        job_id = out.get("id") or out.get("job", {}).get("id")
        if not job_id:
            raise WorkbenchError(f"mcp create_job returned no id: {out}")
        return str(job_id)
    # ── existing REST path unchanged ──
    body: dict = {"name": name, "script": script, "kernel": "python3",
                  "cpu": cpu, "memory": memory}
    if runtime_id:
        body["runtime_identifier"] = runtime_id
    out = _req("POST", "/jobs", body)
    job_id = out.get("id") or out.get("job", {}).get("id")
    if not job_id:
        raise WorkbenchError(f"create_job returned no id: {out}")
    return str(job_id)


def run_job(job_id: str) -> str:
    """POST /jobs/{id}/runs — trigger a run. Returns run_id."""
    if mode() == "mcp":
        out = _mcp_call(["create_job_run"], {"job_id": job_id})
        run_id = out.get("id") or out.get("job_run", {}).get("id")
        if not run_id:
            raise WorkbenchError(f"mcp create_job_run returned no id: {out}")
        return str(run_id)
    # ── existing REST path unchanged ──
    out = _req("POST", f"/jobs/{job_id}/runs", {})
    run_id = out.get("id") or out.get("job_run", {}).get("id")
    if not run_id:
        raise WorkbenchError(f"create_job_run returned no id: {out}")
    return str(run_id)


def get_job_run(job_id: str, run_id: str) -> dict:
    """GET /jobs/{id}/runs/{run_id} — {status, ...}. Status strings like
    ENGINE_SUCCEEDED / ENGINE_RUNNING / ENGINE_FAILED / ENGINE_STOPPED."""
    if mode() == "mcp":
        return _mcp_call(["get_job_run"], {"job_id": job_id, "run_id": run_id})
    # ── existing REST path unchanged ──
    return _req("GET", f"/jobs/{job_id}/runs/{run_id}", timeout=15.0)


def run_succeeded(status: str) -> bool:
    return "SUCCEEDED" in (status or "").upper()


def run_terminal(status: str) -> bool:
    s = (status or "").upper()
    return any(k in s for k in ("SUCCEEDED", "FAILED", "STOPPED", "TIMEDOUT", "TIMED_OUT"))


# ── model canary deploy (step 3) ─────────────────────────────────────────────

def _find_model(name: str) -> str | None:
    out = _req("GET", "/models", timeout=15.0)
    for m in (out.get("models") or []):
        if m.get("name") == name:
            return str(m.get("id"))
    return None


def canary_deploy(model_version: str, model_name: str, script: str,
                  function_name: str = "predict", runtime_id: str | None = None,
                  cpu: float = 1.0, memory: float = 2.0) -> dict:
    """Create-or-reuse model -> new build -> new deployment (the 'canary').

    Returns {model_id, build_id, deployment_id}. Raises WorkbenchError on any
    failure so the workflow can fall back to a DB-only canary.
    """
    if mode() == "mcp":
        # find-or-create model
        models_out = _mcp_call(["list_models"], {})
        model_id = None
        for m in (models_out.get("models") or []):
            if m.get("name") == model_name:
                model_id = str(m.get("id"))
                break
        if not model_id:
            out = _mcp_call(["create_model"], {"name": model_name,
                                               "description": f"AML risk model ({model_version})"})
            model_id = str(out.get("id") or out.get("model", {}).get("id") or "")
            if not model_id:
                raise WorkbenchError(f"mcp create_model returned no id: {out}")

        build_body: dict = {
            "model_id": model_id,
            "file_path": script,
            "function_name": function_name,
            "kernel": "python3",
            "comment": f"retrain {model_version}",
        }
        if runtime_id:
            build_body["runtime_identifier"] = runtime_id
        build = _mcp_call(["create_model_build"], build_body)
        build_id = str(build.get("id") or build.get("model_build", {}).get("id") or "")
        if not build_id:
            raise WorkbenchError(f"mcp create_model_build returned no id: {build}")

        dep = _mcp_call(["create_model_deployment"], {
            "model_id": model_id, "build_id": build_id,
            "name": f"canary-{model_version}", "cpu": cpu, "memory": memory,
        })
        dep_id = str(dep.get("id") or dep.get("model_deployment", {}).get("id") or "")
        if not dep_id:
            raise WorkbenchError(f"mcp create_model_deployment returned no id: {dep}")

        return {"model_id": model_id, "build_id": build_id, "deployment_id": dep_id}

    # ── existing REST path unchanged ──
    model_id = _find_model(model_name)
    if not model_id:
        out = _req("POST", "/models", {"name": model_name,
                                        "description": f"AML risk model ({model_version})"})
        model_id = str(out.get("id") or out.get("model", {}).get("id") or "")
        if not model_id:
            raise WorkbenchError(f"create_model returned no id: {out}")

    build = _req("POST", f"/models/{model_id}/builds", {
        "file_path": script,
        "function_name": function_name,
        "kernel": "python3",
        **({"runtime_identifier": runtime_id} if runtime_id else {}),
        "comment": f"retrain {model_version}",
    })
    build_id = str(build.get("id") or build.get("model_build", {}).get("id") or "")
    if not build_id:
        raise WorkbenchError(f"create_model_build returned no id: {build}")

    dep = _req("POST", f"/models/{model_id}/builds/{build_id}/deployments", {
        "name": f"canary-{model_version}", "cpu": cpu, "memory": memory,
    })
    dep_id = str(dep.get("id") or dep.get("model_deployment", {}).get("id") or "")
    if not dep_id:
        raise WorkbenchError(f"create_model_deployment returned no id: {dep}")

    return {"model_id": model_id, "build_id": build_id, "deployment_id": dep_id}


if __name__ == "__main__":
    if configured():
        print(f"[workbench] configured — host={_host()} project={_project()}")
        try:
            jobs = _req("GET", "/jobs", timeout=15.0)
            print(f"[workbench] reachable — {len(jobs.get('jobs', []))} existing job(s)")
        except WorkbenchError as e:
            print(f"[workbench] configured but unreachable: {e}")
    else:
        print("[workbench] not configured — local fallback "
              "(set CAI_WORKBENCH_HOST / _PROJECT_ID / _API_KEY to enable)")
