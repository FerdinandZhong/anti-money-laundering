"""Import synthetic control source records as versioned LanceDB documents.

CSV supplies scope and receipt metadata. Searchable page text comes only from
the source record, so the evaluator cannot read a CSV answer value as evidence.
"""
import csv
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'data/kyc_semantic_demo'


def document_id(source_ref):
    stem = Path(source_ref).stem
    if re.fullmatch(r'corpus-\d{3}-(registry|mandate|funding|wealth|review)-v[12]', stem):
        return stem.rsplit('-v',1)[0]
    return 'control-demo-' + stem.replace('_', '-')


def record_pages(content):
    markers = list(re.finditer(r'(?m)^Page ([1-9][0-9]*)\s*$', content))
    if not markers:
        raise ValueError('Synthetic source record has no page marker')
    result = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(content)
        result.append({'page':int(marker.group(1)), 'text':content[marker.end():end].strip(),
                       'evidence':[{'method':'source_record_parser','page':int(marker.group(1))}]})
    if len({page['page'] for page in result}) != len(result):
        raise ValueError('Duplicate source-record page')
    return result


def entries(fixtures=FIXTURES):
    fixtures = Path(fixtures)
    with (fixtures/'assertions.csv').open(newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    groups = {}
    for row in rows:
        reference = Path(row['source_ref'])
        path = (fixtures/reference).resolve()
        if not path.is_relative_to((fixtures/'records').resolve()) or path.suffix != '.md':
            raise ValueError('Invalid synthetic source record path')
        prior = groups.setdefault(str(reference), row)
        for field in ('customer_id','account_id','received_at'):
            if prior[field] != row[field]:
                raise ValueError('Conflicting source record metadata')
    return [{'document_id':document_id(ref), 'customer_id':row['customer_id'],
             'account_id':row['account_id'], 'title':'Synthetic control source: '+Path(ref).stem.replace('_',' '),
             'path':str((fixtures/ref).resolve()), 'received_at':row['received_at'],
             'source':'Synthetic control source record', 'language':'mixed',
             'provenance':'Synthetic demo input; values parsed from this document at evaluation time.',
             'illustrative':True, 'pages':record_pages((fixtures/ref).read_text(encoding='utf-8'))}
            for ref,row in sorted(groups.items())]
