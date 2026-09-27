"""Build a local immutable KYC release; no remote writes or model downloads.

Default imports synthetic Markdown dossiers. --include-poc explicitly associates
illustrative extraction fixtures with the showcase customer, labeled as such.
--manifest accepts a JSON list of document entries with explicit scope/dates/pages.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

try:
    ROOT = Path(__file__).resolve().parents[2]
except NameError:
    ROOT = Path.cwd()
sys.path.insert(0, str(ROOT/'02_backend'))

from knowledge.kb import build
from knowledge.demo_records import entries as control_demo_entries


def default_entries(include_poc=False, include_control_demo=False):
    entries = []
    for path in sorted((ROOT/'data/kyc_documents').glob('*/*.md')):
        entries.append({'document_id':path.parent.name+'-'+path.stem.replace('_','-'),
                        'customer_id':path.parent.name, 'title':path.stem.replace('_',' ').title(),
                        'path':str(path),'received_at':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),
                        'source':'Synthetic onboarding record', 'language':'en',
                        'provenance':'Imported local Markdown; received_at is import file modification time, not an asserted historical receipt date.',
                        'pages':[{'page':1,'text':path.read_text(),'evidence':[]} ]})
    if include_poc:
        for path in sorted((ROOT/'artifacts/kyc_poc/extraction').glob('*.pdf.extracted.json')):
            extracted = json.loads(path.read_text())
            pdf = path.with_name(path.name.removesuffix('.extracted.json'))
            groups = {}
            for line in extracted['lines']:
                groups.setdefault(line['page'],[]).append(line)
            entries.append({'document_id':'poc-'+pdf.stem.replace('_','-'), 'customer_id':'CUST-000294',
                            'title':'Illustrative KYC sample: '+pdf.stem.replace('_',' '), 'path':str(pdf),
                            'received_at':'2026-09-01T00:00:00Z','source':'Synthetic extraction fixture',
                            'illustrative':True,'language':pdf.stem.split('_')[0],
                            'provenance':'Illustrative fictional company, attached for retrieval testing. Not a verified identity record of Corp_0294. Receipt date is a scenario assumption. OCR can contain errors.',
                            'pages':[{'page':n,'text':'\n'.join(x['text'] for x in lines),'evidence':lines} for n,lines in groups.items()]})
    if include_control_demo:
        entries.extend(control_demo_entries())
    return entries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--include-poc',action='store_true')
    parser.add_argument('--include-control-demo',action='store_true',
                        help='Index synthetic SG/HK control source records')
    parser.add_argument('--embedding-model-dir',default=os.environ.get('AML_EMBEDDING_MODEL_DIR'))
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.manifest:
        entries=json.loads(args.manifest.read_text())
        for entry in entries:
            path=Path(entry['path'])
            if not path.is_absolute(): entry['path']=str(args.manifest.parent/path)
    else:
        entries=default_entries(args.include_poc,args.include_control_demo)
    result=build(entries,root=args.output,embedding_dir=args.embedding_model_dir)
    print(json.dumps({k:v for k,v in result.items() if k!='embedding'},indent=2))
    print('Retrieval:', 'hybrid' if result['embedding']['backend']!='none' else 'keyword (no embedding model configured)')


if __name__=='__main__':
    main()
