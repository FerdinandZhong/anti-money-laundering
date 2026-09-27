"""Read-only, reproducible synthetic KYC assessment slice."""
import csv
import hashlib
import copy
import math
import re
import os
import unicodedata
import yaml

from compliance.applicability import ROOT, applicable_controls, instant, mappings, pack, resolve
from knowledge.demo_records import document_id
from knowledge.kb import Store, Unavailable, timestamp
from common import kyc_source

FIXTURES = ROOT/'data/kyc_semantic_demo'
ENGINE_VERSION = 'kyc-controls-v3'
STRUCTURED_TABLES=('ownership_parties','ownership_edges','ownership_roots',
                   'activity_profiles','activity_transactions','fx_rates')


def _rows(name):
    return kyc_source.rows(name.removesuffix('.csv'))


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _extract(row, document, store, customer_id, account_id):
    """Parse the cited field from immutable indexed page text, never CSV value."""
    page_no = int(row['page'])
    try:
        chunks = store.page(customer_id, document['version_id'], page_no, account_id)
    except KeyError:
        return []
    # OCR may drop spaces around bilingual separators. Normalize typography only;
    # source names and concept mappings remain exact and review-gated.
    label=unicodedata.normalize('NFKC',row['field'])
    pattern = re.compile(r'^[ \t]*'+re.escape(label).replace(r'\ ',r'[ \t]*')+
                         r'[ \t]*:[ \t]*([^\r\n]*?)[ \t]*$',re.M)
    found = []
    for chunk in chunks:
        for match in pattern.finditer(unicodedata.normalize('NFKC',chunk['text'])):
            if match.group(1).strip():
                found.append((match.group(1),chunk['chunk_id'],chunk.get('evidence',[])))
    # Overlapping chunks can repeat the same line. Retain distinct observed values.
    unique = list(dict.fromkeys(value for value,_,_ in found))
    result = []
    for index,value in enumerate(unique):
        _,chunk_id,evidence = next(hit for hit in found if hit[0]==value)
        confidence=float(row['confidence'])
        ocr=[e for e in evidence if e.get('method')=='rapidocr']
        if ocr:
            confidence=min(confidence, min(float(e.get('confidence') or 0) for e in ocr))
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            confidence=0.0
        result.append({**{k:v for k,v in row.items() if k!='value'},
                       'assertion_id':row['assertion_id']+(f'-{index+1}' if len(unique)>1 else ''),
                       'value':value, 'document_id':document['document_id'],
                       'version_id':document['version_id'], 'chunk_id':chunk_id,
                       'page':page_no, 'source_sha256':document['sha256'],
                       'confidence':confidence,
                       'extraction_method':'rapidocr' if ocr else 'indexed_page_text',
                       'page_text':next(chunk['text'] for chunk in chunks if chunk['chunk_id']==chunk_id),
                       'page_evidence':evidence})
    return result


