"""MCP (stdio) server for the AML Investigation Platform.

A thin HTTP client over the platform's customer-centric API — it holds NO data
logic and NO DB access. Configure it inside Cloudera AI Studio (or any agent
framework) with the deployed API's base URL, e.g.:

    {
      "mcpServers": {
        "aml-investigation": {
          "command": "uvx",
          "args": ["--from",
                   "git+https://github.com/FerdinandZhong/anti-money-laundering#subdirectory=mcp_server",
                   "aml-mcp"],
          "env": {
            "AML_API_BASE_URL": "https://aml-platform.<domain>/api",
            "AML_API_TOKEN": "<optional bearer token>"
          }
        }
      }
    }

READ-ONLY CONTRACT: every tool is read-only EXCEPT `trigger_investigation`, which
runs the multi-agent analysis and persists it to the case (the API's only mutation
on this surface). Disposition / labels / retrain / config are not exposed.
"""
import os

import httpx
from mcp.server import MCPServer

# MCP Python SDK v2 renamed FastMCP to MCPServer.  Keep the server name stable:
# Agent Studio and other MCP hosts show this during their initialization handshake.
mcp = MCPServer("aml-investigation")

_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)


def _base_url() -> str:
    url = os.environ.get("AML_API_BASE_URL", "").rstrip("/")
    if not url:
        raise RuntimeError("AML_API_BASE_URL is not set (e.g. https://aml-platform.<domain>/api)")
    return url


def _headers() -> dict:
    token = os.environ.get("AML_API_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _get(path: str, params: dict | None = None) -> dict:
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as c:
        r = c.get(f"{_base_url()}{path}", params=params, headers=_headers())
        r.raise_for_status()
        return r.json()


def _post(path: str) -> dict:
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as c:
        r = c.post(f"{_base_url()}{path}", headers=_headers())
        r.raise_for_status()
        return r.json()


@mcp.tool()
def is_customer_suspicious(customer_id: str) -> dict:
    """Is this customer suspicious? A customer is suspicious if they have any alert
    in an active status (OPEN, PROPOSED, PENDING). Returns the alerts with risk
    scores/bands and the highest risk score. Read-only."""
    return _get(f"/customers/{customer_id}/suspicious")


@mcp.tool()
def list_high_score_transactions(customer_id: str, limit: int = 20) -> dict:
    """List the customer's transactions ranked by model risk score (highest first;
    unscored last), each with analyst label and derived typology flags. Read-only."""
    return _get(f"/customers/{customer_id}/transactions", params={"limit": limit})


@mcp.tool()
def get_case_status(customer_id: str) -> dict:
    """Current analyst-processing status for the customer's case: state, disposition,
    whether an AI analysis exists, and any analyst annotations. Read-only — does not
    create a case if none exists yet."""
    return _get(f"/customers/{customer_id}/case-status")


@mcp.tool()
def get_customer_network_graph(customer_id: str) -> dict:
    """Fund-flow + shared-device network graph around the customer's primary account:
    {nodes, edges}. Read-only."""
    return _get(f"/customers/{customer_id}/network")


@mcp.tool()
def trigger_investigation(customer_id: str) -> dict:
    """Run the multi-agent AI investigation for the customer's case and return the
    analysis. THE ONLY MUTATING TOOL: the platform persists the analysis narrative
    to the case. Returns {case_id, analysis, verdicts, worker_findings}. May take
    a while (runs several LLM workers)."""
    return _post(f"/customers/{customer_id}/investigate")


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
