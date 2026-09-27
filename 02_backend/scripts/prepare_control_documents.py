"""Render synthetic control PDFs, run real native/OCR extraction, emit ingestion manifest."""
import argparse
import json
from pathlib import Path
import sys
try:
    ROOT=Path(__file__).resolve().parents[2]
except NameError:
    ROOT=Path.cwd()
sys.path.insert(0,str(ROOT/'02_backend'))
sys.path.insert(0,str(ROOT/'02_backend/scripts'))
import fitz
from knowledge.demo_records import entries
from kyc_extraction_poc import put_text, extract
from prepare_kyc_knowledge import default_entries


def prepare(output, include_poc=True):
    from rapidocr_onnxruntime import RapidOCR
    engine=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
    output.mkdir(parents=True,exist_ok=True)
    imported=default_entries(include_poc=include_poc)
    reports=[]
    for entry in entries():
        native=fitz.open()
        for record in entry['pages']:
            page=native.new_page(width=595,height=842)
            put_text(page,(30,40),'SYNTHETIC DEMO - NOT AN OFFICIAL RECORD',13)
            for index,line in enumerate(record['text'].splitlines()):
                put_text(page,(30,100+index*35),line,16)
        scanned=entry['document_id'] in {'control-demo-sg-declaration','control-demo-hk-mandate'}
        target=output/(entry['document_id']+'.pdf')
        if scanned:
            doc=fitz.open()
            for page in native:
                scan=doc.new_page(width=595,height=842)
                scan.insert_image(scan.rect,stream=page.get_pixmap(dpi=220).tobytes('png'))
                assert not scan.get_text().strip()
            doc.save(target,no_new_id=True);doc.close()
        else:
            native.save(target,no_new_id=True)
        native.close()
        extracted=extract(target,engine)
        (output/(target.name+'.extracted.json')).write_text(json.dumps(extracted,ensure_ascii=False,indent=2))
        groups={}
        for line in extracted['lines']:
            groups.setdefault(line['page'],[]).append(line)
        if set(groups) != {record['page'] for record in entry['pages']}:
            raise ValueError(f'Extraction returned an empty or missing page: {target.name}')
        # Text is derived solely from parser/OCR output, never the rendering input.
        entry.update({'path':str(target.resolve()),
                      'pages':[{'page':n,'text':'\n'.join(line['text'] for line in lines),'evidence':lines}
                               for n,lines in sorted(groups.items())],
                      'provenance':'Synthetic demo PDF; real '+('RapidOCR image-only extraction' if scanned else 'native PDF extraction')})
        imported.append(entry)
        reports.append({'document_id':entry['document_id'],'mode':'scan' if scanned else 'native',
                        'pages':len(groups),'lines':len(extracted['lines']), 'sha256':extracted['sha256']})
    manifest=output/'knowledge_manifest.json'
    manifest.write_text(json.dumps(imported,ensure_ascii=False,indent=2))
    (output/'extraction_report.json').write_text(json.dumps(reports,indent=2))
    print(str(manifest))
    print(json.dumps(reports,indent=2))
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/kyc_poc/control_documents')
    prepare(parser.parse_args().output)
