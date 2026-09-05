'''Synthetic conformance scenario, with no LLM or empirical benchmark claim.'''

from copy import deepcopy

import artifacts
import system


def value(number):
    return {'type': 'nat', 'value': number}


def fixture():
    true = {'op': 'true'}
    implementation = {
        'kind': 'code', 'format': 'fixture-v1', 'payload': {'name': 'increment'},
        'dependencies': [],
    }
    implementation_id = artifacts.content_id(implementation)
    skill = {
        'kind': 'skill', 'format': 'skill-v1',
        'payload': {'implementation': implementation_id, 'pre': true, 'post': true},
        'dependencies': [implementation_id],
    }
    policy = {
        'version': '0.6', 'manifest': {
            'version': '0.5', 'budget': 10,
            'cells': {'memory': {'type': 'nat', 'live': True, 'value': value(0)}},
            'components': {'transform': {
                'inputs': {'x': 'nat'}, 'output': 'nat',
                'read': ['memory'], 'write': ['memory'], 'cost': 4,
            }},
        },
        'total_budget': 100, 'context': 'environment-v1',
        'initializable': ['memory'],
        'alpha': {'num': 1, 'den': 20},
        'strata': {'composition': {
            'n': 128, 'regression': {'num': 1, 'den': 10}, 'gain': True,
        }},
        'evaluation_cost': 8, 'max_trials': 20, 'max_runs': 20,
        'contracts': {'transform': {'pre': true, 'post': {
            'op': 'le', 'left': {'arg': 'x'}, 'right': {'output': True},
        }}},
        'interface': {
            'inputs': {'x': 'nat'}, 'output': 'nat', 'pre': true,
            'post': {'op': 'le', 'left': {'arg': 'x'}, 'right': {'output': True}},
        },
    }
    program = {
        'registers': {'x': value(0), 'result': value(0), 'error': {
            'type': 'text', 'value': '',
        }},
        'inputs': ['x'], 'handles': {'call': 'transform'}, 'entry': 'invoke',
        'nodes': {
            'invoke': {
                'op': 'spawn', 'handle': 'call', 'args': {'x': {'register': 'x'}},
                'ok': 'wait', 'error': 'finish', 'error_register': 'error',
            },
            'wait': {
                'op': 'await', 'handle': 'call', 'output_register': 'result',
                'error_register': 'error', 'ok': 'finish', 'error': 'finish',
                'unknown': 'finish',
            },
            'finish': {'op': 'halt', 'value': {'register': 'result'}},
        },
        'output': 'nat', 'fuel': 10,
    }
    configuration = {
        'program': program, 'bindings': {'transform': artifacts.content_id(skill)},
        'initial': {'memory': value(0)},
    }
    return policy, [implementation, skill], configuration


def report(prefix='sample', parent=False, candidate=True):
    return {'strata': {'composition': [
        {'id': prefix + str(i), 'parent': parent, 'candidate': candidate}
        for i in range(128)
    ]}, 'violations': 0}


def demonstration():
    policy, registry, configuration = fixture()
    state = system.initial(policy, registry, configuration)
    candidate = deepcopy(configuration)
    candidate['program']['fuel'] = 11
    events = [
        ('agent', {'id': 'e1', 'kind': 'propose', 'proposal': 'proposal1',
                   'configuration': candidate}),
        ('agent', {'id': 'e2', 'kind': 'start_trial', 'trial': 'trial1',
                   'proposal': 'proposal1', 'claim': 'improve'}),
        ('provider', {'id': 'e3', 'kind': 'assessment', 'trial': 'trial1',
                      'charge': 6, 'outcome': {'kind': 'report', 'report': report()}}),
        ('agent', {'id': 'e4', 'kind': 'publish', 'trial': 'trial1'}),
    ]
    for principal, event in events:
        state, _, _ = system.step(state, principal, event)
        assert system.invariants(state)
    return {
        'synthetic': True, 'generation': state['generation'],
        'available': state['available'], 'spent': state['spent'],
        'records': state['log'],
    }
