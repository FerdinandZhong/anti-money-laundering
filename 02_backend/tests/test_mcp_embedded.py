"""Embedded stdio MCP server registry tests.

SDK transport never actually spawns uvx — we patch `_run` or test pure logic.
DB tests use the `tmp_db_path` fixture (see conftest) so they never touch real data.
"""
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import mcp_client


def _seed_embedded(conn, name, params, enabled=1):
    conn.execute(
        "INSERT INTO tool_config (kind, name, transport, params, enabled) "
        "VALUES ('embedded', ?, 'stdio', ?, ?)",
        (name, json.dumps(params), enabled))
    conn.commit()


def test_embedded_params_none_when_unconfigured(tmp_db_path):
    from common.db import get_connection
    get_connection().close()
    assert mcp_client.embedded_params("iceberg-mcp") is None


def test_embedded_params_none_when_required_missing(tmp_db_path):
    from common.db import get_connection
    conn = get_connection()
    _seed_embedded(conn, "iceberg-mcp", {"impala_host": "h"})  # missing user/password/database
    conn.close()
    assert mcp_client.embedded_params("iceberg-mcp") is None


def test_embedded_params_returns_complete_config(tmp_db_path):
    from common.db import get_connection
    conn = get_connection()
    _seed_embedded(conn, "iceberg-mcp", {
        "impala_host": "h", "impala_port": "443", "impala_user": "u",
        "impala_password": "p", "impala_database": "db"})
    conn.close()
    p = mcp_client.embedded_params("iceberg-mcp")
    assert p and p["impala_host"] == "h"


def test_embedded_params_none_when_disabled(tmp_db_path):
    from common.db import get_connection
    conn = get_connection()
    _seed_embedded(conn, "workbench-mcp",
                   {"host": "https://ml-x", "api_key": "k", "project_id": "pid"},
                   enabled=0)
    conn.close()
    assert mcp_client.embedded_params("workbench-mcp") is None


def test_call_embedded_unconfigured_returns_error(tmp_db_path):
    from common.db import get_connection
    get_connection().close()
    res = mcp_client.call_embedded("iceberg-mcp", "execute_query", {"query": "SELECT 1"})
    assert isinstance(res, dict) and "error" in res


def test_registry_launch_spec():
    ice = mcp_client.EMBEDDED_SERVERS["iceberg-mcp"]
    assert ice["env_map"]["impala_host"] == "IMPALA_HOST"
    assert "impala_password" in ice["required"]
    wb = mcp_client.EMBEDDED_SERVERS["workbench-mcp"]
    assert wb["env_map"]["api_key"] == "CAI_WORKBENCH_API_KEY"
    # workbench needs the --with cmlapi tarball derived from host
    extra = wb["extra_args"]({"host": "https://ml-x.site"})
    assert "--with" in extra and "https://ml-x.site/api/v2/python.tar.gz" in extra
