"""Prepare typed KYC samples; optionally publish only into a new test database.

Default: local CSV/Parquet round-trip. --execute: DNS/auth preflight, create a
unique aml_kyc_poc_* database, SQL Parquet staging -> Iceberg, repeat readback checks.
No DROP, production writes, active-release switch, or credential output.
SQL staging tests engine publication; external file upload is a separate gate.
"""
import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import uuid

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

try:
    ROOT = Path(__file__).resolve().parents[2]
except NameError:
    ROOT = Path.cwd()
OUT = ROOT / 'artifacts/kyc_poc/publication'


def canonical(rows):
    return json.dumps(sorted(rows,key=lambda r:str(r[0])),ensure_ascii=False,default=str,separators=(',',':'))


def tables():
    result={
        'parties': (pa.schema([('party_id',pa.string()),('name',pa.string()),('registration_id',pa.string()),
                              ('expected_turnover',pa.decimal128(20,4)),('currency',pa.string()),('reviewed_at',pa.timestamp('us')),('note',pa.string())]),
                    [('P-EN',"O'Brien Trading Ltd.",'000017',Decimal('421390.0000'),'SGD',datetime(2026,9,1),None),
                     ('P-ZH','澄海贸易有限公司','000018',Decimal('123456789012.3456'),'CNY',datetime(2026,9,1),'合成测试'),
                     ('P-MIXED','澄海 Blue Harbor','000019',Decimal('0.0000'),'HKD',None,'')]),
        'documents': (pa.schema([('document_id',pa.string()),('party_id',pa.string()),('sha256',pa.string()),('language',pa.string()),('uri',pa.string())]),[]),
        'facts': (pa.schema([('fact_id',pa.string()),('document_id',pa.string()),('field_name',pa.string()),('raw_value',pa.string()),('page_no',pa.int32())]),[]),
    }
    for path in sorted((ROOT/'artifacts/kyc_poc/extraction').glob('*.pdf.extracted.json')):
        data=json.loads(path.read_text()); lang=path.name.split('_')[0]
        doc_id=path.name.removesuffix('.pdf.extracted.json')
        result['documents'][1].append((doc_id,'P-'+lang.upper(),data['sha256'],lang,str(path.with_name(doc_id+'.pdf').relative_to(ROOT))))
        for key,assertions in sorted(data['fields'].items()):
            for i,item in enumerate(assertions):
                result['facts'][1].append((f'{doc_id}-{key}-{i}',doc_id,key,item['value'],item['evidence']['page']))
    assert result['documents'][1] and result['facts'][1], 'Run extraction POC first'
    party_ids={r[0] for r in result['parties'][1]}; doc_ids={r[0] for r in result['documents'][1]}
    assert all(r[1] in party_ids for r in result['documents'][1])
    assert all(r[1] in doc_ids for r in result['facts'][1])
    return result


def parse(value, kind):
    if value == r'\N': return None
    if pa.types.is_decimal(kind): return Decimal(value)
    if pa.types.is_timestamp(kind): return datetime.fromisoformat(value)
    if pa.types.is_integer(kind): return int(value)
    return value


def sql_type(kind):
    if pa.types.is_decimal(kind): return f'DECIMAL({kind.precision},{kind.scale})'
    if pa.types.is_timestamp(kind): return 'TIMESTAMP'
    if pa.types.is_integer(kind): return 'INT'
    return 'STRING'


def literal(value):
    if value is None: return 'NULL'
    if isinstance(value,(Decimal,int)): return str(value)
    if isinstance(value,datetime): return "CAST('"+value.isoformat(sep=' ')+"' AS TIMESTAMP)"
    return "'"+str(value).replace('\\','\\\\').replace("'","\\'")+"'"


