'''
Actual release and positive-training admission over authenticated
execution.
'''

from copy import deepcopy
from fractions import Fraction
from math import comb

from .codec import canonical, cid, decode, fields, integer, need, rat, ref
from .environment import ENVIRONMENT, Runner, check_agent
from .kernel import Ledger, replay
from .language import check
from .obligations import (
    COST_AXES, DEFAULT_GUARANTEES, IMPROVEMENT_PROFILE,
    check_mission, create_mission, refines,
    validate_guarantees,
)
from .witness import Evaluator, derive_key, key_id


def exact_pair_tests(rows, epsilon):
    '''
    Returns Fractions internally; protocol serialization uses
    decimal strings.
    '''
    need(type(rows) is list and rows)
    need(all(type(row) is list and len(row) == 2
             and all(type(value) is bool for value in row) for row in rows))
    epsilon = Fraction(epsilon)
    need(0 < epsilon < 1)
    n = len(rows)
    wins = sum(not parent and child for parent, child in rows)
    losses = sum(parent and not child for parent, child in rows)
    discordant = wins + losses
    gain = Fraction(sum(comb(discordant, k)
                        for k in range(wins, discordant + 1)), 2 ** discordant)
    loss = sum(Fraction(comb(n, k)) * epsilon ** k
               * (1 - epsilon) ** (n - k) for k in range(losses + 1))
    return gain, loss


def assess_pairs(strata, trial_index, alpha, epsilon):
    '''
    Conditional statistical gate. Fresh independent sampling is a
    premise.
    '''
    integer(trial_index, 1)
    need(type(strata) is dict and strata)
    alpha = Fraction(alpha)
    need(0 < alpha < 1)
    threshold = alpha / (trial_index * (trial_index + 1) * 2 * len(strata))
    details = {}
    for key in sorted(strata):
        gain, loss = exact_pair_tests(strata[key], epsilon)
        details[key] = {'gain': str(gain), 'loss': str(loss),
                        'accept': gain <= threshold and loss <= threshold}
    return {'accept': all(value['accept'] for value in details.values()),
            'threshold': str(threshold), 'strata': details}


