"""Generate isolated Impala DDL and typed Parquet for Step 3 demo source rows.

Local only. Execute the generated SQL manually against a test Impala database.
"""
import csv
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import uuid

try:
    ROOT = Path(__file__).resolve().parents[2]
except NameError:
    ROOT = Path.cwd()
sys.path.insert(0,str(ROOT/'02_backend'))

import pyarrow as pa
import pyarrow.parquet as pq
from compliance.evaluator import _extract
from knowledge.demo_records import document_id
from knowledge.kb import Store, timestamp

SOURCE=Path(os.environ.get('AML_KYC_SEMANTIC_DIR', ROOT/'data/kyc_semantic_demo'))
OUT=ROOT/'artifacts/kyc_poc/semantic_publication'
SCHEMAS={
    'accounts': pa.schema([('account_id',pa.string()),('customer_id',pa.string()),
                           ('booking_jurisdiction',pa.string()),('product',pa.string()),('booking_entity',pa.string())]),
    'assertions': pa.schema([('assertion_id',pa.string()),('customer_id',pa.string()),
                             ('account_id',pa.string()),('source',pa.string()),('field',pa.string()),
                             ('value',pa.string()),('received_at',pa.timestamp('us')),
                             ('effective_from',pa.timestamp('us')),('source_ref',pa.string()),
                             ('page',pa.int32()),('verified',pa.bool_()),('confidence',pa.float64()),
                             ('document_id',pa.string()),('version_id',pa.string()),
                             ('chunk_id',pa.string()),('source_sha256',pa.string()),
                             ('knowledge_release',pa.string())]),
}
S=pa.string(); T=pa.timestamp('us'); B=pa.bool_(); D=pa.decimal128(28,8)
SCHEMAS.update({
    'ownership_parties':pa.schema([('customer_id',S),('party_id',S),('kind',S),('verified',B),('effective_from',T),('received_at',T)]),
    'ownership_edges':pa.schema([('edge_id',S),('customer_id',S),('account_id',S),('subject_party_id',S),('owner_party_id',S),('percentage',D),('effective_from',T),('received_at',T)]),
    'ownership_roots':pa.schema([('customer_id',S),('account_id',S),('root_party_id',S),('effective_from',T),('received_at',T)]),
    'activity_profiles':pa.schema([('profile_id',S),('customer_id',S),('account_id',S),('currency',S),('expected_amount',D),('threshold_ratio',D),('window_days',pa.int32()),('direction',S),('exclude_internal',B),('complete',B),('effective_from',T),('received_at',T),('expected_rows',pa.int32()),('coverage_start',T),('coverage_end',T)]),
    'activity_transactions':pa.schema([('transaction_id',S),('customer_id',S),('account_id',S),('from_account_id',S),('to_account_id',S),('amount',D),('currency',S),('internal',B),('event_time',T),('received_at',T)]),
    'fx_rates':pa.schema([('rate_id',S),('base_currency',S),('quote_currency',S),('rate_date',S),('rate',D),('published_at',T)]),
})


def _coerce(value, dtype):
    if pa.types.is_timestamp(dtype):
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).replace(tzinfo=None)
    if pa.types.is_integer(dtype): return int(value)
    if pa.types.is_boolean(dtype): return value.lower()=='true'
    if pa.types.is_floating(dtype): return float(value)
    if pa.types.is_decimal(dtype):return Decimal(value)
    return value


def _literal(value):
    if isinstance(value,datetime): return "CAST('"+value.isoformat(sep=' ')+"' AS TIMESTAMP)"
    if isinstance(value,bool): return 'TRUE' if value else 'FALSE'
    if isinstance(value,(int,float,Decimal)): return str(value)
    return "'"+str(value).replace("'","''")+"'"