def prepare(data,database):
    OUT.mkdir(parents=True,exist_ok=True)
    checks={}; statements=[f'CREATE DATABASE {database}']
    for name,(schema,rows) in data.items():
        assert len({r[0] for r in rows})==len(rows)
        array=pa.Table.from_pylist([dict(zip(schema.names,r)) for r in rows],schema=schema)
        pq.write_table(array,OUT/f'{name}.parquet')
        assert pq.read_table(OUT/f'{name}.parquet').equals(array)
        with (OUT/f'{name}.csv').open('w',newline='') as f:
            writer=csv.writer(f); writer.writerow(schema.names)
            writer.writerows([r'\N' if v is None else str(v) for v in r] for r in rows)
        with (OUT/f'{name}.csv').open(newline='') as f:
            reader=csv.reader(f); assert next(reader)==schema.names
            decoded=[tuple(parse(v,field.type) for v,field in zip(row,schema)) for row in reader]
        assert canonical(decoded)==canonical(rows)
        checks[name]={'rows':len(rows),'csv_parquet_exact':True,'sha256':hashlib.sha256(canonical(rows).encode()).hexdigest()}
        cols=', '.join(f'`{f.name}` {sql_type(f.type)}' for f in schema)
        names=', '.join(f'`{n}`' for n in schema.names)
        statements += [f'CREATE TABLE {database}.stage_{name} ({cols}) STORED AS PARQUET',
                       f'CREATE TABLE {database}.{name} ({cols}) STORED AS ICEBERG',
                       f'INSERT INTO {database}.stage_{name} VALUES '+', '.join('('+', '.join(literal(v) for v in row)+')' for row in rows),
                       f'INSERT INTO {database}.{name} SELECT {names} FROM {database}.stage_{name}']
    (OUT/'publication.sql').write_text(';\n\n'.join(statements)+';\n')
    return checks,statements


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--execute',action='store_true'); args=parser.parse_args()
    database='aml_kyc_poc_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
    data=tables(); checks,statements=prepare(data,database)
    report={'database':database,'local_checks':checks,'remote_status':'not_attempted',
            'external_parquet_upload':'not_tested','active_release_changed':False,
            'retention':'Test namespace retained if created; no destructive cleanup is performed.',
            'facts':'Actual extraction assertions, including any OCR errors; not verified KYC facts.'}
    password=None; conn=None
    try:
        if args.execute:
            p=ROOT/'config/config.yaml'
            if not p.exists(): p=ROOT/'config/config.yaml.example'
            cfg=yaml.safe_load(p.read_text())['source']['impala']
            host=os.environ.get('IMPALA_HOST',cfg['host']); port=int(os.environ.get('IMPALA_PORT',cfg.get('port',443)))
            report.update({'host':host,'stage':'dns_tcp'})
            with socket.create_connection((host,port),timeout=8): pass
            report['stage']='authentication'
            password=os.environ.get('IMPALA_PASSWORD') or (Path.home()/'tokens/workload_password').read_text().strip()
            from impala.dbapi import connect
            conn=connect(host=host,port=port,user=os.environ.get('IMPALA_USER',cfg['user']),password=password,
                         use_ssl=True,use_http_transport=True,http_path=os.environ.get('IMPALA_HTTP_PATH',cfg['http_path']),
                         auth_mechanism=cfg.get('auth_mechanism','LDAP'),database=cfg.get('database','default'),timeout=20)
            cur=conn.cursor(); cur.execute('SELECT VERSION()'); report['server_version']=str(cur.fetchone()[0])
            report['stage']='isolated_publication'
            for statement in statements: cur.execute(statement)
            report['stage']='readback'
            for name,(schema,rows) in data.items():
                cols=', '.join(f'`{n}`' for n in schema.names)
                # Repeat readback checks stability. This does not demonstrate
                # interrupted-load recovery or idempotent publication retries.
                for attempt in range(2):
                    cur.execute(f'SELECT {cols} FROM {database}.{name}')
                    assert canonical(cur.fetchall())==canonical(rows), f'{name} parity failure'
                checks[name]['impala_exact']=True
                checks[name]['repeated_readback_exact']=True
                cur.execute(f'SHOW CREATE TABLE {database}.{name}')
                (OUT/f'{name}.actual_ddl.txt').write_text('\n'.join(str(r[0]) for r in cur.fetchall()))
            cur.execute(f'SELECT COUNT(*) FROM {database}.facts f JOIN {database}.documents d ON f.document_id=d.document_id JOIN {database}.parties p ON d.party_id=p.party_id')
            assert cur.fetchone()[0]==len(data['facts'][1]),'join coverage failure'
            report.update({'remote_status':'passed','join_coverage':True,'stage':'complete'})
    except Exception as exc:
        message=str(exc)
        if password: message=message.replace(password,'[REDACTED]')
        report.update({'remote_status':'blocked' if report.get('stage') in ['dns_tcp','authentication'] else 'failed',
                       'error_type':type(exc).__name__,'error':message[:600]})
    finally:
        if conn: conn.close()
        (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['remote_status'] in ['not_attempted','passed'] else 2


if __name__=='__main__':
    sys.exit(main())
