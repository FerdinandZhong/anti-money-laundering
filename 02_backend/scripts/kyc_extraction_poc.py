"""Real PDF/OCR extraction benchmark on visibly synthetic bilingual dossiers.

Run with rapidocr_onnxruntime, PyMuPDF and Pillow installed. Ground truth is
used only by evaluate(); extract() receives document pixels/text, never answers.
"""
from pathlib import Path
import json
import re
import hashlib
import time
import importlib.metadata
import unicodedata

import fitz
from PIL import Image, ImageFilter

try:
    ROOT = Path(__file__).resolve().parents[2]
except NameError:
    ROOT = Path.cwd()
OUT = ROOT / 'artifacts/kyc_poc/extraction'

LABELS = {
    'company_name': ['Company name', '公司名称'],
    'registration_id': ['Registration ID', '登记编号'],
    'representative': ['Legal representative', '法定代表人'],
    'beneficial_owner': ['Beneficial owner', '受益所有人'],
    'registered_address': ['Registered address', '注册地址'],
    'expected_turnover': ['Expected turnover', '预计营业额'],
    'review_date': ['Review date', '审核日期'],
}


def normalize(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value)).casefold()


def put_text(page, point, text, size):
    # Built-in CJK fonts assign full-width advances to Latin glyphs. Use Latin
    # and CJK font runs so fixture typography is readable and does not clip.
    x, y = point
    for run in re.findall(r'[\u3400-\u9fff]+|[^\u3400-\u9fff]+', text):
        font = 'china-s' if re.search(r'[\u3400-\u9fff]', run) else 'helv'
        page.insert_text((x,y),run,fontname=font,fontsize=size)
        x += fitz.get_text_length(run,fontname=font,fontsize=size)
    assert x < page.rect.width - 10, 'Fixture text clipped'


