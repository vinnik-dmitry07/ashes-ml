'''AHSL-Core 0.5: pure, deterministic reference transition function.

This module interprets trusted event fixtures. It does not authenticate
callers, execute model code, store durable data, or dispatch network requests.
'''

from copy import deepcopy
import json
import re


MAX_NAT = 2 ** 31 - 1
TYPES = frozenset(('unit', 'bool', 'nat', 'text', 'ref'))
IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_.-]{0,127}\Z')
PRINCIPALS = frozenset(('agent', 'provider', 'supervisor'))
ROLE = {
    'reserve': 'agent',
    'dispatch': 'agent',
    'cancel': 'agent',
    'unknown': 'provider',
    'complete': 'provider',
    'revoke': 'supervisor',
}


class SchemaError(ValueError):
    pass


def require(condition):
    if not condition:
        raise SchemaError('BAD_SCHEMA')


def fields(value, names):
    require(type(value) is dict and set(value) == set(names))


def identifier(value):
    require(type(value) is str and IDENTIFIER.fullmatch(value) is not None)


def nat(value):
    require(type(value) is int and 0 <= value <= MAX_NAT)


def scalar_text(value):
    require(type(value) is str)
    require(not any(0xD800 <= ord(char) <= 0xDFFF for char in value))


def type_name(value):
    require(type(value) is str and value in TYPES)


def typed_value(value):
    require(type(value) is dict)
    type_name(value.get('type'))
    tag = value['type']
    fields(value, ('type',) if tag == 'unit' else ('type', 'value'))
    if tag == 'nat':
        nat(value['value'])
    elif tag == 'bool':
        require(type(value['value']) is bool)
    elif tag == 'text':
        scalar_text(value['value'])
    elif tag == 'ref':
        identifier(value['value'])


def names(value):
    require(type(value) is list)
    for name in value:
        identifier(name)
    require(len(value) == len(set(value)))


def named_values(value):
    require(type(value) is dict)
    for name, item in value.items():
        identifier(name)
        typed_value(item)


def load_json(text):
    '''Reject duplicate keys, floats, non-finite numbers and surrogates.'''
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result)
            result[key] = value
        return result

    def bad_number(_):
        raise SchemaError('BAD_SCHEMA')

    value = json.loads(
        text, object_pairs_hook=pairs, parse_float=bad_number,
        parse_constant=bad_number,
    )

    def walk(item):
        if type(item) is str:
            scalar_text(item)
        elif type(item) is dict:
            for key, child in item.items():
                scalar_text(key)
                walk(child)
        elif type(item) is list:
            for child in item:
                walk(child)
        elif type(item) is int:
            nat(item)
    walk(value)
    return value


def initial(manifest):
    fields(manifest, ('version', 'budget', 'cells', 'components'))
    require(manifest['version'] == '0.5')
    nat(manifest['budget'])
    require(type(manifest['cells']) is dict)
    require(type(manifest['components']) is dict)
    cells = {}
    for key, cell in manifest['cells'].items():
        identifier(key)
        fields(cell, ('type', 'live', 'value'))
        type_name(cell['type'])
        require(type(cell['live']) is bool)
        typed_value(cell['value'])
        require(cell['value']['type'] == cell['type'])
        cells[key] = dict(deepcopy(cell), version=0)
    for key, component in manifest['components'].items():
        identifier(key)
        fields(component, ('inputs', 'output', 'read', 'write', 'cost'))
        require(type(component['inputs']) is dict)
        for name, tag in component['inputs'].items():
            identifier(name)
            type_name(tag)
        type_name(component['output'])
        names(component['read'])
        names(component['write'])
        require(set(component['read'] + component['write']) <= set(cells))
        nat(component['cost'])
    return {
        'manifest': deepcopy(manifest), 'cells': cells,
        'available': manifest['budget'], 'spent': 0,
        'epoch': 0, 'revoked': [], 'jobs': {}, 'seen': {}, 'log': [],
    }


