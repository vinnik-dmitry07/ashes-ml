'''Closed, total predicates for local skill contracts.

Predicates validate observable values. They do not establish factual truth
of arbitrary text or compensate external side effects.
'''

from kernel.core import fields, require, typed_value


def term_type(term, component, cells, phase):
    require(type(term) is dict and len(term) == 1)
    tag, value = next(iter(term.items()))
    if tag == 'literal':
        typed_value(value)
        return value['type']
    if tag == 'arg':
        require(type(value) is str and value in component['inputs'])
        return component['inputs'][value]
    if tag == 'output':
        require(value is True and phase == 'post')
        return component['output']
    require(tag in ('before', 'after', 'live_before', 'live_after'))
    require(type(value) is str and value in cells)
    footprint = set(component['read']) | set(component['write'])
    require(value in footprint)
    if tag in ('after', 'live_after'):
        require(phase == 'post')
    return 'bool' if tag.startswith('live_') else cells[value]['type']


def validate_predicate(pred, component, cells, phase, depth=0):
    require(depth <= 32 and type(pred) is dict)
    op = pred.get('op')
    if op in ('true', 'false'):
        fields(pred, ('op',))
    elif op == 'not':
        fields(pred, ('op', 'value'))
        validate_predicate(pred['value'], component, cells, phase, depth + 1)
    elif op in ('and', 'or'):
        fields(pred, ('op', 'values'))
        require(type(pred['values']) is list and len(pred['values']) <= 64)
        for child in pred['values']:
            validate_predicate(child, component, cells, phase, depth + 1)
    else:
        require(op in ('eq', 'le', 'contains'))
        fields(pred, ('op', 'left', 'right'))
        left = term_type(pred['left'], component, cells, phase)
        right = term_type(pred['right'], component, cells, phase)
        require(left == right)
        if op == 'le':
            require(left == 'nat')
        elif op == 'contains':
            require(left == 'text')


def term_value(term, args, before, after, output):
    tag, value = next(iter(term.items()))
    if tag == 'literal':
        return value
    if tag == 'arg':
        return args[value]
    if tag == 'output':
        return output
    source = before if tag in ('before', 'live_before') else after
    if tag.startswith('live_'):
        return {'type': 'bool', 'value': source[value]['live']}
    return source[value]['value']


def evaluate(pred, args, before, after=None, output=None):
    op = pred['op']
    if op == 'true':
        return True
    if op == 'false':
        return False
    if op == 'not':
        return not evaluate(pred['value'], args, before, after, output)
    if op in ('and', 'or'):
        values = (
            evaluate(child, args, before, after, output)
            for child in pred['values']
        )
        return all(values) if op == 'and' else any(values)
    left = term_value(pred['left'], args, before, after, output)
    right = term_value(pred['right'], args, before, after, output)
    if op == 'eq':
        return left == right
    if op == 'le':
        return left['value'] <= right['value']
    return right['value'] in left['value']
