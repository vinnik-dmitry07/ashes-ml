'''Closed offline search protocol and measured G12 candidate evaluations.'''

from copy import deepcopy
import json
import random
import secrets
import sys

from ahsl.codec import canonical, fields, integer, need, rat, ref
from ahsl.environment import ENVIRONMENT, audit_trace
from .adapter import run_episode
from .experiment import MemoryJournal, ROOT
from .protocol import ARMS, Route, digest
from .providers import FixtureProvider


METHODS = ('fixed', 'seed_fixed', 'independent', 'hill_climb')
SEARCH_METHODS = ('independent', 'hill_climb')
CALL_CAPS = tuple(range(4, 41, 3))
SEARCH_SEED = {'arm': 'fresh', 'max_calls': 4}
FIXED = {'arm': 'fresh', 'max_calls': 40}
FAULTS = (None, 'paint', 'timeout', 'missing_usage', 'bad_json', 'overrun')


def runtime_identity():
    return {'implementation': sys.implementation.name,
            'version': list(sys.version_info[:3])}


def validate_config(config):
    fields(config, ('repetitions', 'search_seed', 'search_tasks',
                    'holdout_tasks', 'search_budget_units', 'max_proposals',
                    'deployment_horizon', 'success_value_units',
                    'failure_threshold', 'fixture_fault'))
    integer(config['repetitions'], 1, 32)
    integer(config['search_seed'], 0, 2 ** 31 - 1)
    integer(config['search_tasks'], 1, 6)
    integer(config['holdout_tasks'], 1, 6)
    need(config['search_tasks'] + config['holdout_tasks'] <= 12)
    integer(config['search_budget_units'], 2, 100000)
    integer(config['max_proposals'], 1, 64)
    integer(config['deployment_horizon'], 1, 1000000)
    integer(config['success_value_units'], 1, 100000)
    need(0 <= rat(config['failure_threshold']) <= 1)
    need(config['fixture_fault'] in FAULTS)


def validate_candidate(candidate):
    fields(candidate, ('arm', 'max_calls'))
    need(candidate['arm'] in ARMS)
    integer(candidate['max_calls'], 4, 40)
    need(candidate['max_calls'] in CALL_CAPS)
    return deepcopy(candidate)


def candidate_id(candidate):
    return digest('SearchCandidate', validate_candidate(candidate))


def make_search_plan(config, source, hidden_seed=None, nonce=None):
    validate_config(config)
    ref(source)
    hidden = random.Random(secrets.randbits(256) if hidden_seed is None
                           else hidden_seed)
    public = random.Random(config['search_seed'])
    folds, held_out = [], []
    for index in range(config['repetitions']):
        levels = list(range(1, 13))
        hidden.shuffle(levels)
        count = config['search_tasks']
        folds.append({'fold': index, 'seed': public.randrange(2 ** 31),
                      'training_levels': levels[:count]})
        held_out.append(levels[count:count + config['holdout_tasks']])
    reveal = {'nonce': secrets.token_hex(32) if nonce is None else nonce,
              'holdout_levels': held_out}
    ref(reveal['nonce'])
    route = json.loads((ROOT / 'configs/fixture.json').read_text())['route']
    plan = {'kind': 'SearchStudyPlan', 'profile': 'G12_SEARCH_1',
            'source_manifest': source, 'environment': ENVIRONMENT,
            'runtime': runtime_identity(),
            'config': deepcopy(config), 'route': route, 'folds': folds,
            'holdout_commitment': digest('HiddenSplit', reveal)}
    return plan, reveal


def validate_plan(plan):
    fields(plan, ('kind', 'profile', 'source_manifest', 'environment',
                  'config', 'route', 'folds', 'holdout_commitment', 'runtime'))
    need(plan['kind'] == 'SearchStudyPlan')
    need(plan['profile'] == 'G12_SEARCH_1')
    need(plan['environment'] == ENVIRONMENT, 'STALE')
    need(plan['runtime'] == runtime_identity(), 'STALE')
    ref(plan['source_manifest'])
    ref(plan['holdout_commitment'])
    validate_config(plan['config'])
    route = json.loads((ROOT / 'configs/fixture.json').read_text())['route']
    need(plan['route'] == route, 'STALE')
    need(len(plan['folds']) == plan['config']['repetitions'])
    for index, fold in enumerate(plan['folds']):
        fields(fold, ('fold', 'seed', 'training_levels'))
        need(fold['fold'] == index)
        integer(fold['seed'], 0, 2 ** 31 - 1)
        levels = fold['training_levels']
        need(type(levels) is list and len(levels)
             == plan['config']['search_tasks'])
        need(len(set(levels)) == len(levels))
        for level in levels:
            integer(level, 1, 12)


