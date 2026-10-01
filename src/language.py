'''
Closed first-order typed functional language with bounded recursive
calls.
'''

from copy import deepcopy

from .codec import canonical, decode, fields, integer, name, need
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
    need(type(services) is dict and len(services) <= 256)
    for service_name, service in services.items():
        name(service_name)
        need(type(service) in (list, tuple) and len(service) == 3)
        arguments, result, implementation = service
        need(type(arguments) in (list, tuple) and len(arguments) <= 64)
        for argument in arguments:
            type_ok(argument)
        type_ok(result)
        need(callable(implementation))
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


def alpha_normalize(program, services=None):
    '''Fixed-width bound names for size measurement, not a semantic hash.'''
    check(program, services)
    # Deepcopy retains shared Python nodes. Their lexical scopes can differ;
    # normalize the encoded tree so each occurrence is renamed independently.
    result = decode(canonical(program))
    functions = result['functions']
    renamed = {key: 'f' + str(index).zfill(2)
               for index, key in enumerate(sorted(functions))}

    def visit(expr, scope, depth):
        op = expr['op']
        if op == 'var':
            expr['name'] = scope[expr['name']]
        elif op == 'let':
            visit(expr['value'], scope, depth)
            original = expr['name']
            expr['name'] = 'v' + str(depth).zfill(2)
            visit(expr['body'], {**scope, original: expr['name']}, depth + 1)
        else:
            if op == 'call':
                expr['name'] = renamed[expr['name']]
            for child in expression_children(expr):
                visit(child, scope, depth)

    for function in functions.values():
        scope = {key: 'p' + str(index).zfill(2)
                 for index, key in enumerate(sorted(function['params']))}
        visit(function['body'], scope, 0)
        function['params'] = {scope[key]: value
                              for key, value in function['params'].items()}
    result['entry'] = renamed[result['entry']]
    result['functions'] = {renamed[key]: value
                           for key, value in functions.items()}
    check(result, services)
    return result


def program_cost_bytes(program):
    '''Raw storage limits remain separate from alpha-invariant cost.'''
    return len(canonical(alpha_normalize(program)))


def execute(program, arguments, fuel, services=None):
    services = {} if services is None else services
    check(program, services)
    integer(fuel, 1, 100000)
    remaining = fuel
    functions = program['functions']

    canonical(arguments)
    need(type(arguments) is list)
    pending = [('invoke', program['entry'], arguments, 1)]
    values = []

    def collect(count):
        result = values[-count:] if count else []
        if count:
            del values[-count:]
        return result

    # L12 call depth is a language limit, independent of the Python stack.
    # Continuations preserve evaluation order and charge only AST visits.
    while pending:
        frame = pending.pop()
        kind = frame[0]
        if kind == 'invoke':
            _, key, args, depth = frame
            need(depth <= 64, 'LIMIT')
            function = functions[key]
            keys = sorted(function['params'])
            need(len(args) == len(keys), 'TYPE')
            for key, value in zip(keys, args):
                value_ok(value, function['params'][key])
            pending.append(('return', function['result']))
            pending.append(('eval', function['body'], dict(zip(keys, args)),
                            depth))
        elif kind == 'return':
            value_ok(values[-1], frame[1])
        elif kind == 'bind':
            _, name_, body, scope, depth = frame
            pending.append(('eval', body, {**scope, name_: values.pop()},
                            depth))
        elif kind == 'branch':
            _, expr, scope, depth = frame
            branch = 'yes' if values.pop() else 'no'
            pending.append(('eval', expr[branch], scope, depth))
        elif kind == 'record':
            keys = frame[1]
            values.append(dict(zip(keys, collect(len(keys)))))
        elif kind == 'get':
            values.append(values.pop()[frame[1]])
        elif kind == 'index':
            index = values.pop()
            items = values.pop()
            integer(index, 0, len(items) - 1)
            values.append(items[index])
        elif kind == 'apply':
            _, op, key, count, depth = frame
            args = collect(count)
            if op == 'call':
                pending.append(('invoke', key, args, depth + 1))
            else:
                registry = OPERATORS if op == 'builtin' else services
                _, result_type, function = registry[key]
                result = function(*deepcopy(args))
                value_ok(result, result_type)
                canonical(result)
                values.append(result)
        else:
            _, expr, scope, depth = frame
            need(remaining > 0, 'FUEL')
            remaining -= 1
            op = expr['op']
            if op == 'lit':
                values.append(deepcopy(expr['value']))
            elif op == 'var':
                values.append(scope[expr['name']])
            elif op == 'record':
                keys = sorted(expr['fields'])
                pending.append(('record', keys))
                pending.extend(('eval', expr['fields'][key], scope, depth)
                               for key in reversed(keys))
            elif op == 'some':
                pending.append(('eval', expr['value'], scope, depth))
            elif op == 'let':
                pending.append(('bind', expr['name'], expr['body'], scope,
                                depth))
                pending.append(('eval', expr['value'], scope, depth))
            elif op == 'if':
                pending.append(('branch', expr, scope, depth))
                pending.append(('eval', expr['test'], scope, depth))
            elif op == 'get':
                pending.append(('get', expr['field']))
                pending.append(('eval', expr['record'], scope, depth))
            elif op == 'index':
                pending.append(('index',))
                pending.append(('eval', expr['index'], scope, depth))
                pending.append(('eval', expr['list'], scope, depth))
            else:
                pending.append(('apply', op, expr['name'], len(expr['args']),
                                depth))
                pending.extend(('eval', arg, scope, depth)
                               for arg in reversed(expr['args']))
    need(len(values) == 1, 'INTEGRITY')
    return {'result': values[0], 'fuel_used': fuel - remaining}
