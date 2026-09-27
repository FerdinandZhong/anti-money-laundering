"""Eight-table KYC semantic source contract over local CSV or explicit Impala.

Impala is opt-in after isolated publication. It never falls back to CSV when
configured, so an unavailable or incomplete warehouse cannot silently pass.
"""
import csv
import hashlib
import json
import os
from pathlib import Path
import re

from common.config import PROJECT_ROOT

TABLES=('accounts','assertions','ownership_parties','ownership_edges','ownership_roots',
        'activity_profiles','activity_transactions','fx_rates')


def _backend():
    backend=os.environ.get('AML_KYC_SOURCE_BACKEND','csv')
    if backend not in ('csv','impala'):
        raise ValueError('AML_KYC_SOURCE_BACKEND must be csv or impala')
    return backend


def csv_root():
    setting=Path(os.environ.get('AML_KYC_SEMANTIC_DIR','data/kyc_semantic_demo'))
    return setting if setting.is_absolute() else Path(PROJECT_ROOT)/setting


def rows(name):
    if name not in TABLES:
        raise ValueError('Unsupported KYC source table')
    if _backend()=='csv':
        with (csv_root()/(name+'.csv')).open(newline='',encoding='utf-8') as handle:
            return list(csv.DictReader(handle))
    database=os.environ.get('AML_KYC_IMPALA_DATABASE','')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,127}',database):
        raise ValueError('Explicit AML_KYC_IMPALA_DATABASE is required')
    from common import source
    if source.backend()!='impala':
        raise RuntimeError('Impala KYC source requested but Impala is unavailable')
    frame=source._sql_df(f'SELECT * FROM `{database}`.`{name}`')
    if frame.empty:
        return []
    return [{key: 'true' if value is True else 'false' if value is False else str(value)
             for key,value in row.items()} for row in frame.to_dict(orient='records')]


def fingerprint(name):
    if _backend()=='csv':
        return hashlib.sha256((csv_root()/(name+'.csv')).read_bytes()).hexdigest()
    payload=json.dumps(sorted(rows(name),key=lambda row:json.dumps(row,sort_keys=True)),
                       sort_keys=True,separators=(',',':'))
    return hashlib.sha256(payload.encode()).hexdigest()
