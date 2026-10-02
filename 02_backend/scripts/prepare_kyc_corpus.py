"""Build synthetic PDFs linked to 12 AML source customers and 30 accounts.

The source IDs mirror deterministic AML generation; regulatory controls remain DEMO.
All ingestion text comes from native PDF extraction or real OCR of image-only PDFs.
"""
import argparse
import csv
import json
from pathlib import Path
import sys

try:
    ROOT = Path(__file__).resolve().parents[2]
except NameError:
    ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / '02_backend'))
sys.path.insert(0, str(ROOT / '02_backend/scripts'))

FAMILIES = {
    'registry': ('Company registry / 企业登记', [
        'Beneficial owner / 受益所有人: Lin Mei',
        'Legal representative / 法定代表人: Zhang Jun',
        'These roles are distinct; registration does not establish account authority.']),
    'mandate': ('Account mandate / 账户授权书', [
        'Authorized signatory / 授权签字人: Anita Wong',
        'Payment signing limit / 付款签署限额: 50000',
        'Signing authority is not beneficial ownership.']),
    'funding': ('Source of funds / 资金来源', [
        'Funding origin / 资金来源: Export invoice settlement',
        'Invoice / 发票: INV-{group:03d}-2026',
        'Currency / 币种: USD; Amount / 金额: 20000',
        'Origin of this payment does not explain accumulated wealth.']),
    'wealth': ('Source of wealth / 财富来源', [
        'Wealth origin / 财富来源: Sale of inherited property',
        'Property transfer reference / 房产转让编号: PROP-{group:03d}',
        'Accumulated wealth is distinct from current account funding.']),
    'review': ('Periodic KYC review / 定期尽职调查', [
        'Review due date / 复核到期日: 2026-12-31',
        'Ownership chain / 所有权链: Holding company 60%, direct owner 40%',
        'Adverse media / 负面新闻: Unresolved name match, analyst review required',
        'No sanctions determination is made by this synthetic review.']),
}


def scenario_accounts():
    return [{'customer_id': f'CUST-{group + 295:06d}',
             'account_id': f'ACC-{group + 295:07d}' if index == 1 else f'ACC-KYC-{group:03d}-{index}',
             'booking_jurisdiction': 'SG' if group % 2 else 'HK',
             'currency': 'SGD' if group % 2 else 'HKD',
             'classification': 'SYNTHETIC_KYC_CORPUS'}
            for group in range(1, 13) for index in range(1, (3 if group <= 6 else 2) + 1)]


def prepare(output):
    import fitz
    from rapidocr_onnxruntime import RapidOCR
    from kyc_extraction_poc import extract, put_text
    engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    accounts = scenario_accounts()
    with (output / 'accounts.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(accounts[0]))
        writer.writeheader(); writer.writerows(accounts)
    manifest, truth, reports = [], [], []
    for group in range(1, 13):
        customer = f'CUST-{group + 295:06d}'
        for family, (title, fields) in FAMILIES.items():
            for revision in (1, 2):
                document_id = f'corpus-{group:03d}-{family}'
                reference = f'KYC{group:03d}{family.upper()}{revision}'
                received = f'2026-09-{1 if revision == 1 else 18:02d}T00:00:00Z'
                # Account documents are scoped to the first account; the others are customer-wide.
                account = f'ACC-{group + 295:07d}' if family in ('mandate', 'funding') else ''
                lines = ['SYNTHETIC DEMO - NOT AN OFFICIAL RECORD', title,
                         f'Customer: {customer}', f'Reference: {reference}',
                         f'Revision / 版本: {revision}', f'Received / 收件日期: {received[:10]}']
                lines += [field.format(group=group) for field in fields]
                if family == 'registry' and revision == 2 and group % 3 == 0:
                    lines[6] = 'Beneficial owner / 受益所有人: Chen Min'
                if account:
                    lines.append('Account: ' + account)
                scanned = family == 'mandate' and revision == 2
                target = output / f'{document_id}-v{revision}.pdf'
                with fitz.open() as native:
                    page = native.new_page(width=595, height=842)
                    for index, line in enumerate(lines):
                        put_text(page, (25, 40 + index * 39), line, 12)
                    if scanned:
                        with fitz.open() as raster:
                            image_page = raster.new_page(width=595, height=842)
                            image_page.insert_image(image_page.rect, stream=page.get_pixmap(dpi=200).tobytes('png'))
                            assert not image_page.get_text().strip()
                            raster.save(target, no_new_id=True)
                    else:
                        native.save(target, no_new_id=True)
                extracted = extract(target, engine)
                groups = {}
                for line in extracted['lines']:
                    groups.setdefault(line['page'], []).append(line)
                if not groups:
                    raise ValueError(f'No extracted content for {target.name}')
                (output / (target.name + '.extracted.json')).write_text(
                    json.dumps(extracted, ensure_ascii=False, indent=2))
                manifest.append({'document_id': document_id, 'customer_id': customer,
                                 'account_id': account, 'received_at': received, 'title': title,
                                 'path': target.name, 'language': 'en-zh', 'illustrative': True,
                                 'source': 'Isolated synthetic retrieval corpus',
                                 'provenance': 'Real RapidOCR of image-only PDF' if scanned else 'Real native PDF extraction',
                                 'pages': [{'page': number, 'text': '\n'.join(item['text'] for item in records),
                                            'evidence': records} for number, records in sorted(groups.items())]})
                truth.append({'document_id': document_id, 'revision': revision, 'reference': reference,
                              'received_at': received, 'rendered_lines': lines})
                reports.append({'document_id': document_id, 'revision': revision,
                                'mode': 'rapidocr' if scanned else 'native_pdf',
                                'sha256': extracted['sha256'], 'extracted_lines': len(extracted['lines'])})
        print(f'Extracted group {group}/12', flush=True)
    for name, value in [('knowledge_manifest.json', manifest), ('rendering_truth.json', truth),
                        ('extraction_report.json', reports)]:
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    return {'groups': 12, 'accounts': len(accounts), 'document_versions': len(manifest),
            'native_pdfs': sum(item['mode'] == 'native_pdf' for item in reports),
            'scanned_pdfs': sum(item['mode'] == 'rapidocr' for item in reports)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/kyc_poc/corpus')
    print(json.dumps(prepare(parser.parse_args().output), indent=2))
