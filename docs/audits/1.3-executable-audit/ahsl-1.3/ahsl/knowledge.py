'''Typed evidence retrieval and checked, explicit program transformations.'''

from copy import deepcopy
from fractions import Fraction

from .codec import canonical, cid, fields, integer, name, need, ref
from .language import check


def entry(value):
    fields(value, ('text', 'tokens', 'features', 'predicate', 'arguments',
                   'polarity', 'status', 'scope', 'evidence'))
    canonical(value)
    need(type(value['text']) is str)
    for field in ('tokens', 'features', 'arguments', 'evidence'):
        need(type(value[field]) is list
             and all(type(item) is str for item in value[field]))
    for field in ('tokens', 'features', 'evidence'):
        need(value[field] == sorted(set(value[field])))
    name(value['predicate'])
    need(type(value['polarity']) is bool)
    need(value['status'] in ('FACT', 'CONSTRAINT', 'ASSUMPTION', 'UNKNOWN'))
    ref(value['scope'])
    for evidence in value['evidence']:
        ref(evidence)
    need(value['status'] != 'FACT' or value['evidence'], 'PRECONDITION')


def jaccard(left, right):
    union = set(left) | set(right)
    return Fraction(len(set(left) & set(right)), len(union)) if union else (
        Fraction(0))


def assertion_id(item):
    return cid('KnowledgeAssertion', {key: item[key] for key in
                                      ('scope', 'predicate', 'arguments',
                                       'polarity')})


def ground_fact(envelope, runner):
    result = runner.verify(envelope)
    item = {'text': 'Terminal ground-goal result from an audited execution.',
            'tokens': sorted(['ground_success', result['trace']]),
            'features': ['verified_assertion'],
            'predicate': 'ground_success', 'arguments': [result['trace']],
            'polarity': result['ground_success'], 'status': 'FACT',
            'scope': envelope['receipt']['trace']['environment'],
            'evidence': [result['trace']]}
    return item, {result['trace']: assertion_id(item)}


def render_assertion(item):
    '''Render verified prose from bound fields, not from a source string.'''
    claim = {key: item[key] for key in
             ('scope', 'predicate', 'arguments', 'polarity')}
    return 'Verified assertion: ' + canonical(claim).decode('ascii')


def synthetic_trace(model, actions):
    from .environment import ACTIONS
    ref(model)
    need(type(actions) is list and len(actions) <= 64)
    need(all(type(action) is str and action in ACTIONS for action in actions))
    return {'kind': 'SyntheticTrace', 'model': model, 'actions': list(actions)}


def compose(entries, query, scope, byte_budget, channel, verified_refs=None):
    '''Labels are evidence metadata, never proof of their own truth.'''
    ref(scope)
    integer(byte_budget, 2, 100000)
    need(channel in ('relevance', 'analogy', 'contradiction'))
    entry(query)
    ranked = []
    verified_refs = {} if verified_refs is None else verified_refs
    for item in entries:
        entry(item)
        copy = deepcopy(item)
        verified = any(verified_refs.get(key) == assertion_id(copy)
                       for key in copy['evidence'])
        if copy['status'] == 'FACT' and (
                copy['scope'] != scope or not verified):
            copy['status'] = 'ASSUMPTION'
        elif copy['status'] == 'FACT':
            copy['text'] = render_assertion(copy)
            copy['tokens'] = sorted(
                set([copy['predicate']] + copy['arguments']))
            copy['features'] = ['verified_assertion']
            copy['evidence'] = [key for key in copy['evidence']
                                if verified_refs.get(key)
                                == assertion_id(copy)]
        if channel == 'relevance':
            score = jaccard(query['tokens'], copy['tokens'])
        elif channel == 'analogy':
            score = jaccard(query['features'], copy['features'])
        else:
            score = Fraction(query['predicate'] == copy['predicate']
                             and query['arguments'] == copy['arguments']
                             and query['polarity'] != copy['polarity'])
        if score > 0:
            ranked.append((-score, cid('KnowledgeEntry', copy), copy))
    result = []
    seen = set()
    for _, key, item in sorted(ranked, key=lambda row: row[:2]):
        if key not in seen and len(canonical(result + [item])) <= byte_budget:
            result.append(item)
            seen.add(key)
    return {'entries': result, 'bytes': len(canonical(result)),
            'considered': len(entries), 'returned': len(result),
            'channel': channel, 'scope': scope}


def mutate_literal(program, function, path, replacement):
    '''A grammar-constrained proposal, never an admission decision.'''
    check(program)
    result = deepcopy(program)
    need(function in result['functions'], 'REFERENCE')
    node = result['functions'][function]['body']
    need(type(path) is list)
    for key in path:
        if type(node) is dict:
            need(type(key) is str and key in node, 'REFERENCE')
        else:
            need(type(node) is list)
            integer(key, 0, len(node) - 1)
        node = node[key]
    need(type(node) is dict and node.get('op') == 'lit')
    node['value'] = deepcopy(replacement)
    check(result)
    return result


def trim_alias(program, alias):
    '''Remove only a proven forwarding alias; reassign every call to target.'''
    check(program)
    result = deepcopy(program)
    need(alias in result['functions'] and alias != result['entry'])
    function = result['functions'][alias]
    body = function['body']
    need(body['op'] == 'call' and body['name'] != alias, 'PRECONDITION')
    expected = [{'op': 'var', 'name': key}
                for key in sorted(function['params'])]
    need(body['args'] == expected, 'PRECONDITION')
    target = body['name']
    del result['functions'][alias]

    def rewrite(value):
        if type(value) is dict:
            if value.get('op') == 'call' and value.get('name') == alias:
                value['name'] = target
            for child in value.values():
                rewrite(child)
        elif type(value) is list:
            for child in value:
                rewrite(child)

    rewrite(result)
    check(result)
    return {'program': result, 'removed': alias, 'reassigned_to': target}
