"""Immutable LanceDB releases with customer/account/time-scoped evidence access."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from common.config import get_config, PROJECT_ROOT
from knowledge.embeddings import digest, load

ID = re.compile(r'[A-Za-z0-9_-]{1,100}')


class Unavailable(RuntimeError):
    pass


def root_path():
    configured = os.environ.get('AML_KNOWLEDGE_DIR') or get_config().get('knowledge', {}).get('directory', 'data/knowledge')
    path = Path(configured).expanduser()
    return path if path.is_absolute() else Path(PROJECT_ROOT) / path


def valid_id(value):
    if not ID.fullmatch(value):
        raise ValueError('Invalid evidence identifier')
    return value


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec='microseconds')


def tokens(text):
    # Explicit portable segmentation: Latin words/IDs + Chinese runs/bigrams.
    words = re.findall(r'[a-z0-9]+|[\u3400-\u9fff]+', text.lower())
    result = []
    for word in words:
        result.append(word)
        if re.search(r'[\u3400-\u9fff]', word) and len(word) > 2:
            result.extend(word[i:i + 2] for i in range(len(word) - 1))
    return ' '.join(result)


def build(entries, root=None, embedding_dir=None):
    """Trusted build-time manifest. Assets are copied; runtime never reads input paths.

    Each entry: document_id/customer_id/title/path/received_at and pages with
    page/text/evidence. No generator truth is consumed by this module.
    """
    import hashlib
    import lancedb
    import pyarrow as pa
    root = Path(root or root_path())
    root.mkdir(parents=True, exist_ok=True)
    embedder = load(embedding_dir) if embedding_dir else None
    metadata = embedder.metadata if embedder else {'backend': 'none'}
    documents, chunks, inputs = [], [], {}
    seen = set()
    for entry in entries:
        customer = valid_id(entry['customer_id'])
        account = valid_id(entry['account_id']) if entry.get('account_id') else ''
        document = valid_id(entry['document_id'])
        path = Path(entry['path']).resolve()
        if path.suffix.lower() not in {'.pdf', '.png', '.jpg', '.jpeg', '.md', '.txt'}:
            raise ValueError('Unsupported asset type')
        sha = digest(path)
        version = document + '-' + sha[:16]
        valid_id(version)
        if version in seen:
            raise ValueError('Duplicate document version')
        seen.add(version)
        received = timestamp(entry['received_at'])
        asset = f'objects/{sha}{path.suffix.lower()}'
        inputs[asset] = path
        common = {'document_id': document, 'version_id': version, 'customer_id': customer,
                  'account_id': account, 'received_at': received, 'title': entry['title'],
                  'source': entry.get('source', 'Synthetic KYC evidence'),
                  'language': entry.get('language', 'unknown'),
                  'provenance': entry.get('provenance', ''), 'sha256': sha,
                  'illustrative': bool(entry.get('illustrative', False))}
        pages = entry['pages']
        if not pages or len({p['page'] for p in pages}) != len(pages):
            raise ValueError('Missing or duplicate pages')
        documents.append({**common, 'asset': asset, 'page_count': len(pages), 'media_type': {
            '.pdf':'application/pdf', '.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg',
            '.md':'text/plain', '.txt':'text/plain'}[path.suffix.lower()]})
        for page in pages:
            if not isinstance(page['page'], int) or page['page'] < 1:
                raise ValueError('Invalid page number')
            text = str(page['text'])
            # Bounded overlapping character chunks; citations retain whole page evidence.
            for part, start in enumerate(range(0, max(1, len(text)), 1000)):
                snippet = text[start:start + 1200]
                chunks.append({**common, 'chunk_id': f'{version}-p{page["page"]}-{part}',
                               'page': page['page'], 'text': snippet, 'search_text': tokens(snippet),
                               'evidence_json': json.dumps(page.get('evidence', []), ensure_ascii=False)})
    if not chunks:
        raise ValueError('Empty corpus')
    documents.sort(key=lambda x:x['version_id']); chunks.sort(key=lambda x:x['chunk_id'])
    fingerprint = json.dumps({'documents': documents, 'chunks': chunks, 'embedding': metadata,
                              'schema': 1, 'tokenizer': 'bilingual_v1'}, sort_keys=True, ensure_ascii=False)
    release = 'kyc-' + hashlib.sha256(fingerprint.encode()).hexdigest()[:20]
    target = root / 'releases' / release
    if not target.exists():
        stage = Path(tempfile.mkdtemp(prefix='.build-', dir=root))
        try:
            for relative, source in inputs.items():
                dest = stage / relative; dest.parent.mkdir(exist_ok=True)
                shutil.copyfile(source, dest)
                if digest(dest) != dest.stem:
                    raise ValueError('Asset changed during ingestion')
            if embedder:
                vectors = embedder.encode([r['text'] for r in chunks])
                for row, vector in zip(chunks, vectors):
                    row['vector'] = vector
            db = lancedb.connect(str(stage / 'lance'))
            db.create_table('documents', pa.Table.from_pylist(documents))
            table = pa.Table.from_pylist(chunks)
            if embedder:
                table = table.set_column(table.schema.get_field_index('vector'), 'vector',
                                         pa.array([r['vector'] for r in chunks], type=pa.list_(pa.float32(), 1024)))
            db.create_table('chunks', table).create_fts_index('search_text', stem=False, remove_stop_words=False, ascii_folding=False)
            manifest = {'release_id': release, 'schema_version': 1, 'documents':len(documents),
                        'chunks':len(chunks), 'embedding':metadata, 'tokenizer':'bilingual_v1'}
            (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2))
            target.parent.mkdir(exist_ok=True)
            stage.rename(target)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    # The only mutable pointer is activated after complete ingestion/indexing.
    pointer = root / ('.current-' + uuid.uuid4().hex)
    pointer.write_text(json.dumps({'release_id':release}))
    os.replace(pointer, root / 'current.json')
    return json.loads((target / 'manifest.json').read_text())


class Store:
    def __init__(self, root=None, release=None):
        self.root = Path(root or root_path())
        try:
            import lancedb
            release = valid_id(release) if release else valid_id(json.loads((self.root/'current.json').read_text())['release_id'])
            self.path = self.root/'releases'/release
            self.manifest = json.loads((self.path/'manifest.json').read_text())
            if self.manifest['release_id'] != release:
                raise ValueError('Release mismatch')
            self.db = lancedb.connect(str(self.path/'lance'))
            self.docs = self.db.open_table('documents')
            self.chunks = self.db.open_table('chunks')
        except (ImportError, OSError, KeyError, ValueError, RuntimeError) as exc:
            raise Unavailable('KYC knowledge release unavailable; run prepare_kyc_knowledge.py') from exc

    def scope(self, customer, account=None, as_of=None):
        filt = f"customer_id = '{valid_id(customer)}'"
        if account:
            filt += f" AND (account_id = '' OR account_id = '{valid_id(account)}')"
        else:
            filt += " AND account_id = ''"
        if as_of:
            filt += f" AND received_at <= '{timestamp(as_of)}'"
        return filt

    def public(self, row):
        result = {k:v for k,v in row.items() if k not in {'vector','search_text','asset','customer_id','account_id','evidence_json'} and not k.startswith('_')}
        if 'evidence_json' in row:
            result['evidence'] = json.loads(row['evidence_json'])
        return result

    def page(self, customer, version, page, account=None):
        if page < 1:
            raise ValueError('Page must be positive')
        filt = self.scope(customer,account)+f" AND version_id = '{valid_id(version)}' AND page = {int(page)}"
        rows = self.chunks.search().where(filt).limit(10000).to_list()
        if not rows:
            raise KeyError('Page not found in alert scope')
        return [self.public(r) for r in sorted(rows,key=lambda r:r['chunk_id'])]

    def documents(self, customer, account=None, as_of=None):
        rows = self.docs.search().where(self.scope(customer,account,as_of)).limit(10000).to_list()
        return sorted([self.public(r) for r in rows],key=lambda r:(r['document_id'],r['received_at'],r['version_id']))

    def asset(self, customer, version, account=None, as_of=None):
        filt = self.scope(customer,account,as_of)+f" AND version_id = '{valid_id(version)}'"
        rows = self.docs.search().where(filt).limit(1).to_list()
        if not rows:
            raise KeyError('Document not found in alert scope')
        row = rows[0]
        path = (self.path / row['asset']).resolve()
        if not path.is_relative_to((self.path/'objects').resolve()):
            raise Unavailable('Document integrity check failed')
        try:
            if digest(path) != row['sha256']:
                raise Unavailable('Document integrity check failed')
        except OSError as exc:
            raise Unavailable('Document asset unavailable') from exc
        return path, row['media_type']

    def search(self, customer, query, account=None, as_of=None, limit=10):
        if not query.strip() or len(query)>1000 or not 1<=limit<=50:
            raise ValueError('Query must be 1–1000 characters; limit must be 1–50')
        filt = self.scope(customer,account,as_of)
        lexical = tokens(query)
        candidates = self.chunks.search(lexical,query_type='fts',fts_columns='search_text').where(filt,prefilter=True).limit(50).to_list() if lexical else []
        ranked = [candidates]
        mode, reason = 'keyword', 'This release has no semantic embeddings.'
        metadata = self.manifest['embedding']
        if metadata['backend'] != 'none':
            try:
                directory = os.environ.get('AML_EMBEDDING_MODEL_DIR') or get_config().get('knowledge',{}).get('embedding_model_dir') or metadata['model_dir']
                embedder = load(directory)
                for key in ['backend','dimension','model_sha256','tokenizer_sha256','max_tokens']:
                    if embedder.metadata[key] != metadata[key]:
                        raise ValueError('Embedding manifest mismatch')
                vector = embedder.encode([query])[0]
                ranked.append(self.chunks.search(vector).distance_type('cosine').where(filt,prefilter=True).limit(50).to_list())
                mode, reason = 'hybrid', None
            except Exception:
                reason = 'Semantic model unavailable or mismatched; keyword results only.'
        # Reciprocal rank fusion; vector distances and BM25 scores are not comparable.
        scores, rows = {}, {}
        for hits in ranked:
            for rank,row in enumerate(hits,1):
                key = row['chunk_id']; rows[key] = row
                scores[key] = scores.get(key,0) + 1/(60+rank)
        keys = sorted(rows,key=lambda k:(-scores[k],k))[:limit]
        return {'available':True,'release_id':self.manifest['release_id'],'mode':mode,'note':reason,
                'hits':[{**self.public(rows[k]),'retrieval_score':scores[k]} for k in keys]}