def prepare():
    OUT.mkdir(parents=True,exist_ok=True)
    store=Store()
    db='aml_kyc_semantic_demo_'+uuid.uuid4().hex[:8]
    sql=[f'CREATE DATABASE IF NOT EXISTS {db};']
    report={'database':db}
    materialized={}
    for name,schema in SCHEMAS.items():
        with (SOURCE/f'{name}.csv').open(newline='',encoding='utf-8') as handle:
            reader=csv.DictReader(handle)
            input_fields=SCHEMAS[name].names[:12] if name=='assertions' else SCHEMAS[name].names
            if reader.fieldnames != input_fields:
                raise ValueError(f'{name} column mismatch')
            raw=list(reader)
        if name=='assertions':
            extracted=[]
            for row in raw:
                docs=[d for d in store.documents(row['customer_id'],row['account_id'])
                      if d['document_id']==document_id(row['source_ref']) and
                      d['received_at']==timestamp(row['received_at'])]
                if len(docs)!=1:
                    raise ValueError(f"No matching indexed document for {row['assertion_id']}")
                doc=docs[0]
                store.asset(row['customer_id'],doc['version_id'],row['account_id'])
                values=_extract(row,doc,store,row['customer_id'],row['account_id'])
                if len(values)!=1:
                    raise ValueError(f"Expected one extracted value for {row['assertion_id']}; found {len(values)}")
                fact=values[0]
                extracted.append({**row,'value':fact['value'],'confidence':fact['confidence'],'document_id':fact['document_id'],
                                  'version_id':fact['version_id'],'chunk_id':fact['chunk_id'],
                                  'source_sha256':fact['source_sha256'],
                                  'knowledge_release':store.manifest['release_id']})
            raw=extracted
        rows=[{f.name:_coerce(row[f.name],f.type) for f in schema} for row in raw]
        materialized[name]=rows
        key_fields={'ownership_parties':['customer_id','party_id'],'ownership_roots':['customer_id','account_id']}.get(name,[schema.names[0]])
        if len({tuple(row[k] for k in key_fields) for row in rows})!=len(rows):
            raise ValueError(f'{name} duplicate key')
        table=pa.Table.from_pylist(rows,schema=schema)
        pq.write_table(table,OUT/f'{name}.parquet')
        assert pq.read_table(OUT/f'{name}.parquet').equals(table)
        def dtype(field):
            if pa.types.is_timestamp(field.type): return 'TIMESTAMP'
            if pa.types.is_integer(field.type): return 'INT'
            if pa.types.is_boolean(field.type): return 'BOOLEAN'
            if pa.types.is_floating(field.type): return 'DOUBLE'
            if pa.types.is_decimal(field.type):return f'DECIMAL({field.type.precision},{field.type.scale})'
            return 'STRING'
        cols=', '.join(f'`{f.name}` {dtype(f)}' for f in schema)
        sql.append(f'CREATE TABLE IF NOT EXISTS {db}.{name} ({cols}) STORED AS ICEBERG;')
        # The same bundle can be retried after an interruption without appending
        # duplicates. Activation remains a separate, explicit application setting.
        sql.append(f'INSERT OVERWRITE TABLE {db}.{name} VALUES '+',\n'.join('('+', '.join(_literal(row[f.name]) for f in schema)+')' for row in rows)+';')
        report[name]={'rows':len(rows),'schema':str(schema),'parquet_verified':True}
    account_keys={(r['customer_id'],r['account_id']) for r in materialized['accounts']}
    for name,rows in materialized.items():
        if name!='accounts' and 'account_id' in SCHEMAS[name].names:
            assert all((r['customer_id'],r['account_id']) in account_keys for r in rows),f'{name} dangling account'
    party_keys={(r['customer_id'],r['party_id']) for r in materialized['ownership_parties']}
    assert all((r['customer_id'],r[k]) in party_keys for r in materialized['ownership_edges'] for k in ['subject_party_id','owner_party_id'])
    assert all((r['customer_id'],r['root_party_id']) in party_keys for r in materialized['ownership_roots'])
    (OUT/'publish.sql').write_text('\n\n'.join(sql)+'\n',encoding='utf-8')
    report['knowledge_release']=store.manifest['release_id']
    checks=[]
    for name,schema in SCHEMAS.items():
        expected=report[name]['rows']
        key_fields={'ownership_parties':['customer_id','party_id'],
                    'ownership_roots':['customer_id','account_id']}.get(name,[schema.names[0]])
        distinct_expr=(key_fields[0] if len(key_fields)==1 else
                       "CONCAT_WS('|', "+', '.join(f'CAST({field} AS STRING)' for field in key_fields)+')')
        checks.append(f'-- Expected rows: {expected}; duplicate keys: 0\n'
                      f'SELECT COUNT(*) AS actual_rows, COUNT(*) - COUNT(DISTINCT {distinct_expr}) '
                      f'AS duplicate_keys FROM {db}.{name};')
    (OUT/'validate.sql').write_text('\n\n'.join(checks)+'\n',encoding='utf-8')
    (OUT/'activate.env.example').write_text(
        f'# Apply only after validate.sql matches report.json; keep prior database for rollback.\n'
        f'AML_KYC_SOURCE_BACKEND=impala\nAML_KYC_IMPALA_DATABASE={db}\n')
    report['publication_policy']='Isolated database; retry same publish.sql uses INSERT OVERWRITE. Validate counts before changing application environment.'
    (OUT/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    print(json.dumps(prepare(),indent=2))
