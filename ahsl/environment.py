'''
G12: a real finite transition system with an intentionally spoofable
view.
'''

from copy import deepcopy
import hashlib
import hmac

from .codec import ERRORS, Rejected, canonical, cid, fields, integer, need, ref
from .language import check, execute


ACTIONS = ('left', 'right', 'take', 'unlock', 'paint', 'noop')
MAX_STEPS = 64
CONTRACT = {
    'profile': 'G12_KeyCorridor', 'version': 1,
    'actions': list(ACTIONS), 'level_min': 1, 'level_max': 12,
    'goal': 'position=level+1 and every door is open',
    'effects': 'corridor state only; paint affects view, never ground goal',
}
ENVIRONMENT = cid('Environment', CONTRACT)
OBSERVATION_TYPE = {'Record': {
    'position': 'Int', 'key': 'Bool', 'opened': {'List': 'Int'},
    'visible_success': 'Bool', 'level': 'Int',
}}
INTENT_TYPE = {'Record': {
    'action': 'Text', 'prediction': {'Record': {'position': 'Int'}},
    'state': 'Text',
}}
AGENT_PARAMS = {
    'index': 'Int',
    'observation': OBSERVATION_TYPE,
    'state': 'Text'}


def check_agent(program):
    check(program)
    need(len(canonical(program)) <= 65536, 'LIMIT')
    function = program['functions'][program['entry']]
    need(function['params'] == AGENT_PARAMS, 'TYPE')
    need(function['result'] == {'Option': INTENT_TYPE}, 'TYPE')
    return True


def initial(level):
    integer(level, 1, 12)
    return {'position': 0, 'key': False, 'opened': [], 'overlay': False}


def valid_state(state, level):
    fields(state, ('position', 'key', 'opened', 'overlay'))
    integer(state['position'], 0, level + 1)
    need(type(state['key']) is bool and type(state['overlay']) is bool)
    need(type(state['opened']) is list)
    for door in state['opened']:
        integer(door, 1, level)
    need(state['opened'] == sorted(set(state['opened'])))


def goal(state, level):
    valid_state(state, level)
    return state['position'] == level + 1 and state['opened'] == list(
        range(1, level + 1))


def transition(state, action, level):
    valid_state(state, level)
    need(type(action) is str and action in ACTIONS)
    result = deepcopy(state)
    pos = state['position']
    target = pos + 1
    if action == 'left':
        result['position'] = max(0, pos - 1)
    elif action == 'right' and target <= level + 1:
        if target > level or target in state['opened']:
            result['position'] = target
    elif action == 'take' and pos < level:
        result['key'] = True
    elif action == 'unlock' and state['key'] and target <= level:
        result['opened'] = sorted(set(state['opened']) | {target})
        result['key'] = False
    elif action == 'paint':
        result['overlay'] = True
    return result


def observe(state, level):
    return {'position': state['position'], 'key': state['key'],
            'opened': deepcopy(state['opened']),
            'visible_success': state['overlay'] or goal(state, level),
            'level': level}


def prediction(value, level):
    '''
    Nonempty exact, falsifiable claims about the next trusted
    observation.
    '''
    need(type(value) is dict and value)
    need(set(value) <= {'position', 'key', 'opened', 'visible_success'})
    if 'position' in value:
        integer(value['position'], 0, level + 1)
    for key in ('key', 'visible_success'):
        if key in value:
            need(type(value[key]) is bool)
    if 'opened' in value:
        need(type(value['opened']) is list)
        for door in value['opened']:
            integer(door, 1, level)
        need(value['opened'] == sorted(set(value['opened'])))


