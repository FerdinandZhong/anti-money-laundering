"""Read-only comparison of registered MCP tools with an OpenAPI document."""
import argparse
import asyncio
import json
from pathlib import Path

from aml_mcp.server import mcp, _get


def _resolve(schema, document):
    if '$ref' in schema:
        ref = schema['$ref']
        if not ref.startswith('#/'):
            raise ValueError('Only local OpenAPI references are supported')
        value = document
        for part in ref[2:].split('/'):
            value = value[part.replace('~1', '/').replace('~0', '~')]
        return value
    return schema


async def compare(document):
    if 'openapi' not in document or not isinstance(document.get('paths'), dict):
        raise ValueError('Expected an OpenAPI JSON document, not a login page or API response')
    results = []
    for tool in await mcp.list_tools():
        route = tool.meta['aml_api']
        path, method = route['path'], route['method'].lower()
        path_item = document['paths'].get(path, {})
        operation = path_item.get(method)
        problems = []
        if operation is None:
            problems.append('Missing API method/path')
        else:
            properties = tool.input_schema['properties']
            inputs = {{'query': 'q', 'release_id': 'release'}.get(name, name) for name in properties}
            parameters = path_item.get('parameters', []) + operation.get('parameters', [])
            for parameter in parameters:
                parameter = _resolve(parameter, document)
                if parameter.get('required') and parameter['name'] not in inputs:
                    problems.append('Missing required API parameter: ' + parameter['name'])
            body = _resolve(operation.get('requestBody', {}), document)
            body_schema = _resolve(body.get('content', {}).get('application/json', {}).get('schema', {}), document)
            for field in body_schema.get('required', []):
                if field not in properties:
                    problems.append('Missing required JSON field: ' + field)
        results.append({'tool': tool.name, **route, 'compatible': not problems, 'problems': problems})
    return {'compatible': all(r['compatible'] for r in results), 'tools': results,
            'scope': 'Method/path and required input coverage; not runtime authorization or response semantics.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema', type=Path, help='Exported OpenAPI JSON; otherwise fetch the configured API')
    args = parser.parse_args()
    schema = json.loads(args.schema.read_text()) if args.schema else _get('/openapi.json')
    result = asyncio.run(compare(schema))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['compatible'] else 1)


if __name__ == '__main__':
    main()