def evaluate(customer_id, account_id, as_of, release=None, include_snapshot=False):
    """Assess fixed demo scope from a pinned LanceDB release and CSV metadata."""
    instant(as_of)
    accounts = [a for a in _rows('accounts.csv') if a['customer_id'] == customer_id and a['account_id'] == account_id]
    if not accounts:
        return {'available':False, 'reason':'No demo regulatory profile for this alert account'}
    account = accounts[0]
    if len(accounts) != 1:
        raise ValueError('Duplicate account profile')
    controls = applicable_controls(account['booking_jurisdiction'], account['product'], as_of)
    if not controls:
        return {'available':False, 'reason':'No applicable demo control pack for this booking context'}
    metadata = [a for a in _rows('assertions.csv') if a['customer_id'] == customer_id and
                  a['account_id'] == account_id and instant(a['received_at']) <= instant(as_of) and
                  instant(a['effective_from']) <= instant(as_of)]
    if len({a['assertion_id'] for a in metadata}) != len(metadata):
        raise ValueError('Duplicate assertion ID')
    try:
        store = Store(release=release)
    except Unavailable:
        return {'available':False,'reason':'KYC knowledge release unavailable; build with --include-control-demo'}
    # Logical source revisions supersede earlier receipts of the same field.
    # This does not merge different source families (registry vs declaration).
    latest={}
    for row in metadata:
        key=(row['source'],row['field'],document_id(row['source_ref']))
        previous=latest.get(key)
        if previous is None or instant(row['received_at']) > instant(previous['received_at']):
            latest[key]=row
        elif instant(row['received_at']) == instant(previous['received_at']) and row['source_ref'] != previous['source_ref']:
            raise ValueError('Ambiguous source revision at same receipt time')
    metadata=list(latest.values())
    docs = {}
    for d in store.documents(customer_id,account_id,as_of):
        docs.setdefault(d['document_id'],[]).append(d)
    assertions=[]
    record_hashes={}
    missing=[]
    for row in metadata:
        candidates=[doc for doc in docs.get(document_id(row['source_ref']),[])
                    if doc['received_at']==timestamp(row['received_at'])]
        if len(candidates)!=1:
            missing.append({**row,'reason':'Document missing or version ambiguous'})
            continue
        doc=candidates[0]
        if timestamp(row['received_at']) != doc['received_at']:
            missing.append({**row,'reason':'Document receipt metadata mismatch'})
            continue
        # The copied original must still match the release metadata.
        try:
            store.asset(customer_id,doc['version_id'],account_id,as_of)
        except (KeyError,Unavailable):
            missing.append({**row,'reason':'Source asset unavailable or failed integrity validation'})
            continue
        extracted=_extract(row,doc,store,customer_id,account_id)
        assertions.extend(extracted)
        if extracted:
            record_hashes[row['source_ref']]=doc['sha256']
        else:
            missing.append({**row,'reason':'Expected field or page is absent or empty'})
    inputs = {name:kyc_source.fingerprint(name.removesuffix('.csv')) for name in ('accounts.csv','assertions.csv')}
    inputs.update({'mappings':_sha(ROOT/'semantic/aml_source_mappings.yaml'),
                   'controls':_sha(ROOT/'semantic/aml_control_packs.yaml'),
                   'regulatory_source_register':_sha(ROOT/'semantic/regulatory_source_register.yaml')})
    inputs.update(record_hashes)
    inputs['knowledge_release']=store.manifest['release_id']
    tables={}
    for name in STRUCTURED_TABLES:
        rows=_rows(name+'.csv')
        tables[name]=[r for r in rows if
                      (not r.get('customer_id') or r['customer_id']==customer_id) and
                      (not r.get('account_id') or r['account_id']==account_id) and
                      (not r.get('received_at') or instant(r['received_at'])<=instant(as_of)) and
                      (not r.get('effective_from') or instant(r['effective_from'])<=instant(as_of)) and
                      (not r.get('published_at') or instant(r['published_at'])<=instant(as_of))]
        inputs[name+'.csv']=kyc_source.fingerprint(name)
    snapshot={'engine_version':ENGINE_VERSION,'customer_id':customer_id,'account_id':account_id,
              'as_of':instant(as_of).isoformat(),'release_id':store.manifest['release_id'],
              'account':account,'assertions':assertions,
              'tables':tables,
              'missing_evidence':[{k:v for k,v in row.items() if k!='value'} for row in missing],
              'mappings':copy.deepcopy(mappings()),'control_pack':copy.deepcopy(pack()),
              'regulatory_sources':yaml.safe_load((ROOT/'semantic/regulatory_source_register.yaml').read_text()),
              'code_hashes':{name:_sha(ROOT/'02_backend/compliance'/name) for name in ('evaluator.py','applicability.py','calculations.py')},
              'input_hashes':inputs}
    result=assess_snapshot(snapshot)
    if include_snapshot:
        result['snapshot']=snapshot
    return result


