"""Browser acceptance using the real API over a temporary copy of the ops DB.

No listening socket, remote service, or live ops mutation: browser requests are
fulfilled by FastAPI TestClient and the built frontend assets.
"""
import json
import mimetypes
import os
import re
from pathlib import Path
import sqlite3
import sys
import tempfile
from urllib.parse import urlsplit

try:
    ROOT=Path(__file__).resolve().parents[2]
except NameError:
    ROOT=Path.cwd()
sys.path.insert(0,str(ROOT/'02_backend'))


def main():
    from fastapi.testclient import TestClient
    from playwright.sync_api import sync_playwright
    from common import db,source
    original=db.get_db_path()
    output=ROOT/'artifacts/kyc_poc/control_documents'
    output.mkdir(parents=True,exist_ok=True)
    os.environ['AML_ENABLE_KYC_DEMO_CONTROLS']='1'
    source._backend='csv'
    with tempfile.TemporaryDirectory() as temp:
        database=Path(temp)/'aml.db'
        src=sqlite3.connect(original);dst=sqlite3.connect(database)
        src.backup(dst);src.close()
        # Make the showcase visible in the copied test queue, without altering its score.
        dst.execute("UPDATE alerts SET status='PENDING' WHERE customer_id!='CUST-000294'")
        dst.execute("UPDATE alerts SET status='OPEN' WHERE alert_id='ALERT-ML-0466899666'")
        dst.commit();dst.close()
        db.get_db_path=lambda:str(database)
        from api.main import app
        client=TestClient(app)
        errors=[]
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            context=browser.new_context(viewport={'width':1600,'height':1000},accept_downloads=True)
            def route_request(route):
                request=route.request; url=urlsplit(request.url)
                if url.path.startswith('/api/'):
                    response=client.request(request.method,url.path+('?' + url.query if url.query else ''),content=request.post_data or None,
                                            headers={'content-type':request.headers.get('content-type','application/json')})
                    route.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','application/json'))
                else:
                    asset=ROOT/'03_frontend/dist'/url.path.lstrip('/')
                    if not asset.is_file():asset=ROOT/'03_frontend/dist/index.html'
                    route.fulfill(body=asset.read_bytes(),content_type=mimetypes.guess_type(str(asset))[0] or 'application/octet-stream')
            context.route('**/*',route_request)
            page=context.new_page()
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto('http://aml.local/investigation')
            page.get_by_text('CUST-000294',exact=True).first.click(timeout=30000)
            page.get_by_role('tab',name='Semantic context',exact=True).click()
            for heading in ['What this account data says','How the data connects','Ossie source files']:
                page.get_by_role('heading',name=heading,exact=True).wait_for()
            assert not re.search(r'\b(synthetic|demo)\b',page.get_by_role('heading',name='What this account data says').locator('..').inner_text(),re.I)
            graph=page.get_by_label('Ossie model and data lineage graph')
            graph.get_by_role('button',name='aml.accounts Account').wait_for()
            assert graph.get_by_role('button').count()==7
            graph.get_by_role('button',name='aml.transactions Transaction').click()
            page.get_by_text('Records monetary movement used to calculate observed activity.',exact=False).wait_for()
            page.get_by_text('transaction_id',exact=True).wait_for()
            graph.get_by_role('button',name='LanceDB · PDF / OCR KYC page index').click()
            page.get_by_text('document versions linked to this customer/account',exact=False).wait_for()
            page.get_by_text('bilingual full-text; vector search when an embedding model is configured.',exact=False).wait_for()
            page.get_by_text('Browse Ossie-style model and AML extensions (YAML)',exact=True).click()
            page.get_by_text('Ossie-style AML semantic model',exact=True).wait_for()
            page.get_by_text('Browse Ossie-style model and AML extensions (YAML)',exact=True).click()
            page.get_by_role('heading',name='What this account data says').evaluate('''element => {
                for (let parent = element.parentElement; parent; parent = parent.parentElement) {
                    if (getComputedStyle(parent).overflowY === 'auto') parent.scrollTop = 0;
                }
            }''')
            page.screenshot(path=str(output/'semantic_context.png'))
            assert page.get_by_role('textbox',name='Reviewer ID').count()==0
            assert page.get_by_role('button',name='Record review',exact=True).count()==0
            assert page.get_by_role('button',name='Retain assessment',exact=True).count()==0
            assert page.get_by_role('button',name='Query facts',exact=True).count()==0
            page.get_by_role('tab',name='KYC Documents',exact=True).click()
            document_link=page.get_by_role('link',name='Open original document ↗').first
            document_link.wait_for()
            response=client.get(document_link.get_attribute('href').split('#')[0])
            assert response.status_code==200 and response.content
            with sqlite3.connect(database) as copied:
                copied.execute("UPDATE alerts SET status='OPEN' WHERE alert_id='ALERT-ML-B313A7B299'")
            page.reload()
            page.get_by_text('CUST-MULE-0000',exact=True).first.click()
            page.get_by_role('tab',name='KYC Documents',exact=True).click()
            page.get_by_role('heading',name='Recorded onboarding profile',exact=True).wait_for()
            assert page.get_by_text('Customer profile · Markdown view',exact=True).count()==1
            assert page.get_by_role('textbox',name='Search KYC evidence').count()==0
            page.get_by_role('tab',name='Semantic context',exact=True).click()
            page.get_by_role('heading',name='What this account data says').wait_for()
            graph=page.get_by_label('Ossie model and data lineage graph')
            graph.get_by_role('button',name='LanceDB · PDF / OCR KYC page index').click()
            page.get_by_text('0 document versions linked to this customer/account',exact=False).wait_for()

            assert not errors,errors
            report={'browser':'chromium','sections':3,'graph_nodes':7,'source_documents':'passed',
                    'empty_index_fallback':'passed','markdown_fallback':'passed','original_files':'passed','review_form':'removed',
                    'page_errors':errors,'ops_database':'temporary copy'}
            (output/'browser_report.json').write_text(json.dumps(report,indent=2))
            print(json.dumps(report,indent=2))
            browser.close()


if __name__=='__main__':
    main()
