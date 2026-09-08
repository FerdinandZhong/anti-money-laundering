#!/usr/bin/env python3
"""
Create (or find) the CML project for the AML Investigation Platform from git.

Adapted from use_case_discovery/cai_integration/setup_project.py.
Changes: project name/description + git URL come from env.

Steps:
1. Search for an existing project by name, or create one from a git URL.
2. Set project resource defaults; wait for the git clone to complete.
3. Write the project id to /tmp/project_id.txt for the next step / CI.

Required env: CML_HOST, CML_API_KEY, and either GIT_URL or GITHUB_REPOSITORY.
Optional env: PROJECT_NAME (default "AML Investigation Platform").
"""

import os
import sys
import time
import requests
from typing import Optional


class ProjectSetup:

    def __init__(self):
        self.cml_host = os.environ.get("CML_HOST")
        self.api_key = os.environ.get("CML_API_KEY")
        self.git_url = os.environ.get("GIT_URL")
        github_repo = os.environ.get("GITHUB_REPOSITORY")
        if not self.git_url and github_repo:
            self.git_url = f"https://github.com/{github_repo}"
        self.project_name = os.environ.get("PROJECT_NAME", "AML Investigation Platform")

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

    def search_projects(self, project_name: str) -> Optional[str]:
        print(f"Searching for project: {project_name}")
        search_filter = f'{{"name":"{project_name}"}}'
        result = self.make_request(
            "GET", "projects", params={"search_filter": search_filter, "page_size": 50}
        )
        if result:
            projects = result.get("projects", [])
            if projects:
                project_id = projects[0].get("id")
                print(f"Found existing project: {project_id}")
                return project_id
        print("No existing project found")
        return None

    def create_project_with_git(self, project_name: str, git_url: str) -> Optional[str]:
        print(f"Creating project: {project_name}  (git: {git_url})")
        project_data = {
            "name": project_name,
            "description": "AML Investigation Platform — multi-agent investigation "
                           "workbench, XGBoost risk model, dual dashboards, and a "
                           "governed retrain/canary/rollback lifecycle.",
            "template": "git",
            "git_url": git_url,
            "project_visibility": "private",
        }
        result = self.make_request("POST", "projects", data=project_data)
        if result:
            project_id = result.get("id")
            print(f"Project created: {project_id}")
            return project_id
        return None

    def configure_project_resources(self, project_id: str) -> bool:
        print("Configuring project resource defaults...")
        result = self.make_request(
            "PATCH", f"projects/{project_id}",
            data={
                "shared_memory_limit": 10000,
                "ephemeral_storage_request_mb": 0,
                "ephemeral_storage_limit_mb": 307200,
            },
        )
        if result is not None:
            print("Project resource defaults configured")
            return True
        print("Could not configure project resource defaults (non-fatal)")
        return False

    def get_or_create_project(self) -> Optional[str]:
        print("\n" + "=" * 70)
        print("Step 1: Get or Create CML Project")
        print("=" * 70)

        project_id = self.search_projects(self.project_name)
        if project_id:
            return project_id

        if not self.git_url:
            print("No existing project and no git URL provided")
            print("   Set GIT_URL (or GITHUB_REPOSITORY) to create the project from git")
            return None

        return self.create_project_with_git(self.project_name, self.git_url)

    def wait_for_git_clone(self, project_id: str, timeout: int = 900) -> bool:
        print(f"\nWaiting for git repository to be cloned (timeout: {timeout}s)...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            elapsed = int(time.time() - start_time)
            result = self.make_request("GET", f"projects/{project_id}")
            if result:
                creation_status = result.get("creation_status", "unknown")
                print(f"   [{elapsed}s] Project status: {creation_status}")
                if creation_status in ["unknown", "creating"]:
                    pass
                elif creation_status == "error":
                    print("Error during git clone")
                    print(f"   Error: {result.get('error_message', 'No error message')}")
                    return False
                elif creation_status in ["success", "ready", "running"]:
                    print("Clone complete; waiting 30s for files to land on disk...")
                    time.sleep(30)
                    return True
            remaining = timeout - elapsed
            if remaining > 0:
                time.sleep(min(10, remaining))

        print(f"Timeout waiting for git clone ({int(time.time() - start_time)}s / {timeout}s)")
        return False

    def run(self) -> bool:
        print("=" * 70)
        print("CML Project Setup — AML Investigation Platform")
        print("=" * 70)

        project_id = self.get_or_create_project()
        if not project_id:
            print("Failed to get/create project")
            return False

        self.configure_project_resources(project_id)

        # Poll creation_status: fast for an existing (already-populated) project,
        # and waits out the async clone for a freshly-created one.
        if not self.wait_for_git_clone(project_id):
            print("Git clone did not complete")
            return False

        print("=" * 70)
        print(f"Project Setup Complete!  Project ID: {project_id}")
        print("=" * 70)

        with open("/tmp/project_id.txt", "w") as f:
            f.write(project_id)
        return True


def main():
    try:
        setup = ProjectSetup()
        sys.exit(0 if setup.run() else 1)
    except KeyboardInterrupt:
        print("\nSetup cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
