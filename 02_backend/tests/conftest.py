import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


@pytest.fixture
def tmp_db_path(tmp_path, monkeypatch):
    """Point get_db_path() at a fresh temp SQLite file and initialize the
    schema, so tests never touch the real dev data/aml.db.

    common/db.py does `from common.config import get_db_path`, a separate
    name binding — patching common.config's copy alone leaves db.py's own
    reference (and thus every prior test's temp path) in place, so both
    modules' bindings must be patched.
    """
    import common.config as config_mod
    import common.db as db_mod

    path = str(tmp_path / "test.db")
    monkeypatch.setattr(config_mod, "get_db_path", lambda: path)
    monkeypatch.setattr(db_mod, "get_db_path", lambda: path)

    db_mod.init_db()
    return path


@pytest.fixture
def db_conn(tmp_db_path):
    from common.db import get_connection
    conn = get_connection()
    yield conn
    conn.close()
