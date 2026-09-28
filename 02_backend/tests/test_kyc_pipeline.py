"""Local preparation and CML environment handoff without remote service calls."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_pipeline_manifest_is_relative_and_idempotent(tmp_path, monkeypatch):
    pipeline = module('pipeline', '02_backend/scripts/prepare_kyc_pipeline.py')
    monkeypatch.setattr(pipeline, 'ROOT', tmp_path)
    monkeypatch.setenv('AML_KNOWLEDGE_DIR', str(tmp_path / 'kb'))
    monkeypatch.delenv('AML_EMBEDDING_MODEL_DIR', raising=False)
    (tmp_path / 'record.txt').write_text('受益所有人 Lin Mei')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps([{'document_id': 'document', 'customer_id': 'customer',
                                    'title': 'Test', 'path': 'record.txt', 'received_at': '2026-09-01',
                                    'pages': [{'page': 1, 'text': '受益所有人 Lin Mei'}]}]))
    monkeypatch.setenv('AML_KYC_MANIFEST', str(manifest))
    first = pipeline.prepare()
    second = pipeline.prepare()
    assert first['release_id'] == second['release_id']
    assert first['embedding_backend'] == 'none'
    assert not first['remote_impala_executed']
    assert (tmp_path / 'artifacts/kyc_poc/pipeline_report.json').exists()


def test_cml_environment_reaches_generation_and_application(monkeypatch):
    jobs = module('jobs', 'cai_integration/create_jobs.py')
    deploy = module('deploy', 'cai_integration/deploy_application.py')
    for key, value in {'AML_PREPARE_KYC': '1', 'AML_KYC_MANIFEST': '/data/manifest.json',
                       'AML_ENABLE_KYC_DEMO_CONTROLS': '1', 'AML_KNOWLEDGE_DIR': '/data/knowledge',
                       'AML_EMBEDDING_MODEL_DIR': '/data/model'}.items():
        monkeypatch.setenv(key, value)
    manager = jobs.JobManager.__new__(jobs.JobManager)
    manager.runtime_identifier = 'python-runtime'
    manager.list_jobs = lambda project: {}
    created = {}
    def create(project, config, parent, runtime):
        created[config['name']] = config
        return config['name']
    manager.create_job = create
    manager.create_or_update_jobs('project', {'jobs': {
        'install': {'name': 'install'}, 'generate': {'name': 'generate'},
        'launch': {'name': 'launch', 'parent_job_key': 'generate'}}})
    assert created['install']['environment']['AML_PREPARE_KYC'] == '1'
    assert created['generate']['environment']['AML_KYC_MANIFEST'] == '/data/manifest.json'
    assert created['launch']['environment']['AML_ENABLE_KYC_DEMO_CONTROLS'] == '1'
    app = deploy.build_environment('7078', None)
    assert app['AML_KNOWLEDGE_DIR'] == '/data/knowledge'
    assert app['AML_EMBEDDING_MODEL_DIR'] == '/data/model'
    assert 'AML_PREPARE_KYC' not in app


def test_amp_defaults_install_ocr_and_allow_opt_out(monkeypatch):
    import yaml
    template = yaml.safe_load((ROOT / '.project-metadata.yaml').read_text())
    for name, spec in template['environment_variables'].items():
        monkeypatch.setenv(name, str(spec['default']))
    assert template['environment_variables']['AML_ENABLE_KYC_DEMO_CONTROLS']['default'] == '1'
    installer = module('installer', '01_installer/install.py')
    calls = []
    monkeypatch.setattr(installer.subprocess, 'check_call', lambda args: calls.append(args))
    installer.install_python_deps()
    installer.validate_python_deps()
    installs = [args for args in calls if 'pip' in args]
    assert len(installs) == 1
    assert any(arg.endswith('requirements.txt') for arg in installs[0])
    assert any(arg.endswith('requirements-kyc-runtime.txt') for arg in installs[0])
    assert calls[-1][-1] == '--ocr'
    assert calls[-1][-2].endswith('check_python_runtime.py')
    monkeypatch.setenv('AML_PREPARE_KYC', '0')
    assert installer.kyc_requirements() == []
    calls.clear()
    installer.validate_python_deps()
    assert calls[0][-1].endswith('check_python_runtime.py')
    monkeypatch.setenv('AML_PREPARE_KYC', '1')
    monkeypatch.setenv('AML_KYC_DOCUMENT_MODE', 'markdown')
    assert installer.kyc_requirements() == []
    monkeypatch.setenv('AML_EMBEDDING_MODEL_DIR', '/model')
    assert installer.kyc_requirements() == ['requirements-kyc-embeddings.txt']


def test_amp_pdf_bootstrap_real_extraction(tmp_path, monkeypatch):
    import pytest
    pytest.importorskip('rapidocr_onnxruntime')
    import fitz
    from knowledge.kb import Store
    from compliance.evaluator import evaluate
    pipeline = module('pipeline_pdf', '02_backend/scripts/prepare_kyc_pipeline.py')
    monkeypatch.setattr(pipeline, 'ROOT', tmp_path)
    monkeypatch.setenv('AML_KNOWLEDGE_DIR', str(tmp_path / 'knowledge'))
    monkeypatch.setenv('AML_KYC_DOCUMENT_MODE', 'pdf')
    monkeypatch.setenv('AML_KYC_EXPANDED_CORPUS', '0')
    monkeypatch.delenv('AML_KYC_MANIFEST', raising=False)
    monkeypatch.delenv('AML_EMBEDDING_MODEL_DIR', raising=False)
    # A fresh checkout has no legacy generated dossiers or extraction POC outputs.
    import prepare_control_documents
    monkeypatch.setattr(prepare_control_documents, 'default_entries', lambda **kw: [])
    report = pipeline.prepare()
    assert report['document_mode'] == 'generated_pdf_ocr'
    assert report['document_count'] == 5
    store = Store(root=tmp_path / 'knowledge')
    documents = store.documents('CUST-000294', 'ACC-0000294')
    declaration = next(doc for doc in documents if doc['document_id'] == 'control-demo-sg-declaration')
    path, media = store.asset('CUST-000294', declaration['version_id'], 'ACC-0000294')
    assert media == 'application/pdf'
    with fitz.open(path) as pdf:
        assert all(not page.get_text().strip() for page in pdf)
    evidence = store.page('CUST-000294', declaration['version_id'], 2, 'ACC-0000294')
    assert any(item['method'] == 'rapidocr' for chunk in evidence for item in chunk['evidence'])
    result = evaluate('CUST-000294', 'ACC-0000294', '2026-09-12T10:31:21Z')
    assert result['available']
    owner = next(control for control in result['controls'] if control['control_id'] == 'DEMO-SG-OWNER')
    assert owner['outcome'] == 'CONFLICTING_EVIDENCE'


def test_registered_jobs_match_amp_defaults_and_forward_branch(monkeypatch):
    import yaml
    jobs = module('jobs_defaults', 'cai_integration/create_jobs.py')
    template = yaml.safe_load((ROOT / '.project-metadata.yaml').read_text())
    for key in template['environment_variables']:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('GIT_SYNC_BRANCH', 'feature/semantic-demo-explorer')
    manager = jobs.JobManager.__new__(jobs.JobManager)
    manager.runtime_identifier = 'python-runtime'
    manager.list_jobs = lambda project: {}
    created = {}
    def create(project, config, parent, runtime):
        created[config['name']] = config
        return config['name']
    manager.create_job = create
    manager.create_or_update_jobs('project', manager.load_jobs_config())
    for job in created.values():
        for key, value in job.get('environment', {}).items():
            if key.startswith('AML_'):
                assert value == template['environment_variables'][key]['default']
    assert created['Install Dependencies']['environment']['AML_PREPARE_KYC'] == '1'
    assert created['Generate Synthetic Data']['environment']['AML_KYC_EXPANDED_CORPUS'] == '1'
    assert created['Launch Application']['environment']['AML_ENABLE_KYC_DEMO_CONTROLS'] == '1'
    assert created['Git Repository Sync']['environment']['GIT_SYNC_BRANCH'] == 'feature/semantic-demo-explorer'
    monkeypatch.setenv('AML_PREPARE_KYC', '0')
    manager.create_or_update_jobs('project', manager.load_jobs_config())
    assert created['Install Dependencies']['environment']['AML_PREPARE_KYC'] == '0'
    assert created['Generate Synthetic Data']['environment']['AML_PREPARE_KYC'] == '0'