def validate_event(event):
    require(type(event) is dict)
    kind = event.get('kind')
    require(type(kind) is str and kind in ROLE)
    extra = {
        'reserve': ('job', 'component', 'args'),
        'dispatch': ('job',), 'cancel': ('job',), 'unknown': ('job',),
        'complete': ('job', 'charge', 'outcome'),
        'revoke': ('component',),
    }[kind]
    fields(event, ('id', 'kind') + extra)
    identifier(event['id'])
    if 'job' in event:
        identifier(event['job'])
    if 'component' in event:
        identifier(event['component'])
    if kind == 'reserve':
        named_values(event['args'])
    if kind == 'complete':
        nat(event['charge'])
        outcome = event['outcome']
        require(type(outcome) is dict)
        if outcome.get('kind') == 'failure':
            fields(outcome, ('kind', 'code'))
            identifier(outcome['code'])
        else:
            fields(outcome, ('kind', 'value', 'writes'))
            require(outcome['kind'] == 'success')
            typed_value(outcome['value'])
            require(type(outcome['writes']) is list)
            for write in outcome['writes']:
                require(type(write) is dict)
                op = write.get('op')
                require(op in ('create', 'replace', 'delete'))
                required = ('op', 'cell') if op == 'delete' else (
                    'op', 'cell', 'value'
                )
                fields(write, required)
                identifier(write['cell'])
                if op != 'delete':
                    typed_value(write['value'])


def answer(code, **extra):
    return {'code': code, **extra}


def compatible_args(component, args):
    return set(args) == set(component['inputs']) and all(
        args[name]['type'] == tag for name, tag in component['inputs'].items()
    )


def proposal_error(state, job, outcome):
    component = state['manifest']['components'][job['component']]
    if job['epoch'] != state['epoch']:
        return 'STALE_POLICY'
    if job['component'] in state['revoked']:
        return 'DENIED'
    if any(
        state['cells'][key]['version'] != cell['version']
        for key, cell in job['snapshot'].items()
    ):
        return 'CONFLICT'
    if outcome['value']['type'] != component['output']:
        return 'OUTPUT_TYPE'
    writes = outcome['writes']
    keys = [write['cell'] for write in writes]
    if len(keys) != len(set(keys)):
        return 'DUPLICATE_WRITE'
    if not set(keys) <= set(component['write']):
        return 'WRITE_DENIED'
    for write in sorted(writes, key=lambda item: item['cell']):
        cell = state['cells'][write['cell']]
        if cell['version'] == MAX_NAT:
            return 'VERSION_EXHAUSTED'
        if (write['op'] == 'create') == cell['live']:
            return 'CELL_LIFECYCLE'
        if write['op'] != 'delete' and write['value']['type'] != cell['type']:
            return 'WRITE_TYPE'
    return None


