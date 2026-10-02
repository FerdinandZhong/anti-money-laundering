"""Read-only regulatory meaning catalog; never dependent on evidence availability."""
from semantic.model_loader import _load_yaml


def regulation_catalog():
    model = _load_yaml('aml_regulation.ossie.yaml')
    sources = {s['id']: s for s in _load_yaml('regulatory_source_register.yaml')['sources']}
    requirements = []
    for requirement in model['requirements']:
        source = sources[requirement['source_id']]
        requirements.append({**requirement, 'jurisdiction': source['jurisdiction'],
                             'issuer': source['issuer'], 'edition': source['edition'],
                             'source_url': source.get('pdf_url') or source['repository_url'],
                             'mapping_relation': 'related',
                             'applicability_status': 'conditions_only'})
    return {'version': model['version'], 'requirements': requirements}
