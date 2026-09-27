"""Strict term mappings and historically applicable demo controls."""
from datetime import datetime, timezone
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]


def instant(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def mappings():
    return yaml.safe_load((ROOT/'semantic/aml_source_mappings.yaml').read_text())


def pack():
    return yaml.safe_load((ROOT/'semantic/aml_control_packs.yaml').read_text())


def resolve(source, field, concept, jurisdiction, as_of, mapping_contract=None):
    """No fuzzy/partial equivalence in an executable control."""
    relevant = [m for m in (mapping_contract if mapping_contract is not None else mappings())['mappings']
                if m['source'] == source and m['field'] == field and
                m['concept'] == concept and m['jurisdiction'] == jurisdiction and
                instant(m['effective_from']) <= instant(as_of) and
                (not m.get('effective_to') or instant(as_of) < instant(m['effective_to']))]
    denied = [m for m in relevant if m['relation'] == 'not_equivalent']
    approved = [m for m in relevant if m['relation'] == 'equivalent' and m['review_status'] == 'approved_demo']
    if denied:
        return {'status':'unsupported', 'reason':'Explicit non-equivalence', 'mapping_ids':[m['id'] for m in denied]}
    if len(approved) > 1:
        return {'status':'ambiguous', 'mapping_ids':[m['id'] for m in approved]}
    if len(approved) == 1:
        return {'status':'resolved', 'mapping_ids':[approved[0]['id']], 'concept':concept}
    return {'status':'unmapped', 'mapping_ids':[], 'reason':'No approved exact mapping for this source and context'}


def applicable_controls(jurisdiction, product, as_of, control_pack=None):
    contract=control_pack if control_pack is not None else pack()
    if contract.get('classification') != 'DEMO' or any(not c.get('id','').startswith('DEMO-') for c in contract['controls']):
        raise ValueError('Only explicitly DEMO control packs are executable')
    matches = [c for c in contract['controls'] if c['jurisdiction'] == jurisdiction and
               c['product'] == product and instant(c['effective_from']) <= instant(as_of) and
               (not c.get('effective_to') or instant(as_of) < instant(c['effective_to']))]
    if len({c['id'] for c in matches}) != len(matches):
        raise ValueError('Overlapping control versions')
    return matches
