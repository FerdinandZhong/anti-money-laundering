"""Bounded ownership traversal and decimal, account-grain activity calculations."""
from decimal import Decimal, InvalidOperation
from datetime import timedelta
from compliance.applicability import instant


def ownership(root,parties,edges):
    lookup={p['party_id']:p for p in parties}
    owners={};paths=[];issues=[]
    if len(lookup)!=len(parties) or len({e['edge_id'] for e in edges})!=len(edges):
        return {'outcome':'CONFLICTING_EVIDENCE','reason':'Duplicate ownership identifiers','complete':False}
    visits=0
    def walk(node,share,path):
        nonlocal visits
        visits+=1
        if visits>1000 or len(path)>32:
            issues.append('Traversal bound reached');return
        if node in path:
            issues.append('Ownership cycle: '+' -> '.join(path+[node]));return
        party=lookup.get(node)
        if not party:
            issues.append('Unknown party '+node);return
        if party['kind']=='natural':
            owners[node]=owners.get(node,Decimal(0))+share
            paths.append({'parties':path+[node],'percentage':str(share*100)})
            if party['verified']!='true':issues.append('Unverified natural person '+node)
            return
        if party['kind']!='legal':
            issues.append('Unsupported party kind '+node);return
        links=[e for e in edges if e['subject_party_id']==node]
        try:
            amounts=[Decimal(e['percentage']) for e in links]
            if any(not p.is_finite() or p<=0 or p>100 for p in amounts):
                raise ValueError('Invalid percentage')
        except (InvalidOperation,ValueError):
            issues.append('Invalid ownership percentage '+node);return
        if sum(amounts)!=100:
            issues.append('Incomplete or excessive ownership total '+node)
        for edge,amount in zip(links,amounts):
            walk(edge['owner_party_id'],share*amount/100,path+[node])
    walk(root,Decimal(1),[])
    return {'outcome':'REVIEW_REQUIRED' if issues else 'SATISFIED',
            'reason':'; '.join(issues) if issues else 'Fully disclosed demo ownership paths terminate at verified natural persons',
            'complete':not issues,'owners':{k:str(v*100) for k,v in sorted(owners.items())},'paths':paths,
            'edge_ids':[e['edge_id'] for e in edges]}


def activity(account,as_of,profile,transactions,rates):
    fail=lambda reason:{'outcome':'INSUFFICIENT_EVIDENCE','reason':reason,'complete':False}
    if profile.get('complete')!='true':return fail('Source aggregation is incomplete')
    if profile.get('direction')!='outbound' or profile.get('window_days')!='30':
        return {'outcome':'REVIEW_REQUIRED','reason':'Unsupported activity grain or period','complete':False}
    cutoff=instant(as_of); start=cutoff-timedelta(days=30)
    try:
        if instant(profile['coverage_start'])>start or instant(profile['coverage_end'])<cutoff:
            return fail('Requested window exceeds declared ledger coverage')
        scoped={r['transaction_id'] for r in transactions if r['from_account_id']==account}
        if len(scoped)!=int(profile['expected_rows']):
            return fail('Ledger row count does not match completeness manifest')
        expected=Decimal(profile['expected_amount']);threshold=Decimal(profile['threshold_ratio'])
        if not expected.is_finite() or expected<=0 or not threshold.is_finite() or threshold<=0:
            return fail('Invalid expected activity profile')
        total=Decimal(0);seen={};included=[];excluded=[];fx_ids=[]
        for row in transactions:
            if row['from_account_id']!=account or not start<instant(row['event_time'])<=cutoff:
                continue
            if instant(row['received_at'])>cutoff:continue
            tid=row['transaction_id']
            if tid in seen:
                if row!=seen[tid]:
                    return {'outcome':'CONFLICTING_EVIDENCE','reason':'Conflicting duplicate transaction '+tid,'complete':False}
                continue
            seen[tid]=row
            if row['internal']=='true' and profile['exclude_internal']=='true':
                excluded.append(tid);continue
            amount=Decimal(row['amount'])
            if not amount.is_finite() or amount<0:return fail('Invalid transaction amount')
            rate=Decimal(1)
            if row['currency']!=profile['currency']:
                candidates=[r for r in rates if r['base_currency']==row['currency'] and r['quote_currency']==profile['currency']
                            and r['rate_date']==instant(row['event_time']).date().isoformat() and instant(r['published_at'])<=cutoff]
                if len(candidates)!=1:return fail('Missing or ambiguous dated FX rate for '+tid)
                rate=Decimal(candidates[0]['rate']);fx_ids.append(candidates[0]['rate_id'])
                if not rate.is_finite() or rate<=0:return fail('Invalid FX rate')
            total+=amount*rate;included.append(tid)
        ratio=total/expected
    except (InvalidOperation,ValueError,KeyError):
        return fail('Malformed activity input')
    return {'outcome':'GAP' if ratio>threshold else 'SATISFIED','reason':'Observed external outflow compared with the explicit 30-day demo profile',
            'complete':True,'observed_amount':str(total),'expected_amount':str(expected),'ratio':str(ratio),
            'threshold_ratio':str(threshold),'currency':profile['currency'],'account_id':account,
            'window_start_exclusive':start.isoformat(),'window_end_inclusive':cutoff.isoformat(),
            'transaction_ids':included,'excluded_internal_ids':excluded,'fx_rate_ids':sorted(set(fx_ids))}
