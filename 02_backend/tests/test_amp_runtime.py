import builtins
import csv
import importlib.util
from pathlib import Path
import sqlite3

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_export(monkeypatch, tmp_path):
    real_import = builtins.__import__
    def reject_scientific(name, *args, **kwargs):
        if name.split('.')[0] in {'pandas', 'numpy'}:
            raise ValueError('numpy.dtype size changed')
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', reject_scientific)
    spec = importlib.util.spec_from_file_location('isolated_export', ROOT / '02_backend/scripts/export_source_csv.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'PROJECT_ROOT', str(tmp_path))
    monkeypatch.setattr(module, 'get_config', lambda: {'source': {'csv_dir': 'raw'}})
    monkeypatch.setattr(module, 'get_db_path', lambda: str(tmp_path / 'source.db'))
    with sqlite3.connect(tmp_path / 'source.db') as conn:
        for table in module.SOURCE_TABLES:
            conn.execute(f'CREATE TABLE {table} (id TEXT, note TEXT, amount REAL, optional INTEGER)')
        conn.execute('INSERT INTO customers VALUES (?,?,?,?)', ('00001', '公司, "Owner"\nSecond line', 12.5, None))
        conn.execute('INSERT INTO customers VALUES (?,?,?,?)', ('00002', '', 0, 7))
    return module


def test_csv_export_survives_broken_scientific_stack_and_preserves_values(monkeypatch, tmp_path):
    module = load_export(monkeypatch, tmp_path)
    assert module.main() == 0
    with (tmp_path / 'raw/customers.csv').open(newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [{'id': '00001', 'note': '公司, "Owner"\nSecond line', 'amount': '12.5', 'optional': ''},
                    {'id': '00002', 'note': '', 'amount': '0.0', 'optional': '7'}]
    assert (tmp_path / 'raw/accounts.csv').read_text().strip() == 'id,note,amount,optional'
    assert not list((tmp_path / 'raw').glob('*.tmp'))
    first = (tmp_path / 'raw/customers.csv').read_bytes()
    module.main()
    assert (tmp_path / 'raw/customers.csv').read_bytes() == first


def test_failed_export_preserves_existing_file(monkeypatch, tmp_path):
    module = load_export(monkeypatch, tmp_path)
    (tmp_path / 'raw').mkdir()
    target = tmp_path / 'raw/customers.csv'
    target.write_text('previous export')
    def fail(*args):
        raise OSError('disk error')
    monkeypatch.setattr(module.os, 'replace', fail)
    with pytest.raises(OSError, match='disk error'):
        module.main()
    assert target.read_text() == 'previous export'
    assert not list((tmp_path / 'raw').glob('*.tmp'))


def test_requirements_exclude_numpy1_pandas_binaries():
    from packaging.requirements import Requirement
    reqs = {r.name: r for line in (ROOT / 'requirements.txt').read_text().splitlines()
            if line and not line.startswith('#') for r in [Requirement(line.split('#')[0].strip())]}
    assert '2.1.1' not in reqs['pandas'].specifier
    assert '2.2.3' in reqs['pandas'].specifier
    assert '2.3.3' in reqs['pandas'].specifier
    assert '3.0' not in reqs['pandas'].specifier
    assert '2.2.6' in reqs['numpy'].specifier
