"""The expanded documents use real generated AML source keys and one CSV contract."""
import csv
from pathlib import Path


def test_generated_customer_account_keys_and_semantic_contract(tmp_path,monkeypatch):
    from data_generation.generate_synthetic_data import gen_customers,gen_accounts
    from common import kyc_source
    from importlib.util import spec_from_file_location,module_from_spec
    path=Path(__file__).resolve().parents[1]/'scripts/prepare_kyc_semantic_runtime.py'
    spec=spec_from_file_location('kyc_runtime',path)
    runtime=module_from_spec(spec);spec.loader.exec_module(runtime)
    customers=gen_customers(400)
    accounts=gen_accounts(customers,500)
    account_keys={(row['customer_id'],row['account_id']) for row in accounts}
    scenarios=[]
    for group in range(1,13):
        customer=f'CUST-{group+295:06d}'
        for index in range(1,(3 if group<=6 else 2)+1):
            account=f'ACC-{group+295:07d}' if index==1 else f'ACC-KYC-{group:03d}-{index}'
            assert (customer,account) in account_keys
            scenarios.append({'customer_id':customer,'account_id':account,
                              'booking_jurisdiction':'SG' if group%2 else 'HK',
                              'currency':'SGD' if group%2 else 'HKD',
                              'classification':'SYNTHETIC_KYC_CORPUS'})
    source=tmp_path/'accounts.csv'
    with source.open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(scenarios[0]));writer.writeheader();writer.writerows(scenarios)
    target=tmp_path/'semantic'
    report=runtime.prepare(source,target)
    assert report['accounts']==30 and len(report['source_tables'])==8
    monkeypatch.setenv('AML_KYC_SEMANTIC_DIR',str(target))
    assert len(kyc_source.rows('accounts'))==32
    assert len(kyc_source.rows('assertions'))==234
    assert len(kyc_source.fingerprint('assertions'))==64
    assert all(row['value']=='' for row in kyc_source.rows('assertions')[6:])


def test_explicit_impala_adapter_uses_whitelisted_table_and_fails_closed(monkeypatch):
    import pandas as pd
    from common import kyc_source,source
    monkeypatch.setenv('AML_KYC_SOURCE_BACKEND','impala')
    monkeypatch.setenv('AML_KYC_IMPALA_DATABASE','aml_kyc_test_1234')
    monkeypatch.setattr(source,'backend',lambda:'impala')
    queries=[]
    monkeypatch.setattr(source,'_sql_df',lambda sql: queries.append(sql) or pd.DataFrame([{
        'account_id':'ACC-TEST','customer_id':'CUST-TEST','booking_jurisdiction':'SG',
        'product':'KYC_CORPUS','booking_entity':'Demo'}]))
    result=kyc_source.rows('accounts')
    assert result[0]['account_id']=='ACC-TEST'
    assert queries==['SELECT * FROM `aml_kyc_test_1234`.`accounts`']
    try:
        kyc_source.rows('accounts; DROP TABLE x')
        assert False,'Unsupported table accepted'
    except ValueError:
        pass
    monkeypatch.setattr(source,'backend',lambda:'csv')
    try:
        kyc_source.rows('accounts')
        assert False,'Configured Impala silently fell back to CSV'
    except RuntimeError:
        pass


def test_linked_control_snapshots_use_revisions_account_scope_and_structured_rows(tmp_path,monkeypatch):
    from importlib.util import spec_from_file_location,module_from_spec
    from knowledge.kb import build
    from compliance.evaluator import evaluate
    scripts=Path(__file__).resolve().parents[1]/'scripts'
    def load(name):
        spec=spec_from_file_location(name,scripts/(name+'.py'))
        module=module_from_spec(spec);spec.loader.exec_module(module)
        return module
    corpus=load('prepare_kyc_corpus');runtime=load('prepare_kyc_semantic_runtime')
    accounts=corpus.scenario_accounts()
    input_csv=tmp_path/'accounts.csv'
    with input_csv.open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(accounts[0]));writer.writeheader();writer.writerows(accounts)
    target=tmp_path/'semantic'
    runtime.prepare(input_csv,target)
    manifest=[]
    for group in (1,3,4):
        customer=f'CUST-{group+295:06d}'
        for family,(_,fields) in corpus.FAMILIES.items():
            for revision,day in ((1,1),(2,18)):
                values=[f'Revision / 版本: {revision}']+[field.format(group=group) for field in fields]
                if family=='registry' and revision==2 and group%3==0:
                    values[1]='Beneficial owner / 受益所有人: Chen Min'
                path=tmp_path/f'corpus-{group:03d}-{family}-v{revision}.txt'
                path.write_text('\n'.join(values))
                manifest.append({'document_id':f'corpus-{group:03d}-{family}',
                                 'customer_id':customer,
                                 'account_id':f'ACC-{group+295:07d}' if family in ('mandate','funding') else '',
                                 'title':family,'path':str(path),'received_at':f'2026-09-{day:02d}T00:00:00Z',
                                 'pages':[{'page':1,'text':path.read_text()}]})
    monkeypatch.setenv('AML_KYC_SEMANTIC_DIR',str(target))
    monkeypatch.setenv('AML_KNOWLEDGE_DIR',str(tmp_path/'knowledge'))
    build(manifest,root=tmp_path/'knowledge')
    early=evaluate('CUST-000298','ACC-0000298','2026-09-12T00:00:00Z')
    later=evaluate('CUST-000298','ACC-0000298','2026-09-20T00:00:00Z')
    def owner(result):
        return next(control for control in result['controls'] if control['concept']=='registry_owner_record')['evidence'][0]['value']
    assert owner(early)=='Lin Mei' and owner(later)=='Chen Min'
    first=evaluate('CUST-000296','ACC-0000296','2026-09-20T00:00:00Z')
    assert len(first['controls'])==7
    assert all(control['outcome']=='SATISFIED' for control in first['controls'])
    extra=evaluate('CUST-000296','ACC-KYC-001-2','2026-09-20T00:00:00Z')
    outcomes={control['concept']:control['outcome'] for control in extra['controls']}
    assert outcomes['account_signing_authority']=='INSUFFICIENT_EVIDENCE'
    assert outcomes['source_of_funds']=='INSUFFICIENT_EVIDENCE'
    assert outcomes['disclosed_ownership_paths']=='SATISFIED'
    anomaly=evaluate('CUST-000299','ACC-0000299','2026-09-20T00:00:00Z')
    assert next(control for control in anomaly['controls'] if control['concept']=='account_external_outflow_30d')['outcome']=='GAP'
