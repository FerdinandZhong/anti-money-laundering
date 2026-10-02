"""Extend the demo semantic CSV contract with linked source accounts/documents.

Assertion values are deliberately blank: evaluation and publication extract them
from immutable indexed PDF pages. All eight source tables share one CSV contract.
"""
import csv
from pathlib import Path
import shutil

try:
    ROOT = Path(__file__).resolve().parents[2]
except NameError:
    ROOT = Path.cwd()

BASE = ROOT / 'data/kyc_semantic_demo'
FAMILIES = {
    'registry': ('registry','Beneficial owner / 受益所有人'),
    'mandate': ('mandate','Authorized signatory / 授权签字人'),
    'funding': ('onboarding','Funding origin / 资金来源'),
    'wealth': ('onboarding','Wealth origin / 财富来源'),
    'review': ('review','Review due date / 复核到期日'),
}


def _append(path, rows):
    with path.open(newline='',encoding='utf-8') as handle:
        reader=csv.DictReader(handle)
        fields=reader.fieldnames
        existing=list(reader)
    with path.open('w',newline='',encoding='utf-8') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields)
        writer.writeheader();writer.writerows(existing+rows)


def prepare(accounts, output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    for source in BASE.glob('*.csv'):
        shutil.copyfile(source,output/source.name)
    with Path(accounts).open(newline='',encoding='utf-8') as handle:
        rows=list(csv.DictReader(handle))
    expected={f'CUST-{n:06d}' for n in range(296,308)}
    if len(rows)!=30 or {r['customer_id'] for r in rows}!=expected or len({r['account_id'] for r in rows})!=30:
        raise ValueError('Linked corpus requires 12 source customers and 30 unique accounts')
    account_rows=[{'account_id':r['account_id'],'customer_id':r['customer_id'],
                   'booking_jurisdiction':r['booking_jurisdiction'], 'product':'KYC_CORPUS',
                   'booking_entity':'Synthetic SG Bank' if r['booking_jurisdiction']=='SG' else 'Synthetic HK Bank'}
                  for r in rows]
    _append(output/'accounts.csv',account_rows)
    assertions=[]
    for account in rows:
        group=int(account['customer_id'].split('-')[-1])-295
        for family,(source,field) in FAMILIES.items():
            if family in ('mandate','funding') and not account['account_id'].endswith(f'{group+295:07d}'):
                continue
            for revision,day in ((1,1),(2,18)):
                reference=f'corpus-{group:03d}-{family}-v{revision}.pdf'
                assertions.append({'assertion_id':f'A-CORPUS-{group:03d}-{account["account_id"]}-{family}-v{revision}',
                                   'customer_id':account['customer_id'],'account_id':account['account_id'],
                                   'source':source,'field':field,'value':'',
                                   'received_at':f'2026-09-{day:02d}T00:00:00Z',
                                   'effective_from':f'2026-09-{day:02d}T00:00:00Z',
                                   'source_ref':reference,'page':1,'verified':'true','confidence':'0.95'})
    _append(output/'assertions.csv',assertions)
    effective='2026-08-01T00:00:00Z'; received='2026-09-01T00:00:00Z'
    parties=[];edges=[];roots=[];profiles=[];transactions=[]
    for group in range(1,13):
        customer=f'CUST-{group+295:06d}'
        root=f'P-CORPUS-{group:03d}'
        holding=f'H-CORPUS-{group:03d}'
        owner_a=f'N-CORPUS-{group:03d}-A'
        owner_b=f'N-CORPUS-{group:03d}-B'
        for party,kind in ((root,'legal'),(holding,'legal'),(owner_a,'natural'),(owner_b,'natural')):
            parties.append({'customer_id':customer,'party_id':party,'kind':kind,
                            'verified':'true','effective_from':effective,'received_at':received})
        for account in (row for row in rows if row['customer_id']==customer):
            account_id=account['account_id']
            roots.append({'customer_id':customer,'account_id':account_id,'root_party_id':root,
                          'effective_from':effective,'received_at':received})
            for edge_index,subject,owner,share in ((1,root,holding,'60.00'),
                                                    (2,root,owner_b,'40.00'),
                                                    (3,holding,owner_a,'100.00')):
                edges.append({'edge_id':f'EDGE-CORPUS-{group:03d}-{account_id}-{edge_index}',
                              'customer_id':customer,'account_id':account_id,
                              'subject_party_id':subject,'owner_party_id':owner,
                              'percentage':share,'effective_from':effective,'received_at':received})
            profiles.append({'profile_id':f'PROFILE-CORPUS-{account_id}',
                             'customer_id':customer,'account_id':account_id,
                             'currency':account['currency'],'expected_amount':'10000.00',
                             'threshold_ratio':'2.00','window_days':'30','direction':'outbound',
                             'exclude_internal':'true','complete':'true','effective_from':effective,
                             'received_at':received,'expected_rows':'1','coverage_start':effective,
                             'coverage_end':'2026-10-01T00:00:00Z'})
            amount='30000.00' if group%4==0 and account_id.endswith(f'{group+295:07d}') else '3000.00'
            transactions.append({'transaction_id':f'TX-CORPUS-{account_id}',
                                 'customer_id':customer,'account_id':account_id,
                                 'from_account_id':account_id,'to_account_id':f'EXT-CORPUS-{group:03d}',
                                 'amount':amount,'currency':account['currency'],'internal':'false',
                                 'event_time':'2026-09-10T10:00:00Z',
                                 'received_at':'2026-09-10T11:00:00Z'})
    for name,additional in [('ownership_parties',parties),('ownership_edges',edges),
                            ('ownership_roots',roots),('activity_profiles',profiles),
                            ('activity_transactions',transactions)]:
        _append(output/(name+'.csv'),additional)
    return {'accounts':len(account_rows),'assertion_metadata':len(assertions),
            'ownership_parties':len(parties),'ownership_edges':len(edges),
            'ownership_roots':len(roots),'activity_profiles':len(profiles),
            'activity_transactions':len(transactions),
            'source_tables':sorted(path.stem for path in output.glob('*.csv'))}


if __name__=='__main__':
    import argparse,json
    parser=argparse.ArgumentParser()
    parser.add_argument('--accounts',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.accounts,args.output),indent=2))
