#!/usr/bin/env python3
"""CML Job: Launch Application — final job in the chain
(git_sync -> install -> generate -> features -> train -> launch).

Runs INSIDE CML (as a Job) so the whole deploy is triggerable from the CML Jobs UI:
run "Git Repository Sync" and CML cascades the chain down to this. Creates (or
replaces) the CML Application pointing at 03_frontend/start_frontend.py (which serves
the React build + co-located FastAPI backend on $CDSW_APP_PORT) and waits for it to run.

Credentials are auto-injected by CML (CDSW_APIV2_KEY, CDSW_API_URL/CDSW_DOMAIN,
CDSW_PROJECT_ID). App config (RUNTIME_IDENTIFIER, APP_SUBDOMAIN, LLM_PROVIDER,
BACKEND_PORT, ...) is baked into this job's environment by create_jobs.py. The CAII
endpoint resolves from CDSW_DOMAIN inside the app, so no LLM endpoint is passed here.

CML runs job scripts in an IPython engine: never sys.exit (treated as failure) — raise.
"""
import os
import sys

# The job runs from the repo root (/home/cdsw); make cai_integration importable.
sys.path.insert(0, os.path.join(os.getcwd(), "cai_integration"))
sys.path.insert(0, "cai_integration")

import time  # noqa: E402

from deploy_application import (  # noqa: E402
    _build_payload, normalize_host, find_applications, delete_application,
    create_application, wait_for_running, emit_url, get_application, app_is_failed,
)


def main() -> None:
    host = normalize_host(
        os.environ.get("CDSW_API_URL") or os.environ.get("CDSW_DOMAIN") or os.environ.get("CML_HOST") or ""
    )
    api_key = os.environ.get("CDSW_APIV2_KEY") or os.environ.get("CML_API_KEY")
    project_id = os.environ.get("CDSW_PROJECT_ID")
    runtime = os.environ.get("RUNTIME_IDENTIFIER")
    name = os.environ.get("APP_NAME", "AML Investigation Platform")
    subdomain = os.environ.get("APP_SUBDOMAIN", "aml-platform")

    missing = [k for k, v in {
        "CDSW_API_URL/CDSW_DOMAIN": host, "CDSW_APIV2_KEY": api_key,
        "CDSW_PROJECT_ID": project_id, "RUNTIME_IDENTIFIER": runtime,
    }.items() if not v]
    if missing:
        raise RuntimeError(f"launch_app: missing required values: {', '.join(missing)}")

    payload = _build_payload(
        name=name, subdomain=subdomain, script="03_frontend/start_frontend.py",
        runtime_identifier=runtime, cpu=2, memory=8,
        # Public by default (APP_PUBLIC=0 re-enables SSO) so the MCP server / agents
        # can reach /api without a Workbench SSO browser session.
        bypass_authentication=(os.environ.get("APP_PUBLIC", "1") != "0"),
        backend_port=os.environ.get("BACKEND_PORT", "7078"),
        llm_provider=os.environ.get("LLM_PROVIDER", "caii"),
    )

    # Delete ALL matching Applications, then create with the current config (CML PATCH
    # rejects the create payload; deleting every match frees the app port — EADDRINUSE).
    existing = find_applications(host, api_key, project_id, name, subdomain)
    for app_id in existing:
        print(f"Deleting existing Application {app_id} to apply current config / free the port.")
        delete_application(host, api_key, project_id, app_id)
    if existing:
        time.sleep(10)  # let the old workloads terminate and release the app port
    app = create_application(host, api_key, project_id, payload=payload)
    app_id = app.get("id")
    print(f"Application created: {app_id} (subdomain: {subdomain})")

    if not wait_for_running(host, api_key, project_id, app_id, int(os.environ.get("APP_WAIT_TIMEOUT", "300"))):
        raise RuntimeError("Application did not reach 'running' — check the Application logs.")
    emit_url(host, api_key, project_id, app_id, subdomain)
    print("Application is live — dashboard is ready with the scored alert queue.")

    # Keep this job in the 'Running' state while the app is up instead of marking
    # it finished: the pipeline then visibly ends in a live, ready dashboard rather
    # than a "completed" chain with the app as a side effect. Set APP_KEEP_RUNNING=0
    # to exit as soon as the app is running (e.g. for CI / trigger_jobs).
    if os.environ.get("APP_KEEP_RUNNING", "1") == "0":
        print("Launch Application complete (APP_KEEP_RUNNING=0).")
        return
    interval = int(os.environ.get("APP_MONITOR_INTERVAL", "60"))
    print(f"Holding this job open and monitoring the Application every {interval}s "
          "(stop the job to release it).")
    while True:
        time.sleep(interval)
        try:
            status = (get_application(host, api_key, project_id, app_id).get("status") or "unknown").lower()
        except Exception as ex:  # transient API blip — keep the job alive
            print(f"   [monitor] status check failed (continuing): {ex}")
            continue
        if app_is_failed(status):
            raise RuntimeError(f"Application left the running state (status={status}) — check the Application logs.")
        print(f"   [monitor] Application status: {status}")


# CML engine: unguarded call, no sys.exit.
main()
