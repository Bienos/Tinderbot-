"""Explicit provider selection and bounded structured-output transports. No model tools."""
from __future__ import annotations

import copy
import json
import os

import httpx


def provider():
    selected = os.getenv('LLM_PROVIDER', '').strip().lower()
    if not selected:
        selected = 'anthropic' if os.getenv('ANTHROPIC_API_KEY') and not os.getenv('OPENAI_API_KEY') else 'openai'
    if selected not in ('openai', 'anthropic'):
        raise ValueError('Unsupported LLM_PROVIDER; use openai or anthropic')
    return selected


def configured():
    try:
        return bool(os.getenv('ANTHROPIC_API_KEY' if provider() == 'anthropic' else 'OPENAI_API_KEY', '').strip())
    except ValueError:
        return False


def model_name():
    if provider() == 'anthropic':
        return os.getenv('ANTHROPIC_MODEL', '').strip() or 'claude-sonnet-5-5'
    return os.getenv('OPENAI_MODEL', '').strip() or 'gpt-4.1-mini'


def model_label():
    return provider() + ':' + model_name()


def anthropic_schema(schema):
    """Move unsupported bounds to descriptions; the original Pydantic model still validates.

    Only closed objects are used by this application. Walk schema nodes, preserving
    property names even if a property happens to be named like a schema keyword.
    """
    result = copy.deepcopy(schema)
    unsupported = ('minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum',
                   'multipleOf', 'minLength', 'maxLength', 'pattern', 'maxItems', 'uniqueItems')

    def visit(node):
        if not isinstance(node, dict):
            return
        constraints = {}
        for key in unsupported:
            if key in node:
                constraints[key] = node.pop(key)
        if node.get('minItems', 0) not in (0, 1):
            constraints['minItems'] = node.pop('minItems')
        if constraints:
            node['description'] = (node.get('description', '') + ' Required constraints: ' +
                                   json.dumps(constraints, ensure_ascii=False)).strip()
        if node.get('type') == 'object':
            if node.get('additionalProperties', False) is not False:
                raise ValueError('Structured output requires closed object schemas')
            node['additionalProperties'] = False
        for key in ('properties', '$defs', 'definitions'):
            for child in node.get(key, {}).values():
                visit(child)
        for key in ('items',):
            visit(node.get(key))
        for key in ('anyOf', 'allOf', 'oneOf'):
            for child in node.get(key, []):
                visit(child)

    visit(result)
    return result


def complete(prompt, encoded_context, schema):
    """One provider request. Never retry or fall back to another provider implicitly."""
    selected = provider()
    if not configured():
        raise ValueError('Selected model provider has no API key')
    model = model_name()
    with httpx.Client(timeout=40, trust_env=False, follow_redirects=False) as client:
        if selected == 'anthropic':
            payload = {
                'model': model, 'max_tokens': 1024, 'system': prompt,
                'messages': [{'role': 'user', 'content': encoded_context}],
                'output_config': {'format': {'type': 'json_schema', 'schema': anthropic_schema(schema)}},
            }
            # Sonnet 5.5 cannot disable thinking. With no tools, between_tools
            # avoids up-front thinking for these short structured responses.
            if model.startswith('claude-sonnet-5-5'):
                payload['thinking'] = {'type': 'between_tools'}
            response = client.post('https://api.anthropic.com/v1/messages',
                headers={'x-api-key': os.environ['ANTHROPIC_API_KEY'], 'anthropic-version': '2026-10-21'},
                json=payload)
        else:
            response = client.post('https://api.openai.com/v1/chat/completions',
                headers={'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY']},
                json={'model': model, 'messages': [{'role': 'system', 'content': prompt},
                                                 {'role': 'user', 'content': encoded_context}],
                      'max_completion_tokens': 768,
                      'response_format': {'type': 'json_schema', 'json_schema': {
                          'name': schema['title'], 'strict': True, 'schema': schema}}})
        response.raise_for_status()
        result = response.json()
    usage = result.get('usage', {})
    if selected == 'anthropic':
        input_tokens = sum(usage.get(k, 0) for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'))
        output_tokens = usage.get('output_tokens', 0)
        if result.get('stop_reason') != 'end_turn':
            raise ValueError('Model did not complete a structured response')
        blocks = result['content']
        if any(b.get('type') not in ('text', 'thinking', 'redacted_thinking') for b in blocks):
            raise ValueError('Unexpected model content block')
        texts = [b['text'] for b in blocks if b.get('type') == 'text']
        if len(texts) != 1 or not isinstance(texts[0], str):
            raise ValueError('Expected one structured text block')
        content = texts[0]
    else:
        choice = result['choices'][0]
        if choice.get('finish_reason', 'stop') != 'stop' or choice['message'].get('refusal'):
            raise ValueError('Model did not complete a structured response')
        content = choice['message']['content']
        input_tokens, output_tokens = usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0)
    return content, input_tokens, output_tokens
