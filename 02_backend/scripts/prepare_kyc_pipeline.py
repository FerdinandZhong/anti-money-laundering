"""Optional local KYC preparation used by the existing CML generation job.

Generates native/scanned PDFs with real OCR by default, or consumes a supplied
manifest. Explicit markdown mode retains the lightweight demo. No model downloads
or remote Impala connections.
"""
import json
import os
from pathlib import Path
import sys

try:
    ROOT = Path(__file__).resolve().parents[2]
except NameError:
    ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / '02_backend'))
sys.path.insert(0, str(ROOT / '02_backend/scripts'))


def prepare():
    from knowledge.kb import build
    from prepare_kyc_knowledge import default_entries
    manifest_path = os.environ.get('AML_KYC_MANIFEST')
    mode = os.environ.get('AML_KYC_DOCUMENT_MODE', 'pdf')
    if mode not in ('pdf', 'markdown'):
        raise ValueError('AML_KYC_DOCUMENT_MODE must be pdf or markdown')
    generated = not manifest_path and mode == 'pdf'
    if generated:
        from prepare_control_documents import prepare as prepare_documents
        manifest_path = prepare_documents(ROOT / 'artifacts/kyc_poc/amp_documents', include_poc=False)
    if manifest_path:
        manifest = Path(manifest_path).resolve()
        entries = json.loads(manifest.read_text())
        for entry in entries:
            path = Path(entry['path'])
            if not path.is_absolute():
                entry['path'] = str(manifest.parent / path)
        source = str(manifest)
        if generated and os.environ.get('AML_KYC_EXPANDED_CORPUS', '1') == '1':
            from prepare_kyc_corpus import prepare as prepare_corpus
            from prepare_kyc_semantic_runtime import prepare as prepare_semantic
            corpus_dir = ROOT / 'artifacts/kyc_poc/amp_corpus'
            corpus_report = prepare_corpus(corpus_dir)
            corpus_entries = json.loads((corpus_dir/'knowledge_manifest.json').read_text())
            for entry in corpus_entries:
                entry['path'] = str(corpus_dir / entry['path'])
            entries.extend(corpus_entries)
            semantic_dir = Path(os.environ.get('AML_KYC_SEMANTIC_DIR', 'data/kyc_semantic_runtime'))
            if not semantic_dir.is_absolute():
                semantic_dir = ROOT / semantic_dir
            semantic_report = prepare_semantic(corpus_dir/'accounts.csv', semantic_dir)
        else:
            corpus_report = None
            semantic_report = None
    else:
        entries = default_entries(include_control_demo=True)
        source = 'synthetic Markdown records (not OCR)'
        corpus_report = None
        semantic_report = None
    result = build(entries, embedding_dir=os.environ.get('AML_EMBEDDING_MODEL_DIR'))
    report = {'status': 'ready', 'release_id': result['release_id'],
              'document_count': len(entries), 'source': source,
              'document_mode': 'generated_pdf_ocr' if generated else ('manifest' if manifest_path else 'markdown'),
              'expanded_corpus': corpus_report, 'semantic_source': semantic_report,
              'embedding_backend': result['embedding']['backend'],
              'remote_impala_executed': False}
    output = ROOT / 'artifacts/kyc_poc/pipeline_report.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    prepare()