class Session:
    '''
    The only admission authority; no agent-supplied verdicts or
    principal.
    '''

    def __init__(self, baseline, total, key, manifest, levels=None,
                 baseline_guarantees=None):
        check_agent(baseline)
        integer(total, 1, 96)
        self.levels = list(
            range(1, 13)) if levels is None else deepcopy(levels)
        need(self.levels and self.levels == sorted(set(self.levels)))
        for level in self.levels:
            integer(level, 1, 12)
        observer_key = derive_key(key, 'AHSL14-observer')
        evaluator_key = derive_key(key, 'AHSL14-evaluator')
        self.mission = create_mission(
            manifest, self.levels, key_id(observer_key), key_id(evaluator_key))
        self.mission_id = cid('Mission', self.mission)
        base_contract = (deepcopy(DEFAULT_GUARANTEES)
                         if baseline_guarantees is None
                         else deepcopy(baseline_guarantees))
        need(refines(base_contract, self.mission['floor']), 'PRECONDITION')
        baseline_id = cid('Program', baseline)
        self.programs = {baseline_id: deepcopy(baseline)}
        self.published_contracts = {baseline_id: base_contract}
        self.contracts = {cid('Guarantees', base_contract): base_contract}
        self.ledger = Ledger(total, baseline_id)
        self.runner = Runner(observer_key, manifest, self.mission_id)
        self.evaluator = Evaluator(evaluator_key, self.runner.read_observation)
        self.plans = {}
        self.used = set()
        self.training_used = set()
        self.dataset = {}
        self.active_plan = None
        self.requests_used = 0
        self.decisions = []
        self.request_log = []
        self.request_log_bytes = 0
        self.request_log_head = cid('RequestLogStart', {
            'mission': self.mission_id,
        })

    def snapshot(self):
        '''
        Store its digest in a trusted durable store separate
        from the blob.
        '''
        return deepcopy({
            'version': '1.4', 'levels': self.levels,
            'programs': {key: canonical(value).decode('ascii')
                         for key, value in self.programs.items()},
            'plans': self.plans, 'used': sorted(self.used),
            'training_used': sorted(self.training_used),
            'dataset': self.dataset,
            'active_plan': self.active_plan,
            'requests_used': self.requests_used,
            'mission': self.mission, 'mission_id': self.mission_id,
            'published_contracts': self.published_contracts,
            'contracts': self.contracts, 'decisions': self.decisions,
            'request_log': self.request_log,
            'request_log_bytes': self.request_log_bytes,
            'request_log_head': self.request_log_head,
            'ledger': {'genesis': self.ledger.genesis,
                       'state': self.ledger.state,
                       'log': self.ledger.log, 'head': self.ledger.head},
            'runner': {'manifest': self.runner.manifest,
                       'sequence': self.runner.sequence,
                       'issued': self.runner.issued,
                       'fenced': sorted(self.runner.fenced),
                       'receipts': self.runner.receipts},
        })

    @classmethod
    def restore(cls, snapshot, key, expected_digest):
        ref(expected_digest)
        need(cid('SessionSnapshot', snapshot) == expected_digest, 'INTEGRITY')
        fields(snapshot, ('version', 'levels', 'programs', 'plans', 'used',
                          'training_used', 'dataset', 'ledger', 'runner',
                          'active_plan', 'requests_used', 'mission',
                          'mission_id', 'published_contracts', 'contracts',
                          'decisions', 'request_log', 'request_log_bytes',
                          'request_log_head'))
        need(snapshot['version'] == '1.4', 'STALE')
        saved = deepcopy(snapshot)
        need(type(saved['programs']) is dict)
        programs = {}
        for identifier, encoded in saved['programs'].items():
            ref(identifier)
            need(type(encoded) is str)
            program = decode(encoded.encode('ascii'))
            check_agent(program)
            need(cid('Program', program) == identifier, 'INTEGRITY')
            programs[identifier] = program
        saved['programs'] = programs
        ledger = saved['ledger']
        baseline = saved['programs'][ledger['genesis']['active']]
        result = cls(baseline, ledger['genesis']['total'], key,
                     saved['runner']['manifest'], saved['levels'],
                     saved['published_contracts'][ledger['genesis']['active']])
        need(result.mission == saved['mission']
             and result.mission_id == saved['mission_id'], 'AUTHORITY')
        restored = replay(ledger['genesis'], ledger['log'], ledger['head'])
        need(restored == ledger['state'], 'INTEGRITY')
        result.ledger.genesis = ledger['genesis']
        result.ledger.state = restored
        result.ledger.log = ledger['log']
        result.ledger.head = ledger['head']
        for field in ('programs', 'plans', 'dataset', 'published_contracts',
                      'contracts', 'decisions', 'request_log',
                      'request_log_bytes', 'request_log_head'):
            setattr(result, field, saved[field])
        result.used = set(saved['used'])
        result.training_used = set(saved['training_used'])
        result.active_plan = saved['active_plan']
        result.requests_used = saved['requests_used']
        result.runner.fenced = set(saved['runner']['fenced'])
        for field in ('sequence', 'issued', 'receipts'):
            setattr(result.runner, field, saved['runner'][field])
        for envelope in result.runner.receipts.values():
            result.runner.verify(envelope)
        return result

    def prepare(self, candidate, levels, guarantees=None, mode='improve'):
        check_mission(self.mission, self.mission_id)
        check_agent(candidate)
        need(len(self.plans) < 4, 'LIMIT')
        need(type(levels) is list and levels == sorted(set(levels)) and levels)
        for level in levels:
            integer(level, 1, 12)
        need(levels == self.levels == self.mission['levels'], 'PRECONDITION')
        need(mode in ('improve', 'retain'))
        state = self.ledger.state
        need(all(job['phase'] in ('DONE', 'SEALED', 'CANCELLED')
                 for job in state['jobs'].values()), 'PHASE')
        child = cid('Program', candidate)
        parent_contract = self.published_contracts[state['active']]
        child_contract = (deepcopy(parent_contract) if guarantees is None
                          else deepcopy(guarantees))
        validate_guarantees(child_contract)
        need(refines(child_contract, parent_contract)
             and refines(child_contract, self.mission['floor']),
             'PRECONDITION')
        if child in self.published_contracts:
            need(refines(child_contract, self.published_contracts[child]),
                 'PRECONDITION')
        need(child != state['active'] or child_contract != parent_contract,
             'PRECONDITION')
        need(len(canonical(candidate)) <= child_contract['max_program_bytes'],
             'PRECONDITION')
        self.programs[child] = deepcopy(candidate)
        for contract in (parent_contract, child_contract):
            self.contracts[cid('Guarantees', contract)] = deepcopy(contract)
        assignments = []
        candidates = ((state['active'], parent_contract),
                      (child, child_contract))
        for level in levels:
            pair = [self.runner.assign(program, state['generation'], level, 0,
                                       cid('Guarantees', contract))
                    for program, contract in candidates]
            assignments.append(pair)
        plan = {'index': len(self.plans) + 1, 'parent': state['active'],
                'candidate': child, 'generation': state['generation'],
                'manifest': self.runner.manifest, 'environment': ENVIRONMENT,
                'levels': deepcopy(levels), 'assignments': assignments,
                'mode': mode, 'mission': self.mission_id,
                'parent_guarantees': deepcopy(parent_contract),
                'candidate_guarantees': deepcopy(child_contract)}
        identifier = cid('EvaluationPlan', plan)
        self.plans[identifier] = deepcopy(plan)
        return identifier

    def evaluate(self, plan_id):
        need(plan_id in self.plans, 'REFERENCE')
        plan = self.plans[plan_id]
        need(plan['generation'] == self.ledger.state['generation'], 'STALE')
        assignments = [assignment for pair in plan['assignments']
                       for assignment in pair]
        missing = ['j' + str(self.runner.issued[item]['sequence'])
                   for item in assignments]
        missing = [
            job for job in missing if job not in self.ledger.state['jobs']]
        need(self.ledger.state['free'] >= len(missing), 'BUDGET')
        need(self.active_plan in (None, plan_id), 'PHASE')
        if self.active_plan is None:
            need(self.ledger.state['open_runs'] == 0, 'PHASE')
            self.ledger.apply('agent', {'op': 'start_run'})
            self.active_plan = plan_id
        for assignment in assignments:
            binding = self.runner.issued[assignment]
            job = 'j' + str(binding['sequence'])
            if job not in self.ledger.state['jobs']:
                self.ledger.apply('agent', {'op': 'reserve', 'job': job,
                                            'upper': 1})
            phase = self.ledger.state['jobs'][job]['phase']
            need(phase not in ('SEALED', 'CANCELLED'), 'PHASE')
            if phase == 'DONE':
                continue
            if assignment in self.runner.receipts:
                envelope = self.runner.receipts[assignment]
                self.runner.verify(envelope)
            else:
                # Unknown physical completion is never silently retried.
                need(phase == 'RESERVED', 'PHASE')
                self.ledger.apply('executor', {'op': 'dispatch', 'job': job})
                envelope = self.runner.run(
                    assignment, self.programs[binding['candidate']])
            self.ledger.apply('executor', {
                'op': 'complete', 'job': job, 'actual': 1,
                'receipt': cid('Envelope', envelope),
            })
        self.ledger.apply('agent', {'op': 'close_run'})
        self.active_plan = None
        return [deepcopy(self.runner.receipts[assignment])
                for pair in plan['assignments'] for assignment in pair]

    def abandon(self, plan_id):
        '''
        Supervisor capability; reference executor has no
        concurrent processes.
        '''
        need(self.active_plan == plan_id, 'PHASE')
        for pair in self.plans[plan_id]['assignments']:
            for assignment in pair:
                self.runner.fence(assignment)
                job = 'j' + str(self.runner.issued[assignment]['sequence'])
                if job not in self.ledger.state['jobs']:
                    continue
                phase = self.ledger.state['jobs'][job]['phase']
                if phase == 'RESERVED':
                    self.ledger.apply(
                        'supervisor', {
                            'op': 'cancel', 'job': job})
                elif phase in ('RUNNING', 'UNKNOWN'):
                    self.ledger.apply('executor', {'op': 'fence', 'job': job})
                    self.ledger.apply('supervisor', {'op': 'seal', 'job': job})
        self.ledger.apply('agent', {'op': 'close_run'})
        self.active_plan = None
        return True

    def admit(self, plan_id, envelopes):
        check_mission(self.mission, self.mission_id)
        need(plan_id in self.plans, 'REFERENCE')
        plan = self.plans[plan_id]
        state = self.ledger.state
        need(plan['generation'] == state['generation']
             and plan['parent'] == state['active'], 'STALE')
        need(plan['manifest'] == self.runner.manifest
             and plan['environment'] == ENVIRONMENT
             and plan['mission'] == self.mission_id, 'STALE')
        need(plan['parent_guarantees'] ==
             self.published_contracts[state['active']], 'STALE')
        need(refines(plan['candidate_guarantees'], plan['parent_guarantees']),
             'PRECONDITION')
        need(state['open_runs'] == 0, 'PHASE')
        need(all(job['phase'] in ('DONE', 'SEALED', 'CANCELLED')
                 for job in state['jobs'].values()), 'PHASE')
        wanted = [item for pair in plan['assignments'] for item in pair]
        need(type(envelopes) is list and len(envelopes) == len(wanted))
        results = {}
        witnesses = {}
        for envelope in envelopes:
            self.runner.verify(envelope)
            assignment = envelope['receipt']['trace']['assignment']
            need(assignment in wanted and assignment not in results,
                 'DUPLICATE')
            need(assignment not in self.used, 'DUPLICATE')
            binding = envelope['receipt']['binding']
            need(binding == self.runner.issued[assignment], 'INTEGRITY')
            job = self.ledger.state['jobs'].get('j' + str(binding['sequence']))
            need(job is not None and job['phase'] == 'DONE'
                 and job['receipt'] == cid('Envelope', envelope), 'PHASE')
            contract = self.contracts[binding['guarantees']]
            witness = self.evaluator.assess(
                envelope, self.programs[binding['candidate']],
                self.mission, contract)
            assessment = self.evaluator.verify(witness)
            results[assignment] = assessment['outcome']['ground_success']
            witnesses[assignment] = witness
        need(set(results) == set(wanted), 'INTEGRITY')
        pairs = [[results[parent], results[child]]
                 for parent, child in plan['assignments']]
        absolute = all(child for parent, child in pairs)
        retained = all(not witnesses[child]['assessment']['violations']
                       for parent, child in plan['assignments'])
        gain = any(not parent and child for parent, child in pairs)
        need(self.mission['improvement_profile'] == IMPROVEMENT_PROFILE,
             'INTEGRITY')
        costs = [[witnesses[item]['assessment']['cost'] for item in pair]
                 for pair in plan['assignments']]
        comparable = all(parent and child for parent, child in pairs)
        nonworse = comparable and all(
            child[axis] <= parent[axis]
            for parent, child in costs for axis in COST_AXES)
        strict = nonworse and any(
            child[axis] < parent[axis]
            for parent, child in costs for axis in COST_AXES)
        improvement = {
            'profile': IMPROVEMENT_PROFILE, 'success_gain': gain,
            'cost_comparable': comparable, 'cost_nonworse': nonworse,
            'cost_strict': strict, 'cost_pairs': deepcopy(costs),
        }
        accept = absolute and retained and (
            plan['mode'] == 'retain' or gain or strict)
        # All protocol and profile checks precede evidence consumption.
        # A valid completed assessment consumes assignments even on failure.
        self.used.update(wanted)
        certificate = {
            'kind': 'ReleaseDecision', 'plan': plan_id,
            'generation': state['generation'], 'pairs': pairs,
            'accept': accept, 'scope': list(plan['levels']),
            'receipts': sorted(cid('Envelope', item) for item in envelopes),
            'mission': self.mission_id,
            'guarantees': cid('Guarantees', plan['candidate_guarantees']),
            'assessments': [witnesses[key] for key in sorted(witnesses)],
            'improvement': improvement,
        }
        if accept:
            self.ledger.apply('admitter', {
                'op': 'publish', 'candidate': plan['candidate'],
                'generation': plan['generation'],
            })
            self.published_contracts[plan['candidate']] = deepcopy(
                plan['candidate_guarantees'])
        self.decisions.append(deepcopy(certificate))
        return certificate

    def admit_training(self, envelope):
        check_mission(self.mission, self.mission_id)
        outcome = self.runner.verify(envelope)
        trace = envelope['receipt']['trace']
        assignment = trace['assignment']
        need(assignment not in self.training_used, 'DUPLICATE')
        need(outcome['ground_success'], 'INELIGIBLE')
        binding = envelope['receipt']['binding']
        need(binding['manifest'] == self.runner.manifest, 'STALE')
        job = self.ledger.state['jobs'].get('j' + str(binding['sequence']))
        need(job is not None and job['phase'] == 'DONE'
             and job['receipt'] == cid('Envelope', envelope), 'PHASE')
        contract = self.contracts[binding['guarantees']]
        witness = self.evaluator.assess(
            envelope, self.programs[binding['candidate']],
            self.mission, contract)
        assessment = self.evaluator.verify(witness)
        need(not assessment['violations'], 'INELIGIBLE')
        outcome = assessment['outcome']
        certificate = {
            'kind': 'TrainingAdmission', 'profile': 'G12_PATH_1',
            'environment': ENVIRONMENT, 'manifest': self.runner.manifest,
            'assignment': assignment, 'trace': outcome['trace'],
            'mechanism': 'every transition valid and terminal ground goal',
            'scope': {'level': trace['level']},
            'prediction_hits': outcome['prediction_hits'],
            'mission': self.mission_id,
            'guarantees': cid('Guarantees', contract),
            'assessment': witness,
        }
        self.training_used.add(assignment)
        self.dataset[assignment] = {'certificate': certificate,
                                    'trace': deepcopy(trace)}
        return deepcopy(certificate)

    def condense(self, assignments):
        '''Local tabular behavior cloning; this does not publish a release.'''
        need(type(assignments) is list and assignments
             and len(assignments) == len(set(assignments)))
        table = {}
        for assignment in sorted(assignments):
            need(assignment in self.dataset, 'INELIGIBLE')
            record = self.dataset[assignment]
            trace = record['trace']
            need(record['certificate']['trace'] == cid('Trace', trace),
                 'INTEGRITY')
            for step in trace['steps']:
                key = policy_key({'level': trace['level'], **step['before']})
                action = step['intent']['action']
                need(key not in table or table[key] == action, 'CONFLICT')
                table[key] = action
        return {'kind': 'LocalPolicy', 'environment': ENVIRONMENT,
                'sources': sorted(assignments), 'table': table}


def policy_key(observation):
    return cid('PolicyObservation', {
        'environment': ENVIRONMENT, 'level': observation['level'],
        'position': observation['position'], 'key': observation['key'],
        'opened': observation['opened'],
    })


def formalize(policy):
    '''Convert admitted local memory back to an executable bounded program.'''
    from .examples import action, builtin, lit, program, var
    from .environment import AGENT_PARAMS, INTENT_TYPE
    fields(policy, ('kind', 'environment', 'sources', 'table'))
    need(policy['kind'] ==
         'LocalPolicy' and policy['environment'] == ENVIRONMENT)
    table = [{'key': key, 'value': value}
             for key, value in sorted(policy['table'].items())]
    table_type = {'List': {'Record': {'key': 'Text', 'value': 'Text'}}}
    body = action(builtin('lookup_text', lit(table, table_type),
                          builtin('observation_key', var('observation'))))
    result = program(body, {'Option': INTENT_TYPE}, AGENT_PARAMS)
    check(result)
    return result