def apply_event(state, event):
    '''Mutate only a private copy; return result and dispatch requests.'''
    kind = event['kind']
    components = state['manifest']['components']
    if kind == 'revoke':
        key = event['component']
        if key not in components:
            return answer('NO_COMPONENT'), []
        if key in state['revoked']:
            return answer('OK'), []
        if state['epoch'] == MAX_NAT:
            return answer('EPOCH_EXHAUSTED'), []
        state['epoch'] += 1
        state['revoked'] = sorted(state['revoked'] + [key])
        return answer('OK'), []
    key = event['job']
    if kind == 'reserve':
        if key in state['jobs']:
            return answer('JOB_EXISTS'), []
        component_id = event['component']
        if component_id not in components:
            return answer('NO_COMPONENT'), []
        component = components[component_id]
        if component_id in state['revoked']:
            return answer('DENIED'), []
        if not compatible_args(component, event['args']):
            return answer('INPUT_TYPE'), []
        if state['available'] < component['cost']:
            return answer('BUDGET'), []
        footprint = sorted(set(component['read'] + component['write']))
        snapshot = {name: deepcopy(state['cells'][name]) for name in footprint}
        state['available'] -= component['cost']
        state['jobs'][key] = {
            'component': component_id, 'args': deepcopy(event['args']),
            'snapshot': snapshot, 'epoch': state['epoch'],
            'status': 'reserved', 'held': component['cost'],
            'charged': 0, 'result': None,
        }
        return answer('OK'), []
    if key not in state['jobs']:
        return answer('NO_JOB'), []
    job = state['jobs'][key]
    if kind == 'dispatch':
        if job['status'] != 'reserved':
            return answer('BAD_PHASE'), []
        if job['epoch'] != state['epoch']:
            return answer('STALE_POLICY'), []
        if job['component'] in state['revoked']:
            return answer('DENIED'), []
        job['status'] = 'running'
        request = {
            'job': key, 'component': job['component'], 'args': job['args'],
            'snapshot': job['snapshot'], 'max_charge': job['held'],
        }
        return answer('OK'), [deepcopy(request)]
    if kind == 'cancel':
        if job['status'] != 'reserved':
            return answer('BAD_PHASE'), []
        state['available'] += job['held']
        job.update(status='cancelled', held=0, result=answer('CANCELLED'))
        return answer('OK'), []
    if kind == 'unknown':
        if job['status'] not in ('running', 'unknown'):
            return answer('BAD_PHASE'), []
        job['status'] = 'unknown'
        return answer('OK'), []
    if job['status'] not in ('running', 'unknown'):
        return answer('BAD_PHASE'), []
    charge = event['charge']
    if charge > job['held']:
        return answer('CHARGE_EXCEEDS_RESERVE'), []
    outcome = event['outcome']
    error = None
    if outcome['kind'] == 'success':
        error = proposal_error(state, job, outcome)
    if outcome['kind'] == 'failure':
        result = answer('COMPONENT_FAILURE', detail=outcome['code'])
    elif error is not None:
        result = answer(error)
    else:
        for write in outcome['writes']:
            cell = state['cells'][write['cell']]
            cell['version'] += 1
            cell['live'] = write['op'] != 'delete'
            if write['op'] != 'delete':
                cell['value'] = deepcopy(write['value'])
        result = answer('SUCCESS', value=deepcopy(outcome['value']))
    state['available'] += job['held'] - charge
    state['spent'] += charge
    job.update(status='done', charged=charge, held=0, result=result)
    return answer('SETTLED', result=result), []


def step(state, principal, event):
    '''Total on well-formed reachable states and decoded JSON event values.

    Caller identity is supplied by the trusted adapter, not an event field.
    Resource exhaustion of the Python host is outside the abstract semantics.
    '''
    try:
        require(type(principal) is str and principal in PRINCIPALS)
        validate_event(event)
    except (SchemaError, TypeError):
        return deepcopy(state), answer('BAD_SCHEMA'), []
    previous = state['seen'].get(event['id'])
    if previous is not None:
        if previous['principal'] != principal or previous['event'] != event:
            return deepcopy(state), answer('EVENT_ID_REUSE'), []
        return deepcopy(state), deepcopy(previous['result']), []
    updated = deepcopy(state)
    if ROLE[event['kind']] != principal:
        result, requests = answer('FORBIDDEN'), []
    else:
        result, requests = apply_event(updated, event)
    record = {
        'principal': principal, 'event': deepcopy(event),
        'result': deepcopy(result),
    }
    updated['seen'][event['id']] = deepcopy(record)
    updated['log'].append(record)
    return updated, deepcopy(result), deepcopy(requests)


def invariants(state):
    jobs = state['jobs'].values()
    held = sum(job['held'] for job in jobs)
    return (
        state['available'] >= 0
        and state['spent'] >= 0
        and state['available'] + state['spent'] + held
        == state['manifest']['budget']
        and state['spent'] == sum(job['charged'] for job in jobs)
        and all(job['held'] >= 0 for job in jobs)
        and all(
            job['held'] == state['manifest']['components'][
                job['component']
            ]['cost']
            for job in jobs if job['status'] in (
                'reserved', 'running', 'unknown'
            )
        )
        and all(
            cell['value']['type'] == cell['type']
            for cell in state['cells'].values()
        )
        and all(
            job['held'] == 0
            for job in jobs if job['status'] in ('done', 'cancelled')
        )
    )


def replay(manifest, records):
    state = initial(manifest)
    for record in records:
        state, result, _ = step(state, record['principal'], record['event'])
        require(result == record['result'])
    return state