def validate_reveal(plan, reveal):
    fields(reveal, ('nonce', 'holdout_levels'))
    ref(reveal['nonce'])
    need(digest('HiddenSplit', reveal) == plan['holdout_commitment'],
         'INTEGRITY')
    need(len(reveal['holdout_levels']) == len(plan['folds']))
    for fold, levels in zip(plan['folds'], reveal['holdout_levels']):
        need(type(levels) is list and len(levels)
             == plan['config']['holdout_tasks'])
        need(len(set(levels)) == len(levels))
        need(not set(levels) & set(fold['training_levels']), 'INTEGRITY')
        for level in levels:
            integer(level, 1, 12)


def proposal_packet(plan, fold, method, index, history):
    '''Only this closed packet enters the built-in proposal function.'''
    return {'method': method, 'seed': fold['seed'], 'index': index,
            'training_levels': deepcopy(fold['training_levels']),
            'history': deepcopy(history), 'arms': list(ARMS),
            'call_caps': list(CALL_CAPS)}


def propose(packet):
    fields(packet, ('method', 'seed', 'index', 'training_levels',
                    'history', 'arms', 'call_caps'))
    need(packet['method'] in SEARCH_METHODS)
    if packet['index'] == 0:
        return deepcopy(SEARCH_SEED)
    seed = digest('ProposalSeed', {'seed': packet['seed'],
                                   'index': packet['index']})
    generator = random.Random(int(seed, 16))
    if packet['method'] == 'independent':
        return {'arm': generator.choice(ARMS),
                'max_calls': generator.choice(CALL_CAPS)}
    history = packet['history']
    parent = best(history)['candidate'] if history else SEARCH_SEED
    child = deepcopy(parent)
    if generator.random() < 0.8:
        position = CALL_CAPS.index(parent['max_calls'])
        shift = generator.choice((-1, 1, 1, 2))
        child['max_calls'] = CALL_CAPS[max(0, min(12, position + shift))]
    else:
        child['arm'] = generator.choice(ARMS)
    return child


def best(history):
    # Fewer calls and then content ID settle ties, before holdout is opened.
    return min(history, key=lambda row: (-row['score_sum'],
                                         row['units'], row['id']))


def reserve_evaluation(candidate, task_count):
    # One episode, <= cap model calls and <= cap verified transitions.
    return task_count * (1 + 2 * candidate['max_calls'])


def measure(plan, fold, candidate, levels, sequence, phase):
    candidate = validate_candidate(candidate)
    route = Route(**plan['route'])
    settings = {'run_budget_microusd': 50000,
                'max_calls': candidate['max_calls'],
                'success_value_microusd': 1000000}
    rows = []
    for index, level in enumerate(levels):
        slot = {'case': fold['fold'] * 10000 + sequence * 10 + index,
                'level': level, 'condition': candidate['arm'],
                'model_seed': fold['seed']}
        provider = FixtureProvider(route, plan['config']['fixture_fault'])
        result = run_episode(slot, settings, route, provider,
                             MemoryJournal(), plan['source_manifest'])
        trace = audit_trace(result['envelope']['receipt']['trace'])
        units = 1 + result['calls'] + trace['steps']
        rows.append({'level': level, 'success': result['success'],
                     'calls': result['calls'], 'checks': trace['steps'],
                     'units': units, 'trace': trace['trace'],
                     'contract_violated': result['provider_contract_violated'],
                     'score': plan['config']['success_value_units']
                     * int(result['success']) - units})
    total = sum(row['units'] for row in rows)
    need(total <= reserve_evaluation(candidate, len(levels)), 'BUDGET')
    return {'candidate': candidate, 'id': candidate_id(candidate),
            'phase': phase, 'rows': rows, 'units': total,
            'score_sum': sum(row['score'] for row in rows),
            'contract_violated': any(row['contract_violated'] for row in rows)}
