'''
Closed first-order typed functional language with bounded recursive
calls.
'''

from copy import deepcopy

from .codec import canonical, fields, integer, name, need
from .decisions import OPERATORS
from .types import signature, type_ok, value_ok


def expression_children(expr):
    '''Children of a checked expression; literals and types are opaque data.'''
    op = expr['op']
    if op in ('lit', 'var'):
        return ()
    if op in ('call', 'builtin', 'service'):
        return tuple(expr['args'])
    if op == 'record':
        return tuple(expr['fields'].values())
    members = {
        'let': ('value', 'body'),
        'if': ('test', 'yes', 'no'),
        'some': ('value',),
        'get': ('record',),
        'index': ('list', 'index'),
    }
    need(op in members, 'SCHEMA')
    return tuple(expr[key] for key in members[op])


def check(program, services=None):
    canonical(program)
    services = {} if services is None else services
    fields(program, ('entry', 'functions'))
    functions = program['functions']
    need(type(functions) is dict and 1 <= len(functions) <= 64)
    need(program['entry'] in functions, 'REFERENCE')
    for key, function in functions.items():
        name(key)
        fields(function, ('params', 'result', 'body'))
        signature(function['params'], function['result'])

    def infer(expr, scope):
        need(type(expr) is dict and type(expr.get('op')) is str)
        op = expr['op']
        if op == 'lit':
            fields(expr, ('op', 'type', 'value'))
            value_ok(expr['value'], expr['type'])
            return expr['type']
        if op == 'var':
            fields(expr, ('op', 'name'))
            need(expr['name'] in scope, 'REFERENCE')
            return scope[expr['name']]
        if op == 'let':
            fields(expr, ('op', 'name', 'value', 'body'))
            name(expr['name'])
            updated = dict(scope)
            updated[expr['name']] = infer(expr['value'], scope)
            return infer(expr['body'], updated)
        if op == 'if':
            fields(expr, ('op', 'test', 'yes', 'no'))
            need(infer(expr['test'], scope) == 'Bool', 'TYPE')
            result = infer(expr['yes'], scope)
            need(result == infer(expr['no'], scope), 'TYPE')
            return result
        if op in ('call', 'builtin', 'service'):
            fields(expr, ('op', 'name', 'args'))
            need(type(expr['args']) is list)
            registry = {'call': functions, 'builtin': OPERATORS,
                        'service': services}[op]
            need(expr['name'] in registry, 'REFERENCE')
            target = registry[expr['name']]
            if op == 'call':
                args = [target['params'][key]
                        for key in sorted(target['params'])]
                output = target['result']
            else:
                args, output = target[:2]
            need(len(args) == len(expr['args']), 'TYPE')
            for wanted, actual in zip(args, expr['args']):
                need(wanted == infer(actual, scope), 'TYPE')
            return output
        if op == 'record':
            fields(expr, ('op', 'fields'))
            need(type(expr['fields']) is dict and len(expr['fields']) <= 64)
            for key in expr['fields']:
                name(key)
            return {'Record': {key: infer(value, scope)
                               for key, value in expr['fields'].items()}}
        if op == 'some':
            fields(expr, ('op', 'value'))
            return {'Option': infer(expr['value'], scope)}
        if op == 'get':
            fields(expr, ('op', 'record', 'field'))
            tag = infer(expr['record'], scope)
            need(type(tag) is dict and 'Record' in tag, 'TYPE')
            need(expr['field'] in tag['Record'], 'REFERENCE')
            return tag['Record'][expr['field']]
        if op == 'index':
            fields(expr, ('op', 'list', 'index'))
            tag = infer(expr['list'], scope)
            need(type(tag) is dict and 'List' in tag, 'TYPE')
            need(infer(expr['index'], scope) == 'Int', 'TYPE')
            return tag['List']
        need(False, 'SCHEMA')

    for function in functions.values():
        need(infer(function['body'], function['params']) == function['result'],
             'TYPE')
    return True


def execute(program, arguments, fuel, services=None):
    services = {} if services is None else services
    check(program, services)
    integer(fuel, 1, 100000)
    remaining = fuel
    functions = program['functions']

    def invoke(key, args, depth):
        need(depth <= 64, 'LIMIT')
        function = functions[key]
        need(len(args) == len(function['params']), 'TYPE')
        keys = sorted(function['params'])
        for value, tag in zip(args, [function['params'][key] for key in keys]):
            value_ok(value, tag)
        scope = dict(zip(keys, args))
        result = evaluate(function['body'], scope, depth)
        value_ok(result, function['result'])
        return result

    def evaluate(expr, scope, depth):
        nonlocal remaining
        need(remaining > 0, 'FUEL')
        remaining -= 1
        op = expr['op']
        if op == 'lit':
            return deepcopy(expr['value'])
        if op == 'var':
            return scope[expr['name']]
        if op == 'record':
            return {key: evaluate(expr['fields'][key], scope, depth)
                    for key in sorted(expr['fields'])}
        if op == 'some':
            return evaluate(expr['value'], scope, depth)
        if op == 'let':
            value = evaluate(expr['value'], scope, depth)
            return evaluate(
                expr['body'], {**scope, expr['name']: value}, depth)
        if op == 'if':
            branch = 'yes' if evaluate(expr['test'], scope, depth) else 'no'
            return evaluate(expr[branch], scope, depth)
        if op == 'get':
            return evaluate(expr['record'], scope, depth)[expr['field']]
        if op == 'index':
            values = evaluate(expr['list'], scope, depth)
            index = evaluate(expr['index'], scope, depth)
            integer(index, 0, len(values) - 1)
            return values[index]
        args = [evaluate(arg, scope, depth) for arg in expr['args']]
        if op == 'call':
            return invoke(expr['name'], args, depth + 1)
        registry = OPERATORS if op == 'builtin' else services
        _, result_type, function = registry[expr['name']]
        result = function(*deepcopy(args))
        value_ok(result, result_type)
        canonical(result)
        return result

    canonical(arguments)
    need(type(arguments) is list)
    result = invoke(program['entry'], arguments, 1)
    return {'result': result, 'fuel_used': fuel - remaining}