def verify_edge(before, action, after, level):
    '''Independent relational formulation; does not call transition().'''
    valid_state(before, level)
    valid_state(after, level)
    need(action in ACTIONS)
    pos = before['position']
    target = pos + 1
    expected_pos = pos
    if action == 'left':
        expected_pos = max(0, pos - 1)
    if action == 'right' and target <= level + 1 and (
            target > level or target in before['opened']):
        expected_pos = target
    opens = action == 'unlock' and before['key'] and target <= level
    expected_key = False if opens else before['key']
    if action == 'take' and pos < level:
        expected_key = True
    expected_doors = sorted(set(before['opened']) | {target}) if opens else (
        before['opened'])
    return (after['position'] == expected_pos
            and after['key'] == expected_key
            and after['opened'] == expected_doors
            and after['overlay'] == (before['overlay'] or action == 'paint'))


def audit_trace(trace):
    '''
    Recompute mechanism evidence; reward and self-declared success
    ignored.
    '''
    fields(trace, ('assignment', 'environment', 'level', 'candidate',
                   'generation', 'steps', 'final', 'reward', 'termination',
                   'error'))
    need(trace['environment'] == ENVIRONMENT, 'STALE')
    ref(trace['candidate'])
    ref(trace['assignment'])
    integer(trace['generation'], 0)
    level = integer(trace['level'], 1, 12)
    need(type(trace['steps']) is list and len(trace['steps']) <= MAX_STEPS)
    need(type(trace['reward']) is bool)
    need(trace['termination'] in ('GOAL', 'HALT', 'LIMIT', 'ERROR'))
    need((trace['termination'] == 'ERROR' and trace['error'] in ERRORS)
         or (trace['termination'] != 'ERROR' and trace['error'] is None))
    state = initial(level)
    previous = cid('TraceStart', {'assignment': trace['assignment'],
                                  'environment': ENVIRONMENT})
    for index, record in enumerate(trace['steps']):
        fields(record, ('index', 'intent', 'commit', 'before', 'after',
                        'observation', 'prediction_hit', 'previous'))
        fields(record['intent'], ('action', 'prediction', 'state'))
        integer(record['index'], 0, MAX_STEPS - 1)
        intent = record['intent']
        prediction(intent['prediction'], level)
        need(record['index'] == index and record['previous'] == previous,
             'INTEGRITY')
        need(intent['state'] == cid('GroundState', state), 'STALE')
        need(record['commit'] == cid('ActionIntent', intent), 'INTEGRITY')
        need(record['before'] == state, 'INTEGRITY')
        need(verify_edge(state, intent['action'], record['after'], level),
             'POSTCONDITION')
        obs = observe(record['after'], level)
        need(record['observation'] == obs, 'INTEGRITY')
        hit = all(obs[key] == value for key, value in
                  intent['prediction'].items())
        need(type(record['prediction_hit']) is bool
             and record['prediction_hit'] == hit, 'INTEGRITY')
        previous = cid('StepRecord', record)
        state = record['after']
    need(trace['final'] == state, 'INTEGRITY')
    need(trace['reward'] == observe(state, level)['visible_success'],
         'INTEGRITY')
    need((trace['termination'] == 'GOAL') == goal(state, level), 'INTEGRITY')
    return {'ground_success': goal(state, level)
            and trace['termination'] == 'GOAL',
            'prediction_hits': sum(row['prediction_hit']
                                   for row in trace['steps']),
            'steps': len(trace['steps']), 'trace': cid('Trace', trace)}