def generate():
    OUT.mkdir(parents=True, exist_ok=True)
    cases = []
    for language in ['en', 'zh', 'mixed']:
        chinese = language != 'en'
        values = dict(zip(LABELS, [
            '澄海贸易有限公司' if chinese else 'Blue Harbor Trading Ltd.',
            'KYC-DEMO-00017', '林伟' if chinese else 'Lin Wei',
            '陈敏' if chinese else 'Chen Min',
            '海港路18号' if chinese else '18 Harbor Road',
            'SGD 421390.00', '2026-09-01',
        ]))
        rows = [['陈敏' if chinese else 'Chen Min', '60.00%'],
                ['林伟' if chinese else 'Lin Wei', '40.00%']]
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((35, 40), 'SYNTHETIC DEMO - NOT AN OFFICIAL RECORD', fontsize=13)
        put_text(page, (35,75), 'KYC / 企业尽职调查',20)
        for i, (key, value) in enumerate(values.items()):
            label = LABELS[key][1 if language == 'zh' or (language == 'mixed' and i % 2) else 0]
            put_text(page, (35,120+i*43), f'{label}: {value}',15)
        put_text(page,(35,450),'Ownership / 股权记录',17)
        for j, row in enumerate([['Shareholder / 股东', 'Holding / 持股']] + rows):
            y = 475 + j * 40
            page.draw_rect(fitz.Rect(35, y, 560, y + 40), color=(0.3, 0.3, 0.3))
            page.draw_line((380, y), (380, y + 40), color=(0.3, 0.3, 0.3))
            for x, value in zip([45, 395], row):
                put_text(page,(x,y+26),value,15)
        path = OUT / f'{language}_native.pdf'
        doc.set_metadata({'title': 'Synthetic KYC extraction fixture'})
        doc.save(path, no_new_id=True)
        cases.append({'file': path.name, 'language': language, 'mode': 'native', 'expected': values, 'table': rows})
        for mode, dpi in [('scan', 220), ('degraded', 120)]:
            pix = page.get_pixmap(dpi=dpi)
            im = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)
            if mode == 'degraded':
                im = im.convert('L').filter(ImageFilter.GaussianBlur(0.8)).rotate(2, expand=True, fillcolor=255).convert('RGB')
            png = OUT / f'{language}_{mode}.png'
            im.save(png)
            scanned = fitz.open()
            sp = scanned.new_page(width=595, height=842)
            sp.insert_image(sp.rect, filename=str(png))
            target = OUT / f'{language}_{mode}.pdf'
            scanned.save(target, no_new_id=True)
            assert not sp.get_text().strip(), 'Scans must not contain hidden text'
            scanned.close()
            cases.append({'file': target.name, 'language': language, 'mode': mode, 'expected': values, 'table': rows})
        doc.close()
    (OUT / 'evaluation_ground_truth.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2))
    return cases


def extract(path, engine):
    """Read actual page content; no access to fixture values or evaluation labels."""
    lines = []
    with fitz.open(path) as doc:
        for page_no, page in enumerate(doc, 1):
            native = page.get_text('dict')
            if page.get_text().strip():
                for block in native['blocks']:
                    for line in block.get('lines', []):
                        lines.append({'text': ''.join(s['text'] for s in line['spans']),
                                      'bbox': list(line['bbox']), 'page': page_no,
                                      'confidence': None, 'method': 'native_pdf', 'coordinates': 'pdf_points'})
            else:
                pix = page.get_pixmap(dpi=220)
                import numpy as np
                image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                results, _ = engine(image)
                for box, text, confidence in results or []:
                    lines.append({'text': text, 'bbox': box, 'page': page_no,
                                  'confidence': float(confidence), 'method': 'rapidocr',
                                  'coordinates': 'pixels', 'image_size': [pix.width, pix.height]})
    # OCR may detect labels and values as separate boxes. Reconstruct lines
    # geometrically before applying label rules; keep the raw boxes as evidence.
    groups = []
    for line in lines:
        b=line['bbox']
        if isinstance(b[0],list):
            x=min(p[0] for p in b); y=sum(p[1] for p in b)/4
            height=max(p[1] for p in b)-min(p[1] for p in b)
        else:
            x=b[0]; y=(b[1]+b[3])/2; height=b[3]-b[1]
        group=next((g for g in groups if g['page']==line['page'] and g['method']==line['method'] and abs(g['y']-y)<max(g['height'],height)*.8),None)
        if group is None:
            group={'page':line['page'],'method':line['method'],'y':y,'height':height,'parts':[]}; groups.append(group)
        group['parts'].append((x,line))
    fields = {}
    for group in groups:
        parts=[p[1] for p in sorted(group['parts'],key=lambda p:p[0])]
        line={'text':' '.join(p['text'] for p in parts),'page':group['page'],'components':parts}
        for key, labels in LABELS.items():
            for label in labels:
                match = re.match(r'^\s*' + re.escape(label) + r'\s*[:：]\s*(.+)$', line['text'], re.I)
                if match:
                    fields.setdefault(key, []).append({'value': match.group(1).strip(), 'evidence': line})
    # Pair table cells by vertical center; never infer rows from generator truth.
    cells = []
    for line in lines:
        box = line['bbox']
        if isinstance(box[0], list):
            x = sum(p[0] for p in box) / len(box); y = sum(p[1] for p in box) / len(box)
            h = max(p[1] for p in box) - min(p[1] for p in box)
        else:
            x = (box[0] + box[2])/2; y = (box[1]+box[3])/2; h=box[3]-box[1]
        cells.append((x,y,h,line))
    table = []
    for x,y,h,line in cells:
        if re.fullmatch(r'\d+(?:\.\d+)?[%％]', line['text'].strip()):
            left = [c for c in cells if c[0] < x and c[3]['page']==line['page'] and abs(c[1]-y)<max(h,c[2])*.7]
            if left:
                owner = max(left,key=lambda c:c[0])[3]
                table.append({'name':owner['text'], 'holding':line['text'], 'evidence':[owner,line]})
    return {'fields': fields, 'table': table, 'lines': lines,
            'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def main():
    from rapidocr_onnxruntime import RapidOCR
    cases = generate()
    engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
    reports = []
    for case in cases:
        start = time.monotonic()
        result = extract(OUT / case['file'], engine)
        (OUT / (case['file'] + '.extracted.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
        matches = {key: len(result['fields'].get(key,[]))==1 and
                   normalize(result['fields'][key][0]['value'])==normalize(value)
                   for key,value in case['expected'].items()}
        table_ok = sorted((normalize(r['name']),normalize(r['holding'])) for r in result['table']) == sorted(tuple(normalize(c) for c in row) for row in case['table'])
        record = {'file':case['file'],'language':case['language'],'mode':case['mode'],
                  'correct_fields':sum(matches.values()),'total_fields':len(matches),
                  'field_matches':matches,'ownership_table_exact':table_ok,
                  'elapsed_seconds':round(time.monotonic()-start,2),
                  'missing_fields':[k for k in matches if k not in result['fields']],
                  'incorrect_fields':[k for k,v in matches.items() if not v and k in result['fields']]}
        reports.append(record)
        print(json.dumps(record,ensure_ascii=False),flush=True)
    report = {'engine': 'rapidocr_onnxruntime',
              'versions':{p:importlib.metadata.version(p) for p in ['rapidocr_onnxruntime','onnxruntime','PyMuPDF','Pillow']},
              'scope':'9 controlled synthetic pages; not a production OCR benchmark',
              'acceptance':'Native/clean scans: all seven field values and both ownership rows exact; degraded cases report errors without automatic acceptance.',
              'clean_gate_passed':all(r['correct_fields']==r['total_fields'] and r['ownership_table_exact'] for r in reports if r['mode']!='degraded'),
              'cases':reports}
    (OUT / 'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
