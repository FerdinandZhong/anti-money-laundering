"""Real API + built UI over an isolated ops copy, with a deterministic LLM stub.

Does not exercise remote LLM quality, AMP or Impala. Run from the project root.
"""
import json
import mimetypes
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from urllib.parse import urlsplit

try:
    ROOT = Path(__file__).resolve().parents[2]
except NameError:
    ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / '02_backend'))


def main():
    from fastapi.testclient import TestClient
    from playwright.sync_api import sync_playwright
    from common import db, source
    from agents import workers, supervisor
    original = db.get_db_path()
    output = ROOT / 'artifacts/investigation'
    output.mkdir(parents=True, exist_ok=True)
    source._backend = 'csv'
    os.environ['AML_ENABLE_KYC_DEMO_CONTROLS'] = '1'

    def interpret(messages, **kwargs):
        inputs = json.loads(messages[-1]['content'])
        return json.dumps({'interpretations': [{'finding_id': item['id'],
            'text': 'Use the retained sources and the stated scope when reviewing this observation.'}
            for item in inputs['findings']]})
    supervisor.chat = lambda messages, **kwargs: json.dumps({
        'disposition': 'NEEDS_MORE_INFO',
        'finding_ids': [json.loads(messages[-1]['content'])['findings'][0]['id']]})
    workers.chat = interpret
    supervisor.run_verification_worker = lambda *args: None
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / 'aml.db'
        src = sqlite3.connect(original); dst = sqlite3.connect(database)
        src.backup(dst); src.close()
        dst.execute("UPDATE alerts SET status='PENDING' WHERE customer_id!='CUST-000294'")
        dst.execute("UPDATE alerts SET status='OPEN' WHERE customer_id='CUST-000294'")
        dst.commit(); dst.close()
        db.get_db_path = lambda: str(database)
        from api.main import app
        client = TestClient(app)
        errors = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1550, 'height': 1050})
            def route_request(route):
                request = route.request; url = urlsplit(request.url)
                if url.path.startswith('/api/'):
                    response = client.request(request.method, url.path + ('?' + url.query if url.query else ''),
                        content=request.post_data or None, headers={'content-type': 'application/json'})
                    route.fulfill(status=response.status_code, body=response.content,
                                  content_type=response.headers.get('content-type', 'application/json'))
                else:
                    asset = ROOT / '03_frontend/dist' / url.path.lstrip('/')
                    if not asset.is_file():
                        asset = ROOT / '03_frontend/dist/index.html'
                    route.fulfill(body=asset.read_bytes(), content_type=mimetypes.guess_type(str(asset))[0] or 'application/octet-stream')
            context.route('**/*', route_request)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto('http://aml.local/investigation')
            page.get_by_text('CUST-000294', exact=True).first.click(timeout=30000)
            page.get_by_role('tab', name='AI Findings', exact=True).click()
            page.get_by_role('button', name='Run inference', exact=True).click()
            page.get_by_text('Investigation summary', exact=True).wait_for(timeout=60000)
            page.get_by_text('Account Recorded Outflow By Currency', exact=True).wait_for()
            page.get_by_text('Conflicting Evidence', exact=True).first.wait_for()
            page.get_by_text('Meaning and source evidence', exact=True).first.click()
            assert page.locator('a[href*="/knowledge/assets/"]').count() > 0
            page.get_by_role('button', name='Inspect retained inputs', exact=True).first.click()
            page.get_by_role('button', name='Hide retained inputs', exact=True).first.wait_for()
            assert '"integrity_valid": true' in page.locator('pre').first.inner_text()
            page.get_by_role('button', name='Hide retained inputs', exact=True).first.click()
            page.screenshot(path=str(output / 'findings.png'), full_page=True)
            page.reload()
            page.get_by_text('CUST-000294', exact=True).first.click(timeout=30000)
            page.get_by_role('tab', name='AI Findings', exact=True).click()
            page.get_by_text('Account Recorded Outflow By Currency', exact=True).wait_for()
            assert page.get_by_role('button', name='Inspect retained inputs', exact=True).count() > 0
            assert not errors, errors
            browser.close()
        print(json.dumps({'status': 'passed', 'checks': ['live findings', 'owner conflict', 'document links',
            'retained payload integrity', 'saved report reload', 'no browser errors'],
            'llm': 'stubbed', 'ops_db': 'temporary copy', 'screenshot': str(output / 'findings.png')}))


if __name__ == '__main__':
    main()
