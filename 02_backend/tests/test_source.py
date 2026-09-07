import pytest


@pytest.fixture(autouse=True)
def _reset_source_module():
    """source.py caches backend/csv/count state at module scope. Reset it around
    every test and force backend=csv so tests stay fast + offline (no real
    Impala TCP attempt)."""
    import common.source as source

    source._backend = None
    source._impala_conn = None
    source._csv_cache = {}
    source._suspicious_count = None
    source._total_count = None
    yield
    source._backend = None
    source._impala_conn = None
    source._csv_cache = {}
    source._suspicious_count = None
    source._total_count = None


@pytest.fixture
def force_csv_backend(monkeypatch):
    import common.source as source

    monkeypatch.setattr(source, "_source_cfg", lambda: {"backend": "csv", "csv_dir": "data/raw"})
    return source


def test_backend_resolves_to_csv_when_forced(force_csv_backend):
    assert force_csv_backend.backend() == "csv"


def test_count_transactions_matches_csv_row_count(force_csv_backend):
    import pandas as pd
    import os

    csv_path = os.path.join(force_csv_backend.PROJECT_ROOT, "data/raw/transactions.csv")
    expected = len(pd.read_csv(csv_path, low_memory=False))
    assert force_csv_backend.count_transactions() == expected


def test_count_suspicious_matches_csv_flagged_rows(force_csv_backend):
    import pandas as pd
    import os

    csv_path = os.path.join(force_csv_backend.PROJECT_ROOT, "data/raw/transactions.csv")
    tx = pd.read_csv(csv_path, low_memory=False)
    expected = int((tx["is_suspicious"] == 1).sum())
    assert force_csv_backend.count_suspicious() == expected


def test_count_suspicious_is_cached_per_process(force_csv_backend, monkeypatch):
    """Second call must not re-read the CSV (cached in _suspicious_count)."""
    first = force_csv_backend.count_suspicious()
    # sabotage the CSV loader; a cache-miss would now raise
    monkeypatch.setattr(force_csv_backend, "_csv", lambda table: (_ for _ in ()).throw(RuntimeError("should not re-read")))
    assert force_csv_backend.count_suspicious() == first


def test_csv_missing_file_raises_helpful_error(force_csv_backend, monkeypatch, tmp_path):
    monkeypatch.setattr(force_csv_backend, "_source_cfg", lambda: {"backend": "csv", "csv_dir": str(tmp_path)})
    with pytest.raises(RuntimeError, match="CSV source missing"):
        force_csv_backend.get_customer("CUST-DOES-NOT-EXIST")


def test_get_customer_returns_none_when_not_found(force_csv_backend):
    assert force_csv_backend.get_customer("CUST-DOES-NOT-EXIST-12345") is None


def test_backend_impala_forced_but_unreachable_raises(monkeypatch):
    import common.source as source

    monkeypatch.setattr(source, "_source_cfg", lambda: {
        "backend": "impala",
        "impala": {"host": "127.0.0.1", "port": 1, "connect_timeout": 0.2},
    })
    with pytest.raises(RuntimeError, match="unreachable"):
        source.backend()
