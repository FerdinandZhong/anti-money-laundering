#!/usr/bin/env python3
"""
Trigger the root job (git_sync) and monitor the whole chain to completion.

CML's parent-child chaining runs the rest autonomously; this script triggers
git_sync and then waits, in dependency order, for each job CML auto-triggers:
    git_sync -> install -> generate -> features -> train

The chain and its order are read from cai_integration/jobs_config.yaml, so adding
or reordering jobs there needs no change here. After `train`, launch the
Application once with cai_integration/deploy_application.py (or via the CML UI).

Usage:
    python cai_integration/trigger_jobs.py --project-id <project_id>

Required env: CML_HOST, CML_API_KEY
"""

import argparse
import os
import sys
import time
import yaml
import requests
from pathlib import Path
from typing import Optional, List, Dict, Any

# Wait this long for CML to auto-trigger a child before triggering it ourselves.
AUTO_TRIGGER_WINDOW = 120


class JobTrigger:

    def __init__(self):
        self.cml_host = os.environ.get("CML_HOST")
        self.api_key = os.environ.get("CML_API_KEY")

        if not all([self.cml_host, self.api_key]):
            print("Error: Missing required environment variables")
            print("   Required: CML_HOST, CML_API_KEY")
            sys.exit(1)

        self.api_url = f"{self.cml_host.rstrip('/')}/api/v2"
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key.strip()}",
        }

    def make_request(self, method, endpoint, data=None, params=None) -> Optional[dict]:
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        try:
            response = requests.request(
                method=method, url=url, headers=self.headers,
                json=data, params=params, timeout=30,
            )
            if 200 <= response.status_code < 300:
                return response.json() if response.text else {}
            print(f"API Error ({response.status_code}): {response.text[:200]}")
            return None
        except Exception as e:
            print(f"Request error: {e}")
            return None

    def load_chain(self) -> List[Dict[str, Any]]:
        """Return jobs ordered by the parent chain (root first). Assumes the
        linear chain in jobs_config.yaml (one parent per job)."""
        config_path = Path(__file__).parent / "jobs_config.yaml"
        with open(config_path) as f:
            jobs = (yaml.safe_load(f) or {}).get("jobs", {})
        # Order by walking parent_job_key from the root (parent None).
        by_parent: Dict[Optional[str], str] = {}
        for key, cfg in jobs.items():
            by_parent[cfg.get("parent_job_key")] = key
        ordered: List[Dict[str, Any]] = []
        parent_key = None
        seen = set()
        while parent_key in by_parent and by_parent[parent_key] not in seen:
            key = by_parent[parent_key]
            seen.add(key)
            ordered.append({"key": key, **jobs[key]})
            parent_key = key
        if len(ordered) != len(jobs):
            # Not a clean linear chain — fall back to yaml order so nothing is dropped.
            print("WARNING: jobs are not a single linear chain; using yaml order.")
            return [{"key": k, **v} for k, v in jobs.items()]
        return ordered

    def find_job_id(self, project_id: str, job_name: str) -> Optional[str]:
        result = self.make_request("GET", f"projects/{project_id}/jobs")
        if result:
            for job in result.get("jobs", []):
                if job.get("name") == job_name:
                    return job.get("id")
        return None

    def trigger_job(self, project_id: str, job_id: str) -> Optional[str]:
        result = self.make_request("POST", f"projects/{project_id}/jobs/{job_id}/runs")
        return result.get("id") if result else None

    def wait_for_new_run(self, project_id, job_id, job_name, trigger_epoch, timeout) -> Optional[str]:
        """Poll until a run for job_id appears that was created after trigger_epoch
        (the run CML auto-triggered). Returns its run_id, or None on timeout.

        Filters by created_at rather than list order: CML does not honor a sort
        param, so a prior successful run must not be mistaken for the new one.
        """
        print(f"   Waiting for CML to auto-trigger: {job_name} ...")
        start = time.time()
        while time.time() - start < timeout:
            result = self.make_request(
                "GET", f"projects/{project_id}/jobs/{job_id}/runs", params={"page_size": 5}
            )
            for run in (result or {}).get("runs", []):
                run_id = run.get("id")
                created_at = run.get("created_at", "")
                if not run_id or not created_at:
                    continue
                try:
                    from datetime import datetime, timezone
                    ts = created_at.rstrip("Z")
                    fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in ts else "%Y-%m-%dT%H:%M:%S"
                    dt = datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
                    if dt.timestamp() > trigger_epoch:
                        print(f"   [{int(time.time() - start)}s] New run detected: {run_id}")
                        return run_id
                except Exception:
                    # Unparseable timestamp: optimistically accept the most-recent run.
                    return run_id
            time.sleep(15)
        print(f"   Timed out waiting for {job_name} to be auto-triggered ({timeout}s)")
        return None

    def wait_for_job_completion(self, project_id, job_id, run_id, timeout,
                                succeed_on_running: bool = False) -> bool:
        print(f"   Waiting for job to complete (timeout: {timeout}s)...")
        start = time.time()
        last_status = None

        while time.time() - start < timeout:
            result = self.make_request(
                "GET", f"projects/{project_id}/jobs/{job_id}/runs/{run_id}"
            )
            if result:
                status = result.get("status", "unknown").lower()
                if status != last_status:
                    print(f"      [{int(time.time() - start)}s] Status: {status}")
                    last_status = status
                if status in ("succeeded", "success", "engine_succeeded"):
                    print("   Job completed successfully")
                    return True
                # The launch job is keep-alive (APP_KEEP_RUNNING=1) — it never
                # 'succeeds', it stays running while the app is live. Once it's
                # running the chain is done from CI's perspective.
                if succeed_on_running and status in ("running", "engine_running"):
                    print("   Launch job is running (keep-alive) — app is live; chain complete.")
                    return True
                if status in ("failed", "error", "engine_failed", "killed", "stopped", "timedout"):
                    print(f"   Job failed with status: {status}")
                    return False
            time.sleep(10)

        print(f"   Job timeout ({int(time.time() - start)}s / {timeout}s)")
        return False

    def run(self, project_id: str) -> bool:
        chain = self.load_chain()
        if not chain:
            print("No jobs configured in jobs_config.yaml")
            return False

        root = chain[0]
        print("=" * 70)
        print(f"Triggering root job: {root['name']}")
        print("(CML auto-triggers each child as its parent succeeds)")
        print(f"Chain: {' -> '.join(j['name'] for j in chain)}")
        print("=" * 70)

        root_id = self.find_job_id(project_id, root["name"])
        if not root_id:
            print(f"Job not found: {root['name']}")
            print("   Run the create-jobs step first.")
            return False
        print(f"   Job ID: {root_id}")

        run_id = self.trigger_job(project_id, root_id)
        if not run_id:
            print("   Failed to trigger job")
            return False
        # Epoch BEFORE the chain runs, so every auto-triggered downstream run
        # (created after its parent succeeds) is always newer than this stamp.
        trigger_epoch = time.time()
        print(f"   Run ID: {run_id}\n")

        if not self.wait_for_job_completion(project_id, root_id, run_id, root.get("timeout", 300)):
            print(f"{root['name']} failed")
            return False

        # Walk the rest of the chain. CML *should* auto-trigger each child when its
        # parent succeeds, but that dependency (and its timestamp detection) isn't
        # reliable — the symptom is a long "waiting to be auto-triggered" hang. So for
        # each child: briefly look for an auto-triggered run; if none appears within
        # AUTO_TRIGGER_WINDOW, trigger it explicitly. Completion uses the job's timeout.
        for job in chain[1:]:
            # The launch job is keep-alive — it stays 'running', never 'succeeded'.
            keep_alive = str(job.get("script", "")).endswith("launch_app.py")
            if not self._await_child(project_id, job, trigger_epoch, succeed_on_running=keep_alive):
                return False

        print("=" * 70)
        print(" -> ".join(j["name"] for j in chain) + " complete. Application is live.")
        print("=" * 70)
        return True

    def _await_child(self, project_id, job, trigger_epoch, succeed_on_running: bool = False) -> bool:
        """Wait for a child job to run: prefer the run CML auto-triggers; if none appears
        within AUTO_TRIGGER_WINDOW, trigger it explicitly. Then wait for completion."""
        job_id = self.find_job_id(project_id, job["name"])
        if not job_id:
            print(f"Job not found: {job['name']} — run the create-jobs step first.")
            return False
        run_id = self.wait_for_new_run(
            project_id, job_id, job["name"], trigger_epoch, AUTO_TRIGGER_WINDOW
        )
        if not run_id:
            print(f"   {job['name']} not auto-triggered within {AUTO_TRIGGER_WINDOW}s — triggering it explicitly.")
            run_id = self.trigger_job(project_id, job_id)
            if not run_id:
                print(f"   Failed to trigger {job['name']}")
                return False
            print(f"   Run ID: {run_id}")
        if not self.wait_for_job_completion(project_id, job_id, run_id, job.get("timeout", 600),
                                            succeed_on_running=succeed_on_running):
            print(f"{job['name']} failed")
            return False
        return True

    def sync_only(self, project_id: str) -> bool:
        """Run just git_sync to pull latest code into the project working dir. Used before
        create_jobs so newly-added job scripts (e.g. launch_app.py) exist when CML validates
        them. No-op on a brand-new project (no git_sync job yet) — its clone is already at HEAD."""
        chain = self.load_chain()
        root_name = chain[0]["name"] if chain else "Git Repository Sync"
        job_id = self.find_job_id(project_id, root_name)
        if not job_id:
            print(f"{root_name} not found — new project (fresh clone); nothing to pre-sync.")
            return True
        print(f"Pre-syncing project code via {root_name} ...")
        run_id = self.trigger_job(project_id, job_id)
        if not run_id:
            print("   Failed to trigger git_sync")
            return False
        return self.wait_for_job_completion(project_id, job_id, run_id, chain[0].get("timeout", 300))


def main():
    parser = argparse.ArgumentParser(
        description="Run the CML deploy chain (git_sync -> ... -> train -> launch)"
    )
    parser.add_argument("--project-id", required=True, help="CML project ID")
    parser.add_argument("--sync-only", action="store_true",
                        help="Only run git_sync (pull latest code), then exit — use before create_jobs")
    args = parser.parse_args()

    try:
        trigger = JobTrigger()
        if args.sync_only:
            sys.exit(0 if trigger.sync_only(args.project_id) else 1)
        sys.exit(0 if trigger.run(args.project_id) else 1)
    except KeyboardInterrupt:
        print("\nCancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
