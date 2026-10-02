"""Small tests for extraction provenance and lossless publication preparation."""
import importlib.util
from pathlib import Path
from decimal import Decimal

import pytest
fitz = pytest.importorskip('fitz', reason='Optional KYC POC PDF dependency')
import pyarrow as pa


def load(name):
    path = Path(__file__).resolve().parents[1] / 'scripts' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_native_extractor_reads_unseen_values_and_preserves_roles(tmp_path):
    module = load('kyc_extraction_poc')
    path = tmp_path / 'unseen.pdf'
    doc = fitz.open(); page = doc.new_page()
    page.insert_text((30,50), 'Company name: Unseen Example')
    page.insert_text((30,80), 'Legal representative: Alice')
    page.insert_text((30,110), 'Beneficial owner: Bob')
    doc.save(path); doc.close()
    result = module.extract(path, None)
    assert result['fields']['company_name'][0]['value'] == 'Unseen Example'
    assert result['fields']['representative'][0]['value'] == 'Alice'
    assert result['fields']['beneficial_owner'][0]['value'] == 'Bob'
    assert result['fields']['beneficial_owner'][0]['evidence']['page'] == 1
    assert 'review_date' not in result['fields']


def test_empty_page_never_fills_fields_from_fixture(tmp_path):
    module = load('kyc_extraction_poc')
    path = tmp_path / 'blank.pdf'
    doc = fitz.open(); doc.new_page(); doc.save(path); doc.close()
    result = module.extract(path, lambda image: (None, None))
    assert result['fields'] == {} and result['table'] == []


def test_publication_roundtrip_preserves_money_unicode_null_and_empty(tmp_path):
    module = load('kyc_impala_publication_poc'); module.OUT = tmp_path
    schema = pa.schema([('id',pa.string()), ('money',pa.decimal128(20,4)), ('text',pa.string())])
    rows = [('00001',Decimal('123456789012.3456'),"澄海 O'Brien"),
            ('00002',Decimal('0.0000'),None), ('00003',Decimal('-0.0100'),'')]
    checks, sql = module.prepare({'samples': (schema,rows)}, 'aml_kyc_poc_test')
    assert checks['samples']['csv_parquet_exact']
    assert checks['samples']['rows'] == 3
    assert 'STORED AS ICEBERG' in '\n'.join(sql)
    assert all('DROP ' not in s for s in sql)


def test_sql_literal_keeps_synthetic_strings_in_one_literal():
    module = load('kyc_impala_publication_poc')
    assert module.literal("O'Brien") == "'O\\'Brien'"
    assert module.literal(None) == 'NULL'
    assert module.literal(Decimal('0.0100')) == '0.0100'
