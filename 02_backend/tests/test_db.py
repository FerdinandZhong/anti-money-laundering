import pytest


def test_get_connection_self_heals_missing_columns_and_tables(tmp_db_path):
    """A DB created before transaction_scores/labels/llm_models/cases-cols existed
    should self-heal on first get_connection() without raising."""
    import sqlite3
    from common.config import get_db_path
    from common.db import get_connection

    # simulate an "old" DB: drop the self-heal tables/columns
    conn = sqlite3.connect(get_db_path())
    conn.execute("DROP TABLE IF EXISTS transaction_labels")
    conn.execute("DROP TABLE IF EXISTS llm_models")
    conn.commit()
    conn.close()

    healed = get_connection()
    # tables recreated
    healed.execute("SELECT 1 FROM transaction_labels").fetchall()
    healed.execute("SELECT 1 FROM llm_models").fetchall()
    # cases columns present (added via ALTER TABLE, ignored if already there)
    row = healed.execute("SELECT analysis, analyzed_at, disposition FROM cases LIMIT 0").fetchall()
    assert row == []
    healed.close()


def test_get_connection_check_same_thread_false(tmp_db_path):
    """FastAPI serves sync endpoints from a threadpool; a connection must be
    usable from a thread other than the one that created it."""
    import threading
    from common.db import get_connection

    conn = get_connection()
    results = {}

    def worker():
        try:
            conn.execute("SELECT 1").fetchone()
            results["ok"] = True
        except Exception as e:  # noqa: BLE001
            results["ok"] = False
            results["error"] = str(e)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    conn.close()

    assert results.get("ok") is True, results.get("error")


def test_get_connection_missing_file_raises(monkeypatch):
    import common.db as db_mod

    # common/db.py imports get_db_path by value (`from common.config import
    # get_db_path`), so the binding to patch lives on db_mod, not config.
    monkeypatch.setattr(db_mod, "get_db_path", lambda: "/nonexistent/path/does-not-exist.db")
    with pytest.raises(RuntimeError):
        db_mod.get_connection()