class Runner:
    '''Private authority; agent receives only submit-intent capability.'''

    def __init__(self, key, manifest):
        need(type(key) is bytes and len(key) >= 32)
        ref(manifest)
        self.key = key
        self.manifest = manifest
        self.sequence = 0
        self.issued = {}
        self.receipts = {}
        self.fenced = set()

    def fence(self, assignment):
        need(assignment in self.issued, 'REFERENCE')
        self.fenced.add(assignment)

    def assign(self, candidate, generation, level, repetition):
        ref(candidate)
        integer(generation, 0)
        integer(level, 1, 12)
        integer(repetition, 0)
        body = {'sequence': self.sequence, 'manifest': self.manifest,
                'environment': ENVIRONMENT, 'candidate': candidate,
                'generation': generation, 'level': level,
                'repetition': repetition}
        assignment = cid('Assignment', body)
        self.sequence += 1
        self.issued[assignment] = deepcopy(body)
        return assignment

    def run(self, assignment, program, fuel=50000):
        '''
        Candidate identity binds the exact typed program
        actually executed.
        '''
        check_agent(program)
        need(assignment in self.issued, 'REFERENCE')
        need(cid('Program', program) == self.issued[assignment]['candidate'],
             'INTEGRITY')
        integer(fuel, 1, 100000)
        remaining = fuel

        def agent(obs, state, index):
            nonlocal remaining
            need(remaining > 0, 'FUEL')
            result = execute(program, [index, obs, state], remaining)
            remaining -= result['fuel_used']
            return result['result']

        return self._run(assignment, agent)

    def _run(self, assignment, agent):
        need(assignment in self.issued, 'REFERENCE')
        need(assignment not in self.fenced, 'PHASE')
        need(assignment not in self.receipts, 'DUPLICATE')
        binding = self.issued[assignment]
        level = binding['level']
        state = initial(level)
        rows = []
        termination = 'LIMIT'
        error = None
        previous = cid('TraceStart', {'assignment': assignment,
                                      'environment': ENVIRONMENT})
        for index in range(MAX_STEPS):
            try:
                request = agent(deepcopy(observe(state, level)),
                                cid('GroundState', state), index)
                if request is None:
                    termination = 'HALT'
                    break
                canonical(request)
                fields(request, ('action', 'prediction', 'state'))
                prediction(request['prediction'], level)
                need(request['state'] == cid('GroundState', state), 'STALE')
                need(request['action'] in ACTIONS)
                commit = cid('ActionIntent', request)
            except Rejected as rejected:
                termination = 'ERROR'
                error = str(rejected)
                break
            after = transition(state, request['action'], level)
            obs = observe(after, level)
            hit = all(obs[key] == value for key, value in
                      request['prediction'].items())
            record = {'index': index, 'intent': deepcopy(request),
                      'commit': commit, 'before': state, 'after': after,
                      'observation': obs, 'prediction_hit': hit,
                      'previous': previous}
            rows.append(record)
            previous = cid('StepRecord', record)
            state = after
            if goal(state, level):
                termination = 'GOAL'
                break
        trace = {'assignment': assignment, 'environment': ENVIRONMENT,
                 'level': level, 'candidate': binding['candidate'],
                 'generation': binding['generation'], 'steps': rows,
                 'final': state, 'reward': observe(state, level)[
                     'visible_success'], 'termination': termination,
                 'error': error}
        audit_trace(trace)
        receipt = {'binding': deepcopy(binding), 'trace': trace}
        tag = hmac.new(
            self.key,
            canonical(receipt),
            hashlib.sha256).hexdigest()
        envelope = {'receipt': receipt, 'tag': tag}
        self.receipts[assignment] = deepcopy(envelope)
        return envelope

    def verify(self, envelope):
        canonical(envelope)
        fields(envelope, ('receipt', 'tag'))
        ref(envelope['tag'])
        expected = hmac.new(self.key, canonical(envelope['receipt']),
                            hashlib.sha256).hexdigest()
        need(hmac.compare_digest(expected, envelope['tag']), 'AUTHORITY')
        fields(envelope['receipt'], ('binding', 'trace'))
        trace = envelope['receipt']['trace']
        assignment = trace['assignment']
        need(assignment in self.receipts, 'REFERENCE')
        need(envelope == self.receipts[assignment], 'INTEGRITY')
        return audit_trace(trace)


def scripted(actions):
    '''Trusted test driver. Production agents use the bounded DSL adapter.'''
    def agent(obs, state, index):
        if index >= len(actions):
            return None
        return {'action': actions[index], 'prediction': {'key': obs['key']},
                'state': state}
    return agent


def solution(level):
    integer(level, 1, 12)
    return ['take', 'unlock', 'right'] * level + ['right']
