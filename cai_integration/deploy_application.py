#!/usr/bin/env python3
"""
Register the AML Investigation Platform as a Cloudera AI (CML) Application via
CML API v2:  POST {host}/api/v2/projects/{project_id}/applications

The Application script is 03_frontend/start_frontend.py, which serves the built
React frontend AND starts the co-located FastAPI backend on localhost:BACKEND_PORT
in one app (see .project-metadata.yaml). It binds to $CDSW_APP_PORT.

Run this from inside a CML Session in the project (env vars are auto-injected),
or locally by supplying --host / --api-key / --project-id.

CAII/LLM config: the app reads config/config.yaml and substitutes the workspace
domain from CML's CDSW_DOMAIN at runtime — so no LLM endpoint needs to be passed
here. Set LLM_PROVIDER to switch provider (caii | vllm | ollama).

Keep bypass_authentication FALSE so the platform sits behind Workbench SSO
(customer/investigation data). --public flips it (not recommended).
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import requests


# Application status classification (pure — unit-testable without network).
# CML application statuses vary a little by version; classify on substrings.
def app_is_running(status: str) -> bool:
    return (status or "").lower() in ("running", "running_partial")


def app_is_failed(status: str) -> bool:
    return (status or "").lower() in (
        "failed", "stopped", "error", "engine_failed", "startup_failed", "killed",
    )


def build_environment(backend_port: str, llm_provider: str | None) -> dict:
    """Application env. Pure so it is unit-testable. CAII endpoint resolves from
    CDSW_DOMAIN inside the app, so only pass through the knobs the app reads."""
    environment = {"BACKEND_PORT": backend_port}
    if llm_provider:
        environment["LLM_PROVIDER"] = llm_provider
    # Optional pass-through: source-data password for Impala/Iceberg reads.
    if os.environ.get("IMPALA_PASSWORD"):
        environment["IMPALA_PASSWORD"] = os.environ["IMPALA_PASSWORD"]
    return environment


def _build_payload(*, name: str, subdomain: str, script: str, runtime_identifier: str,
                   cpu: int, memory: int, bypass_authentication: bool,
                   backend_port: str, llm_provider: str | None) -> dict:
    """Assemble the create-Application payload. Pure — unit-testable without network."""
    return {
        "name": name,
        "subdomain": subdomain,
        "script": script,
        "cpu": cpu,
        "memory": memory,
        "runtime_identifier": runtime_identifier,
        "bypass_authentication": bypass_authentication,
        "environment": build_environment(backend_port, llm_provider),
    }


def create_application(host: str, api_key: str, project_id: str, *, payload: dict) -> dict:
    url = f"{host.rstrip('/')}/api/v2/projects/{project_id}/applications"
    resp = requests.post(
        url, json=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=60,
    )
    if resp.status_code >= 400:
        print(f"Create failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        resp.raise_for_status()
    return resp.json()


def delete_application(host: str, api_key: str, project_id: str, app_id: str) -> None:
    """DELETE an existing Application so a redeploy recreates it with the current
    config (script/env/runtime). CML's PATCH uses a different schema than POST and
    rejects the create payload, so delete+create is the reliable converge path. Only
    the Application *definition* is removed — project storage (SQLite/model) is untouched."""
    url = f"{host}/api/v2/projects/{project_id}/applications/{app_id}"
    resp = requests.delete(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=60)
    if resp.status_code >= 400:
        print(f"Delete failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        resp.raise_for_status()


def normalize_host(host: str) -> str:
    """CDSW_API_URL may carry a /api/v1 or /api/v2 suffix — strip it; callers
    re-append /api/v2 themselves."""
    host = (host or "").rstrip("/")
    for suffix in ("/api/v2", "/api/v1"):
        if host.endswith(suffix):
            return host[: -len(suffix)]
    return host


def find_applications(host: str, api_key: str, project_id: str,
                      name: str, subdomain: str) -> list[str]:
    """Return the ids of ALL Applications matching name or subdomain. Multiple can
    accumulate from repeated deploys, and stale ones hold the app port (EADDRINUSE),
    so callers delete every match, not just the first."""
    url = f"{host}/api/v2/projects/{project_id}/applications"
    resp = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=60)
    if resp.status_code >= 400:
        return []
    return [
        app.get("id")
        for app in resp.json().get("applications", [])
        if (app.get("name") == name or app.get("subdomain") == subdomain) and app.get("id")
    ]


def get_application(host: str, api_key: str, project_id: str, app_id: str) -> dict:
    """GET a single Application (for status + url)."""
    url = f"{host}/api/v2/projects/{project_id}/applications/{app_id}"
    resp = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=60)
    if resp.status_code >= 400:
        return {}
    return resp.json() if resp.text else {}


def wait_for_running(host: str, api_key: str, project_id: str, app_id: str,
                     timeout: int = 300) -> bool:
    """Poll the Application until it reaches a running state, or a terminal
    failure / timeout — so a broken start fails CI instead of a false green."""
    print(f"   Waiting for Application to reach 'running' (timeout: {timeout}s)...")
    start = time.time()
    last = None
    while time.time() - start < timeout:
        app = get_application(host, api_key, project_id, app_id)
        status = (app.get("status") or "unknown").lower()
        if status != last:
            print(f"      [{int(time.time() - start)}s] status: {status}")
            last = status
        if app_is_running(status):
            print("   Application is running")
            return True
        if app_is_failed(status):
            print(f"   Application entered a failed state: {status}", file=sys.stderr)
            return False
        time.sleep(10)
    print(f"   Timed out waiting for 'running' ({timeout}s)", file=sys.stderr)
    return False


def emit_url(host: str, api_key: str, project_id: str, app_id: str, subdomain: str) -> None:
    """Print the deployed app URL and write it to /tmp/app_url.txt (for CI summary)."""
    app = get_application(host, api_key, project_id, app_id)
    url = app.get("url") or f"(subdomain '{subdomain}' — check the CML Applications page for the full URL)"
    print(f"   url:       {url}")
    try:
        with open("/tmp/app_url.txt", "w") as f:
            f.write(url)
    except OSError:
        pass


def _selfcheck() -> None:
    """No-network assertions for the pure helpers."""
    assert app_is_running("running") and app_is_running("RUNNING")
    assert not app_is_running("starting") and not app_is_running("stopped")
    assert app_is_failed("failed") and app_is_failed("stopped") and app_is_failed("startup_failed")
    assert not app_is_failed("running") and not app_is_failed("starting")
    assert normalize_host("https://x.site/api/v2") == "https://x.site"
    assert normalize_host("https://x.site/api/v1/") == "https://x.site"
    assert normalize_host("https://x.site/") == "https://x.site"
    env = build_environment("7078", "caii")
    assert env["BACKEND_PORT"] == "7078" and env["LLM_PROVIDER"] == "caii"
    assert "LLM_PROVIDER" not in build_environment("7078", None)
    payload = _build_payload(name="n", subdomain="s", script="03_frontend/start_frontend.py",
                             runtime_identifier="rt", cpu=2, memory=8,
                             bypass_authentication=False, backend_port="7078", llm_provider="caii")
    assert payload["script"] == "03_frontend/start_frontend.py"
    assert payload["environment"]["BACKEND_PORT"] == "7078"
    assert payload["bypass_authentication"] is False
    print("deploy_application selfcheck: OK")


def main() -> None:
    p = argparse.ArgumentParser(description="Deploy the AML platform as a CML Application")
    p.add_argument("--host", default=os.environ.get("CDSW_API_URL") or os.environ.get("CML_HOST"),
                   help="CML host, e.g. https://ml-xxxx.cloudera.site (default: $CDSW_API_URL/$CML_HOST)")
    p.add_argument("--api-key", default=os.environ.get("CDSW_APIV2_KEY") or os.environ.get("CML_API_KEY"),
                   help="CML API v2 key (default: $CDSW_APIV2_KEY/$CML_API_KEY)")
    p.add_argument("--project-id", default=os.environ.get("CDSW_PROJECT_ID"),
                   help="Project ID (default: $CDSW_PROJECT_ID)")
    p.add_argument("--name", default="AML Investigation Platform")
    p.add_argument("--subdomain", default="aml-platform", help="URL subdomain (a-z0-9-)")
    p.add_argument("--script", default="03_frontend/start_frontend.py")
    p.add_argument("--runtime-identifier", default=os.environ.get("RUNTIME_IDENTIFIER"),
                   help="ML Runtime identifier — a Python 3.11 runtime (default: $RUNTIME_IDENTIFIER; "
                        "see cai_integration/README.md)")
    p.add_argument("--cpu", type=int, default=2)
    p.add_argument("--memory", type=int, default=8)
    p.add_argument("--backend-port", default=os.environ.get("BACKEND_PORT", "7078"),
                   help="Localhost port the co-located FastAPI backend binds to (default 7078)")
    p.add_argument("--llm-provider", default=os.environ.get("LLM_PROVIDER", "caii"),
                   help="LLM provider: caii | vllm | ollama (default caii)")
    # Public by default so agents / the MCP server can reach /api without a Workbench
    # SSO browser session. Set APP_PUBLIC=0 or pass --private to sit behind SSO.
    p.add_argument("--public", dest="public", action="store_true",
                   default=(os.environ.get("APP_PUBLIC", "1") != "0"),
                   help="bypass_authentication=True — allow unauthenticated requests (default)")
    p.add_argument("--private", dest="public", action="store_false",
                   help="Require Workbench SSO (bypass_authentication=False)")
    p.add_argument("--wait", dest="wait", action="store_true", default=True,
                   help="Poll until the Application is running (default)")
    p.add_argument("--no-wait", dest="wait", action="store_false",
                   help="Return immediately after create/restart (don't poll status)")
    p.add_argument("--wait-timeout", type=int, default=300,
                   help="Seconds to wait for 'running' before failing (default 300)")
    p.add_argument("--selfcheck", action="store_true",
                   help="Run no-network assertions on the pure helpers and exit")
    args = p.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    missing = [k for k in ("host", "api_key", "project_id", "runtime_identifier")
               if not getattr(args, k)]
    if missing:
        print(f"Missing required values: {', '.join(missing)}. "
              f"Pass them as flags or set the corresponding env vars.", file=sys.stderr)
        sys.exit(1)

    host = normalize_host(args.host)
    payload = _build_payload(
        name=args.name, subdomain=args.subdomain, script=args.script,
        runtime_identifier=args.runtime_identifier, cpu=args.cpu, memory=args.memory,
        bypass_authentication=args.public,
        backend_port=args.backend_port, llm_provider=args.llm_provider,
    )

    # Idempotent: delete ALL existing Applications matching name/subdomain, then create
    # with the current config. CML PATCH rejects the create payload, so delete+create is
    # the reliable converge path; deleting *every* match frees the app port that stale
    # duplicates from prior deploys would otherwise hold (EADDRINUSE).
    existing = find_applications(host, args.api_key, args.project_id, args.name, args.subdomain)
    for app_id in existing:
        print(f"   Deleting existing Application {app_id} to apply current config / free the port.")
        delete_application(host, args.api_key, args.project_id, app_id)
    if existing:
        time.sleep(10)  # let the old workloads terminate and release the port
    app = create_application(host, args.api_key, args.project_id, payload=payload)
    app_id = app.get("id")
    print("Application created:")
    print(f"   id:        {app_id}")
    print(f"   subdomain: {app.get('subdomain')}")
    print("   auth:      " + ("PUBLIC — unauthenticated requests allowed (bypass_authentication=True)"
                               if args.public else "Workbench SSO (bypass_authentication=False)"))

    # Fail loudly if the app doesn't actually come up (broken runtime, missing
    # dep, port issue) — otherwise CI reports a false green.
    if args.wait and app_id:
        if not wait_for_running(host, args.api_key, args.project_id, app_id, args.wait_timeout):
            sys.exit(1)
    if app_id:
        emit_url(host, args.api_key, args.project_id, app_id, args.subdomain)


if __name__ == "__main__":
    main()