def assess_snapshot(snapshot):
    """Deterministic evaluation using only retained inputs; no source or index reads."""
    if snapshot['engine_version']!=ENGINE_VERSION:
        raise ValueError('Unsupported assessment engine version')
    account=snapshot['account']; as_of=snapshot['as_of']
    controls=applicable_controls(account['booking_jurisdiction'],account['product'],as_of,snapshot['control_pack'])
    if not controls:
        return {'available':False,'reason':'No applicable control pack'}
    results=[]
    for control in controls:
        if control.get('evaluator') in {'ownership_graph','activity_deviation'}:
            from compliance.calculations import ownership,activity
            tables=snapshot.get('tables',{})
            if control['evaluator']=='ownership_graph':
                roots=tables.get('ownership_roots',[])
                calculation=ownership(roots[0]['root_party_id'],tables.get('ownership_parties',[]),tables.get('ownership_edges',[])) if len(roots)==1 else {
                    'outcome':'INSUFFICIENT_EVIDENCE','reason':'Missing or ambiguous ownership root','complete':False}
                used=['ownership_roots','ownership_parties','ownership_edges']
            else:
                profiles=tables.get('activity_profiles',[])
                calculation=activity(snapshot['account_id'],as_of,profiles[0],tables.get('activity_transactions',[]),tables.get('fx_rates',[])) if len(profiles)==1 else {
                    'outcome':'INSUFFICIENT_EVIDENCE','reason':'Missing or ambiguous activity profile','complete':False}
                used=['activity_profiles','activity_transactions','fx_rates']
            results.append({'control_id':control['id'],'control_version':control['effective_from'],
                            'classification':'DEMO','source_label':control['source_label'],'concept':control['concept'],
                            'outcome':calculation['outcome'],'reason':calculation['reason'],
                            'calculation':calculation,'source_tables':used,'evidence':[],
                            'missing_sources':[],'missing_evidence':[]})
            continue
        matched, blocked = [], []
        missing=[]
        for row in snapshot['missing_evidence']:
            mapping=resolve(row['source'],row['field'],control['concept'],account['booking_jurisdiction'],as_of,snapshot['mappings'])
            if mapping['status'] in ('resolved','ambiguous'):
                missing.append({**row,'mapping':mapping})
        for assertion in snapshot['assertions']:
            mapping = resolve(assertion['source'], assertion['field'], control['concept'],
                              account['booking_jurisdiction'], as_of,snapshot['mappings'])
            annotated = {**assertion, 'mapping':mapping}
            if mapping['status'] == 'resolved':
                matched.append(annotated)
            elif mapping['status'] == 'ambiguous':
                blocked.append(annotated)
        values = {a['value'].strip().casefold() for a in matched if a['value'].strip() and a['verified'].lower() == 'true'}
        required=control.get('required_sources',[])
        absent_sources=sorted(set(required)-{a['source'] for a in matched})
        if control.get('evaluator') not in {'consistent_assertions','evidence_present'} or not required:
            outcome, reason = 'REVIEW_REQUIRED', 'Unsupported evaluator or missing evidence requirements'
        elif blocked:
            outcome, reason = 'REVIEW_REQUIRED', 'Ambiguous approved source mapping'
        elif missing or absent_sources:
            outcome, reason = 'INSUFFICIENT_EVIDENCE', 'Required source evidence is missing, unreadable or incomplete'
        elif not matched:
            outcome, reason = 'INSUFFICIENT_EVIDENCE', 'No mapped evidence known at assessment time'
        elif any(a['verified'].lower() != 'true' or float(a['confidence']) < 0.8 for a in matched):
            outcome, reason = 'INSUFFICIENT_EVIDENCE', 'Unverified or low-confidence assertion'
        elif len(values) > 1:
            outcome, reason = 'CONFLICTING_EVIDENCE', 'Mapped sources disagree; no source was silently preferred'
        elif not values:
            outcome, reason = 'INSUFFICIENT_EVIDENCE', 'Mapped assertion is empty'
        else:
            outcome, reason = 'SATISFIED', 'Mapped verified evidence is present and consistent'
        results.append({'control_id':control['id'], 'control_version':control['effective_from'],
                        'classification':'DEMO', 'source_label':control['source_label'],
                        'concept':control['concept'], 'outcome':outcome, 'reason':reason,
                        'required_sources':required,'missing_sources':absent_sources,
                        'missing_evidence':missing,'evidence':matched+blocked})
    result={'available':True, 'classification':'DEMO', 'customer_id':snapshot['customer_id'],
            'account_id':snapshot['account_id'], 'as_of':as_of,
            'release_id':snapshot['release_id'], 'engine_version':ENGINE_VERSION,
            'booking_context':account, 'mapping_version':snapshot['mappings']['version'],
            'control_pack_version':snapshot['control_pack']['version'], 'input_hashes':snapshot['input_hashes'],
            'controls':results,
            'metrics':{'applicable_controls':len(results),
                       'satisfied_controls':sum(r['outcome']=='SATISFIED' for r in results),
                       'coverage':sum(r['outcome']=='SATISFIED' for r in results)/len(results),
                       'complete':all(r['outcome']=='SATISFIED' for r in results)}}
    if 'regulatory_sources' in snapshot:
        concepts={control['concept'] for control in results}
        candidates=[{'source_id':source['id'],'clause':link['clause'],
                     'concepts':sorted(concepts.intersection(link['business_concepts'])),
                     'relation':link['relation'],
                     'source_url':source.get('pdf_url') or source.get('repository_url') or source.get('reference_url',''),
                     'review_status':source['review_status']}
                    for source in snapshot['regulatory_sources']['sources']
                    if source['jurisdiction']==account['booking_jurisdiction']
                    for link in source['candidate_links']
                    if concepts.intersection(link['business_concepts'])]
        result['regulatory_linkage']={'status':'SOURCE_REVIEW_ONLY',
                                     'register_version':snapshot['regulatory_sources']['version'],
                                     'notice':snapshot['regulatory_sources']['notice'],
                                     'candidates':candidates}
    return result
