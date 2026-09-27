"""Evaluate frozen bilingual/identifier queries against a pinned local release."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

try:
    ROOT = Path(__file__).resolve().parents[2]
except NameError:
    ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / '02_backend'))
from knowledge.kb import Store, timestamp


def benchmark(root, queries, release=None):
    source = queries.read_bytes()
    dataset = json.loads(source)
    store = Store(root=root, release=release)
    rows = []
    for query in dataset['queries']:
        result = store.search(query['customer_id'], query['query'], query.get('account_id'),
                              query['as_of'], limit=5)
        expected = query['expected_document_id']
        excluded = query.get('excluded_document_id')
        if expected:
            # Reject invalid gold labels instead of silently reporting a retrieval miss.
            gold = [doc for doc in store.documents(query['customer_id'], query.get('account_id'), query['as_of'])
                    if doc['document_id'] == expected and (not query.get('expected_received_at') or
                       timestamp(doc['received_at']) == timestamp(query['expected_received_at']))]
            if not gold:
                raise ValueError(f"Gold document outside indexed scope: {query['id']}")
            versions = {doc['version_id'] for doc in gold}
            ranks=[index for index,hit in enumerate(result['hits'],1) if hit['version_id'] in versions]
            passed = bool(ranks)
        else:
            ranks=[]
            passed = (not any(hit['document_id']==excluded for hit in result['hits'])) if excluded else not result['hits']
        rows.append({'id': query['id'], 'category': query['category'], 'passed': passed,
                     'reciprocal_rank':1/ranks[0] if ranks else 0,
                     'mode': result['mode'], 'expected_document_id': expected,
                     'hits': [{'document_id': hit['document_id'], 'version_id': hit['version_id'],
                               'page': hit['page']} for hit in result['hits']]})
    positives = [row for row in rows if row['expected_document_id']]
    negatives = [row for row in rows if not row['expected_document_id']]
    recall = sum(row['passed'] for row in positives) / len(positives)
    return {'benchmark_version': dataset['version'], 'query_sha256': hashlib.sha256(source).hexdigest(),
            'release_id': store.manifest['release_id'], 'queries': len(rows),
            'positive_queries': len(positives), 'recall_at_5': recall,
            'mrr_at_5':sum(row['reciprocal_rank'] for row in positives)/len(positives),
            'negative_queries': len(negatives), 'negative_passes': sum(row['passed'] for row in negatives),
            'target_recall_at_5': .9, 'target_met': recall >= .9 and all(row['passed'] for row in negatives),
            'by_category': {category: {'passed': sum(row['passed'] for row in rows if row['category'] == category),
                                      'total': sum(row['category'] == category for row in rows)}
                            for category in sorted({row['category'] for row in rows})},
            'limitations': 'Synthetic template corpus; not a held-out production accuracy or OCR field-accuracy evaluation.',
            'results': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--release')
    parser.add_argument('--queries', type=Path, default=ROOT / 'data/kyc_benchmark/queries.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = benchmark(args.root, args.queries, args.release)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'results'}, indent=2))
    if not report['target_met']:
        raise SystemExit(1)
