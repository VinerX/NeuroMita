from __future__ import annotations

from copy import deepcopy
from typing import Any

from schemas.structured_response import StructuredResponse
from schemas.sparse_structured_response import provider_structured_model
from services.structured_response_capabilities import provider_schema_options


def openai_response_format(req: Any) -> dict:
    caps = req.capabilities or {}
    if caps.get('structured_output_mode', 'json_schema') == 'json_object':
        return {'type': 'json_object'}
    options = provider_schema_options(caps)
    model = provider_structured_model(req.structured_model or StructuredResponse, caps)
    return model.openai_response_format(
        exclude_fields=options['exclude_fields'] or None,
        custom_params=caps.get('custom_params') or None,
        exclude_segment_fields=options['exclude_segment_fields'] or None,
        require_fields=options['require_fields'] or None,
    )


def _strict_schema(source: dict, property_name: str = '') -> dict:
    node = deepcopy(source)
    node.pop('default', None)
    if node.get('type') == 'object':
        if node.get('additionalProperties') not in (None, False) or (
            'properties' not in node and node.get('additionalProperties') is not False
        ):
            if property_name not in {'args', 'payload'}:
                raise ValueError(f'Strict output requires declared properties for {property_name or "object"}')
            return {'type': 'string', 'description': (
                (node.get('description') or '') + ' Return this object as a JSON-encoded string.')}
        properties = node.get('properties') or {}
        node['properties'] = {name: _strict_schema(value, name) for name, value in properties.items()}
        node['required'] = list(properties)
        node['additionalProperties'] = False
    if isinstance(node.get('items'), dict):
        node['items'] = _strict_schema(node['items'], property_name)
    for key in ('anyOf', 'oneOf', 'allOf'):
        if key in node:
            node[key] = [_strict_schema(branch, property_name) for branch in node[key]]
    for key in ('$defs', 'definitions'):
        if key in node:
            node[key] = {name: _strict_schema(value, name) for name, value in node[key].items()}
    return node


def responses_text_format(req: Any) -> dict:
    response_format = openai_response_format(req)
    if response_format['type'] == 'json_object':
        return response_format
    definition = deepcopy(response_format['json_schema'])
    definition['schema'] = _strict_schema(definition['schema'])
    definition['strict'] = True
    return {'type': 'json_schema', **definition}
