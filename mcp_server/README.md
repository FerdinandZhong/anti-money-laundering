# aml-mcp

MCP (stdio) server for the AML Investigation Platform. A thin HTTP client over the
platform's customer-centric API (`/api/customers/{id}/...`) — it holds no data
logic and no DB access, so it runs anywhere `uvx` does (Cloudera AI Studio, Claude
Code, …) and talks to the **hosted** API over HTTP.

> **SDK compatibility:** `aml-mcp` 0.2.0 uses the MCP Python SDK v2
> `MCPServer` API and declares `mcp>=2,<3`. Do not pin it to MCP 1.x.

## Tools

| Tool | Reads/Writes |
|------|--------------|
| `is_customer_suspicious(customer_id)` | read |
| `list_high_score_transactions(customer_id, limit=20)` | read |
| `get_case_status(customer_id)` | read |
| `get_customer_network_graph(customer_id)` | read |
| `trigger_investigation(customer_id)` | **write** (persists the analysis) — the only mutation |

## Configure (Cloudera AI Studio / any MCP client)

```json
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
```

- `AML_API_BASE_URL` (required) — base URL of the deployed API, ending in `/api`.
- `AML_API_TOKEN` (optional) — sent as `Authorization: Bearer <token>`.

Swagger for the API is at `${AML_API_BASE_URL}/docs`.

## Local dev

```bash
cd mcp_server
uv run --with mcp --with httpx aml-mcp        # or: pip install -e . && aml-mcp
python -m pytest test_server.py -q            # HTTP layer mocked, no live API
```
