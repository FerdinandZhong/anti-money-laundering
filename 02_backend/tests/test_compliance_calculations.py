import copy
from compliance.calculations import ownership,activity


def test_indirect_ownership_cycle_and_incomplete_graph():
    parties=[{'party_id':p,'kind':k,'verified':'true'} for p,k in [('root','legal'),('hold','legal'),('a','natural'),('b','natural')]]
    edges=[{'edge_id':str(i),'subject_party_id':s,'owner_party_id':o,'percentage':p}
           for i,(s,o,p) in enumerate([('root','hold','60'),('root','a','40'),('hold','b','100')])]
    result=ownership('root',parties,edges)
    assert result['complete'] and result['owners']=={'a':'40.0','b':'60.0'}
    cycle=copy.deepcopy(edges);cycle[2]['owner_party_id']='root'
    assert ownership('root',parties,cycle)['outcome']=='REVIEW_REQUIRED'
    assert not ownership('root',parties,edges[:2])['complete']
    assert not ownership('root',parties[:-1],edges)['complete']


def test_decimal_fx_account_grain_internal_exclusion_and_fail_closed():
    profile={'complete':'true','direction':'outbound','window_days':'30','currency':'SGD',
             'expected_amount':'1000.00','threshold_ratio':'2.0','exclude_internal':'true',
             'expected_rows':'2','coverage_start':'2026-08-01','coverage_end':'2026-09-12T23:59:59Z'}
    tx={'transaction_id':'one','from_account_id':'A','event_time':'2026-09-10','received_at':'2026-09-10',
        'internal':'false','amount':'2000.00','currency':'USD'}
    rates=[{'rate_id':'fx','base_currency':'USD','quote_currency':'SGD','rate_date':'2026-09-10',
            'published_at':'2026-09-10','rate':'1.30000000'}]
    internal={**tx,'transaction_id':'internal','internal':'true','amount':'999999.99'}
    other={**tx,'transaction_id':'other','from_account_id':'OTHER'}
    result=activity('A','2026-09-12',profile,[tx,tx,internal,other],rates)
    assert result['outcome']=='GAP' and result['transaction_ids']==['one']
    assert result['observed_amount']=='2600.0000000000'
    assert result['excluded_internal_ids']==['internal']
    assert not activity('A','2026-09-12',{**profile,'expected_rows':'1'},[tx],[])['complete']
    assert not activity('A','2026-09-12',profile,[tx],rates)['complete']
    assert not activity('A','2026-09-20',profile,[tx,internal],rates)['complete']
    assert not activity('A','2026-09-12',{**profile,'complete':'false'},[tx],rates)['complete']
    conflicting={**tx,'amount':'100.00'}
    assert activity('A','2026-09-12',{**profile,'expected_rows':'1'},[tx,conflicting],rates)['outcome']=='CONFLICTING_EVIDENCE'
