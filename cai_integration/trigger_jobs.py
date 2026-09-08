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

    def wait_for_job_completion(self, project_id, job_id, run_id, timeout) -> bool:
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

        # Walk the rest of the chain. Each child's run appears within seconds of
        # its parent succeeding (which we just confirmed), so a modest new-run
        # timeout suffices; completion uses the job's own configured timeout.
        for job in chain[1:]:
            job_id = self.find_job_id(project_id, job["name"])
            if not job_id:
                print(f"Warning: '{job['name']}' job not found — skipping.")
                continue
            new_run_timeout = max(300, int(job.get("timeout", 600)))
            child_run = self.wait_for_new_run(
                project_id, job_id, job["name"], trigger_epoch, new_run_timeout
            )
            if not child_run:
                return False
            if not self.wait_for_job_completion(project_id, job_id, child_run, job.get("timeout", 600)):
                print(f"{job['name']} failed")
                return False

        print("=" * 70)
        print("Pipeline complete. Launch the Application (once):")
        print("   python cai_integration/deploy_application.py --runtime-identifier <python-runtime> ...")
        print("=" * 70)
        return True


def main():
    parser = argparse.ArgumentParser(
        description="Trigger the git_sync root job; CML runs the rest of the chain"
    )
    parser.add_argument("--project-id", required=True, help="CML project ID")
    args = parser.parse_args()

    try:
        trigger = JobTrigger()
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
