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
    from agents import workers, supervisor, narrator
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
    if '--live-decision' not in sys.argv:
        supervisor.chat = lambda messages, **kwargs: json.dumps({
            'activity_assessment': 'concerning', 'disposition': 'SUSPICIOUS',
            'reason': 'Concentrated outgoing activity and conflicting ownership records warrant escalation.',
            'finding_ids': [next(f['id'] for f in json.loads(messages[1]['content'])['findings']
                                 if f['concept'] == 'account_activity_patterns')]})
    def write_report(messages, **kwargs):
        inputs = json.loads(messages[-1]['content'])
        owner = next(f['id'] for f in inputs['findings'] if f['concept'] == 'beneficial_owner' and f['status'] == 'conflicting_evidence')
        screen = next(f['id'] for f in inputs['findings'] if f['concept'] == 'screening')
        return json.dumps({'decision': inputs['decision'],
            'overview': [{'text': 'Escalate the account for further investigation and resolve the outstanding ownership questions during that review.', 'finding_ids': [owner]}],
            'findings': [{'text': 'The ownership records identify different people as the person who ultimately owns or controls the company.', 'finding_ids': [owner]}],
            'significance': [{'text': 'The conflicting ownership information leaves an important question unanswered. Missing screening results also mean that those checks cannot yet inform the review.', 'finding_ids': [owner, screen]}],
            'actions': [{'text': 'Reconcile the ownership records and obtain dated screening results before deciding how to proceed.', 'finding_ids': [owner, screen]}]})
    if '--live-narrator' not in sys.argv:
        narrator.chat = write_report
    else:
        live_chat = narrator.chat
        def capture_narration(*args, **kwargs):
            response = live_chat(*args, **kwargs)
            (output / 'narrator-response.json').write_text(response)
            return response
        narrator.chat = capture_narration
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
            report = page.get_by_role('article', name='Investigation report')
            report.wait_for(timeout=90000)
            assert 'source contract' not in report.inner_text()
            assert 'failed workers' not in report.inner_text()
            assert 'Escalate for further investigation' in report.inner_text()
            assert 'Supporting information: Additional information required' in report.inner_text()
            assert page.locator('#investigation-details').get_attribute('open') is None
            (output / 'business-report.txt').write_text(report.inner_text())
            from common.evidence import get_evidence
            with sqlite3.connect(database) as check:
                eid = check.execute("SELECT evidence_id FROM evidence WHERE tool='investigation_report' ORDER BY rowid DESC LIMIT 1").fetchone()[0]
            retained = get_evidence(eid)['payload']
            assert retained['business_report']['mode'] == 'narrated', 'Narrator fell back; inspect model response'
            (output / 'business-report.json').write_text(json.dumps(retained['business_report'], indent=2))
            page.screenshot(path=str(output / 'business-report.png'), full_page=True)
            report.get_by_role('button', name='View supporting findings').first.click()
            page.get_by_role('button', name='Show all findings', exact=True).click()
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
            page.get_by_role('article', name='Investigation report').wait_for()
            assert page.locator('#investigation-details').get_attribute('open') is None
            page.get_by_text('Detailed findings and evidence', exact=True).click()
            page.get_by_text('Account Recorded Outflow By Currency', exact=True).wait_for()
            assert page.get_by_role('button', name='Inspect retained inputs', exact=True).count() > 0
            assert not errors, errors
            browser.close()
        print(json.dumps({'status': 'passed', 'checks': ['business report first', 'details collapsed', 'paragraph source navigation', 'live findings', 'owner conflict', 'document links',
            'retained payload integrity', 'saved report reload', 'no browser errors'],
            'llm': {'narrator': 'live' if '--live-narrator' in sys.argv else 'stubbed',
                    'decision': 'live' if '--live-decision' in sys.argv else 'stubbed',
                    'workers': 'stubbed'}, 'ops_db': 'temporary copy', 'screenshot': str(output / 'findings.png')}))


if __name__ == '__main__':
    main()
