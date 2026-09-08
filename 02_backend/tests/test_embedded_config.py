import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_tool_config_has_params_column(tmp_db_path):
    from common.db import get_connection
    conn = get_connection()
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(tool_config)")]
    assert "params" in cols
    conn.execute(
        "INSERT INTO tool_config (kind, name, transport, params) "
        "VALUES ('embedded', 'iceberg-mcp', 'stdio', ?)",
        (json.dumps({"impala_host": "h", "impala_user": "u"}),))
    conn.commit()
    row = conn.execute("SELECT params FROM tool_config WHERE name='iceberg-mcp'").fetchone()
    assert json.loads(row["params"])["impala_host"] == "h"
    conn.close()


def test_params_column_migration_is_idempotent(tmp_db_path):
    from common.db import get_connection
    get_connection().close()
    get_connection().close()  # second connect must not raise
