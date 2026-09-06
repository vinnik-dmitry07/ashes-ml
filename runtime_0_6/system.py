'''AHSL 0.6 release and execution transition system.

Pure reference model: identity, provider honesty, isolation and durable
delivery are obligations of an external adapter, not implemented here.
'''

from copy import deepcopy

import artifacts
import contracts
import evidence
from kernel import core
import workflow


ROLE = {
    'add_artifact': 'agent', 'propose': 'agent', 'start_trial': 'agent',
    'publish': 'agent', 'start_run': 'agent', 'drive': 'agent',
    'close_run': 'agent', 'assessment': 'provider', 'deliver': 'provider',
    'invalidate_context': 'supervisor', 'rollback': 'supervisor',
}
EXTRA = {
    'add_artifact': ('artifact',), 'propose': ('proposal', 'configuration'),
    'start_trial': ('trial', 'proposal', 'claim'), 'publish': ('trial',),
    'start_run': ('run', 'args'), 'drive': ('run',), 'close_run': ('run',),
    'assessment': ('trial', 'charge', 'outcome'), 'deliver': ('run', 'event'),
    'invalidate_context': ('context',), 'rollback': ('configuration',),
}


class Reject(Exception):
    pass


def guard(condition, code):
    if not condition:
        raise Reject(code)


def validate_policy(policy):
    core.fields(policy, (
        'version', 'manifest', 'total_budget', 'context', 'alpha', 'strata',
        'evaluation_cost', 'max_trials', 'max_runs', 'contracts', 'interface',
        'initializable',
    ))
    core.require(policy['version'] == '0.6')
    core.initial(policy['manifest'])
    core.names(policy['initializable'])
    core.require(set(policy['initializable']) <= set(policy['manifest']['cells']))
    core.require(type(policy['contracts']) is dict)
    core.require(set(policy['contracts']) == set(policy['manifest']['components']))
    for name, contract in policy['contracts'].items():
        core.fields(contract, ('pre', 'post'))
        for phase in ('pre', 'post'):
            contracts.validate_predicate(
                contract[phase], policy['manifest']['components'][name],
                policy['manifest']['cells'], phase,
            )
    interface = policy['interface']
    core.fields(interface, ('inputs', 'output', 'pre', 'post'))
    core.require(type(interface['inputs']) is dict)
    for name, tag in interface['inputs'].items():
        core.identifier(name)
        core.type_name(tag)
    core.type_name(interface['output'])
    signature = dict(interface, read=[], write=[])
    for phase in ('pre', 'post'):
        contracts.validate_predicate(interface[phase], signature, {}, phase)
    for name in ('total_budget', 'evaluation_cost', 'max_trials', 'max_runs'):
        core.nat(policy[name])
    core.require(policy['max_trials'] > 0 and policy['max_runs'] > 0)
    core.identifier(policy['context'])
    evidence.validate_protocol(policy)
    artifacts.canonical(policy)


def initial(policy, artifact_list, configuration):
    validate_policy(policy)
    core.require(type(artifact_list) is list)
    registry = {}
    for artifact in artifact_list:
        artifacts.add(registry, artifact)
    artifacts.validate_configuration(policy, registry, configuration)
    reference = artifacts.configuration_id(policy, configuration)
    return {
        'policy': deepcopy(policy), 'policy_hash': artifacts.content_id(policy),
        'artifacts': registry, 'configurations': {reference: deepcopy(configuration)},
        'active': reference, 'generation': 0, 'epoch': 0,
        'context': policy['context'], 'active_epoch': 0,
        'activated': {reference: 0}, 'proposals': {}, 'trials': {}, 'runs': {},
        'trial_count': 0, 'used_samples': [],
        'available': policy['total_budget'], 'spent': 0,
        'seen': {}, 'log': [],
    }


def validate_event(event):
    core.require(type(event) is dict)
    kind = event.get('kind')
    core.require(type(kind) is str and kind in ROLE)
    core.fields(event, ('id', 'kind') + EXTRA[kind])
    core.identifier(event['id'])
    for name in ('proposal', 'trial', 'run', 'context'):
        if name in event:
            core.identifier(event[name])
    if kind == 'add_artifact':
        artifacts.validate(event['artifact'])
    elif kind == 'propose':
        artifacts.canonical(event['configuration'])
    elif kind == 'start_trial':
        core.require(event['claim'] in ('improve', 'retain'))
    elif kind == 'start_run':
        core.named_values(event['args'])
    elif kind == 'rollback':
        core.identifier(event['configuration'])
    elif kind == 'deliver':
        core.validate_event(event['event'])
        core.require(event['event']['kind'] in ('complete', 'unknown'))
    elif kind == 'assessment':
        core.nat(event['charge'])
        outcome = event['outcome']
        core.require(type(outcome) is dict)
        if outcome.get('kind') == 'failure':
            core.fields(outcome, ('kind', 'code'))
            core.identifier(outcome['code'])
        else:
            core.fields(outcome, ('kind', 'report'))
            core.require(outcome['kind'] == 'report')
            evidence.validate_report(outcome['report'])


def current(state, item):
    return (
        item['parent'] == state['active']
        and item['generation'] == state['generation']
        and item['epoch'] == state['epoch']
        and item['context'] == state['context']
    )


def quiescent(state):
    return all(run['closed'] for run in state['runs'].values())


def publish_configuration(state, reference):
    guard(state['generation'] < core.MAX_NAT, 'GENERATION_EXHAUSTED')
    state['active'] = reference
    state['generation'] += 1
    state['active_epoch'] = state['epoch']
    state['activated'][reference] = state['epoch']


def settle_assessment(state, event):
    trial = state['trials'].get(event['trial'])
    guard(trial is not None, 'NO_TRIAL')
    guard(trial['status'] == 'pending', 'BAD_PHASE')
    charge = event['charge']
    guard(charge <= trial['held'], 'CHARGE_EXCEEDS_RESERVE')
    outcome = event['outcome']
    verdict = {'accepted': False, 'code': 'EVALUATOR_FAILURE', 'tests': {}}
    if outcome['kind'] == 'report':
        report = outcome['report']
        ids = evidence.sample_ids(report)
        fresh = (
            len(ids) == len(set(ids))
            and not set(ids).intersection(state['used_samples'])
        )
        # Even a rejected or stale well-formed report consumes its sample IDs.
        state['used_samples'] = sorted(set(state['used_samples']).union(ids))
        if not fresh:
            verdict['code'] = 'REUSED_SAMPLE'
        elif not current(state, trial):
            verdict['code'] = 'STALE_EVIDENCE'
        else:
            verdict = evidence.assess(
                state['policy'], trial['number'], trial['claim'], report,
            )
    state['available'] += trial['held'] - charge
    state['spent'] += charge
    trial.update(status='done', held=0, charged=charge, verdict=verdict)
    return core.answer('SETTLED', verdict=deepcopy(verdict)), []


def deliver(state, event):
    run = state['runs'].get(event['run'])
    guard(run is not None, 'NO_RUN')
    guard(not run['closed'], 'RUN_CLOSED')
    kernel = run['kernel']
    inner = deepcopy(event['event'])
    inner['id'] = 'p' + artifacts.content_id(event['id'])
    job = kernel['jobs'].get(inner['job'])
    if (
        inner['kind'] == 'complete'
        and job is not None
        and job['status'] in ('running', 'unknown')
        and inner['charge'] <= job['held']
        and inner['outcome']['kind'] == 'success'
        and core.proposal_error(kernel, job, inner['outcome']) is None
    ):
        configuration = state['configurations'][run['configuration']]
        skills = artifacts.skills_for(state['artifacts'], configuration, state['policy'])
        outcome = inner['outcome']
        after = deepcopy(job['snapshot'])
        for write in outcome['writes']:
            cell = after[write['cell']]
            cell['version'] += 1
            cell['live'] = write['op'] != 'delete'
            if write['op'] != 'delete':
                cell['value'] = deepcopy(write['value'])
        if not contracts.evaluate(
            skills[job['component']]['post'], job['args'], job['snapshot'],
            after, outcome['value'],
        ):
            inner['outcome'] = {'kind': 'failure', 'code': 'POSTCONDITION'}
    updated, result, requests = core.step(kernel, 'provider', inner)
    state['spent'] += updated['spent'] - kernel['spent']
    run['kernel'] = updated
    return result, requests


def apply_event(state, event):
    kind = event['kind']
    policy = state['policy']
    if kind == 'add_artifact':
        artifact = event['artifact']
        guard(
            set(artifact['dependencies']) <= set(state['artifacts']),
            'MISSING_DEPENDENCY',
        )
        reference = artifacts.add(state['artifacts'], artifact)
        return core.answer('OK', artifact=reference), []
    if kind == 'propose':
        guard(event['proposal'] not in state['proposals'], 'PROPOSAL_EXISTS')
        configuration = event['configuration']
        try:
            artifacts.validate_configuration(policy, state['artifacts'], configuration)
        except (core.SchemaError, TypeError):
            raise Reject('INVALID_CONFIGURATION') from None
        reference = artifacts.configuration_id(policy, configuration)
        state['configurations'][reference] = deepcopy(configuration)
        state['proposals'][event['proposal']] = {
            'parent': state['active'], 'generation': state['generation'],
            'epoch': state['epoch'], 'context': state['context'],
            'configuration': reference,
        }
        return core.answer('OK', configuration=reference), []
    if kind == 'start_trial':
        guard(event['trial'] not in state['trials'], 'TRIAL_EXISTS')
        proposal = state['proposals'].get(event['proposal'])
        guard(proposal is not None, 'NO_PROPOSAL')
        guard(current(state, proposal), 'STALE_PROPOSAL')
        guard(state['trial_count'] < policy['max_trials'], 'TRIAL_LIMIT')
        guard(state['available'] >= policy['evaluation_cost'], 'BUDGET')
        state['trial_count'] += 1
        state['available'] -= policy['evaluation_cost']
        trial = dict(
            deepcopy(proposal), number=state['trial_count'],
            claim=event['claim'], status='pending',
            held=policy['evaluation_cost'], charged=0, verdict=None,
        )
        state['trials'][event['trial']] = trial
        request = {
            'kind': 'EvaluationRequest', 'trial': event['trial'],
            'policy': state['policy_hash'], 'parent': trial['parent'],
            'candidate': trial['configuration'], 'context': trial['context'],
            'epoch': trial['epoch'], 'generation': trial['generation'],
            'number': trial['number'], 'claim': trial['claim'],
            'strata': deepcopy(policy['strata']),
            'max_charge': trial['held'],
        }
        return core.answer('OK'), [request]
    if kind == 'assessment':
        return settle_assessment(state, event)
    if kind == 'publish':
        trial = state['trials'].get(event['trial'])
        guard(trial is not None, 'NO_TRIAL')
        guard(trial['status'] == 'done', 'BAD_PHASE')
        guard(trial['verdict']['accepted'], 'NOT_ACCEPTED')
        guard(current(state, trial), 'STALE_EVIDENCE')
        guard(quiescent(state), 'RUNS_OPEN')
        publish_configuration(state, trial['configuration'])
        return core.answer('OK', configuration=state['active']), []
    if kind == 'start_run':
        guard(event['run'] not in state['runs'], 'RUN_EXISTS')
        guard(len(state['runs']) < policy['max_runs'], 'RUN_LIMIT')
        guard(state['active_epoch'] == state['epoch'], 'REVALIDATION_REQUIRED')
        amount = policy['manifest']['budget']
        guard(state['available'] >= amount, 'BUDGET')
        configuration = state['configurations'][state['active']]
        try:
            vm = workflow.initial(configuration['program'], event['args'])
        except (core.SchemaError, TypeError):
            raise Reject('INPUT_TYPE') from None
        guard(contracts.evaluate(
            policy['interface']['pre'], event['args'], {},
        ), 'INPUT_PRECONDITION')
        state['available'] -= amount
        state['runs'][event['run']] = {
            'configuration': state['active'], 'epoch': state['epoch'],
            'kernel': core.initial(artifacts.manifest_for(policy, configuration)),
            'vm': vm, 'closed': False, 'args': deepcopy(event['args']),
        }
        return core.answer('OK'), []
    if kind == 'drive':
        run = state['runs'].get(event['run'])
        guard(run is not None, 'NO_RUN')
        guard(not run['closed'], 'RUN_CLOSED')
        guard(run['epoch'] == state['epoch'], 'STALE_RUN')
        configuration = state['configurations'][run['configuration']]
        vm, kernel, outgoing, code = workflow.advance(
            configuration['program'], run['vm'], run['kernel'],
            artifacts.skills_for(state['artifacts'], configuration, policy),
        )
        if vm['status'] == 'halted' and not contracts.evaluate(
            policy['interface']['post'], run['args'], {}, {}, vm['result'],
        ):
            vm['status'] = 'failed'
            vm['failure'] = 'OUTPUT_POSTCONDITION'
            vm['result'] = None
        run['vm'], run['kernel'] = vm, kernel
        requests = [{
            'kind': 'ComponentRequest', 'run': event['run'],
            'configuration': run['configuration'], 'epoch': run['epoch'],
            'context': state['context'],
            'skill': configuration['bindings'][request['component']],
            'request': request,
        } for request in outgoing]
        return core.answer(code), requests
    if kind == 'deliver':
        return deliver(state, event)
    if kind == 'close_run':
        run = state['runs'].get(event['run'])
        guard(run is not None, 'NO_RUN')
        guard(not run['closed'], 'RUN_CLOSED')
        guard(
            run['vm']['status'] in ('halted', 'exhausted', 'failed')
            or run['epoch'] != state['epoch'], 'NOT_TERMINAL',
        )
        guard(all(
            job['status'] in ('done', 'cancelled')
            for job in run['kernel']['jobs'].values()
        ), 'JOBS_PENDING')
        state['available'] += policy['manifest']['budget'] - run['kernel']['spent']
        run['closed'] = True
        return core.answer('OK'), []
    if kind == 'invalidate_context':
        guard(event['context'] != state['context'], 'SAME_CONTEXT')
        guard(state['epoch'] < core.MAX_NAT, 'EPOCH_EXHAUSTED')
        for name, run in sorted(state['runs'].items()):
            if run['closed']:
                continue
            for component in sorted(policy['manifest']['components']):
                inner = {
                    'id': 's' + artifacts.content_id([event['id'], name, component]),
                    'kind': 'revoke', 'component': component,
                }
                kernel, result, _ = core.step(run['kernel'], 'supervisor', inner)
                guard(result['code'] == 'OK', result['code'])
                run['kernel'] = kernel
        state['context'] = event['context']
        state['epoch'] += 1
        return core.answer('OK'), []
    # The only remaining validated kind is rollback.
    reference = event['configuration']
    guard(reference in state['activated'], 'NEVER_ACTIVATED')
    guard(state['activated'][reference] == state['epoch'], 'REVALIDATION_REQUIRED')
    guard(quiescent(state), 'RUNS_OPEN')
    publish_configuration(state, reference)
    return core.answer('OK', configuration=reference), []


def step(state, principal, event):
    try:
        core.require(type(principal) is str and principal in core.PRINCIPALS)
        validate_event(event)
    except (core.SchemaError, TypeError):
        return deepcopy(state), core.answer('BAD_SCHEMA'), []
    previous = state['seen'].get(event['id'])
    if previous is not None:
        if previous['principal'] != principal or previous['event'] != event:
            return deepcopy(state), core.answer('EVENT_ID_REUSE'), []
        return deepcopy(state), deepcopy(previous['result']), []
    updated = deepcopy(state)
    if ROLE[event['kind']] != principal:
        result, requests = core.answer('FORBIDDEN'), []
    else:
        try:
            result, requests = apply_event(updated, event)
        except Reject as exc:
            updated = deepcopy(state)
            result, requests = core.answer(str(exc)), []
    record = {'principal': principal, 'event': deepcopy(event), 'result': deepcopy(result)}
    updated['seen'][event['id']] = deepcopy(record)
    updated['log'].append(record)
    return updated, deepcopy(result), deepcopy(requests)


def invariants(state):
    policy = state['policy']
    held_runs = sum(
        policy['manifest']['budget'] - run['kernel']['spent']
        for run in state['runs'].values() if not run['closed']
    )
    held_trials = sum(trial['held'] for trial in state['trials'].values())
    actual_spent = (
        sum(run['kernel']['spent'] for run in state['runs'].values())
        + sum(trial['charged'] for trial in state['trials'].values())
    )
    return (
        state['policy_hash'] == artifacts.content_id(policy)
        and state['active'] in state['configurations']
        and state['available'] >= 0 and state['spent'] >= 0
        and state['available'] + state['spent'] + held_runs + held_trials
        == policy['total_budget']
        and state['spent'] == actual_spent
        and state['trial_count'] == len(state['trials'])
        and all(core.invariants(run['kernel']) for run in state['runs'].values())
        and all(
            reference == artifacts.content_id(artifact)
            and set(artifact['dependencies']) <= set(state['artifacts'])
            for reference, artifact in state['artifacts'].items()
        )
    )


def replay(policy, artifact_list, configuration, records):
    state = initial(policy, artifact_list, configuration)
    for record in records:
        state, result, _ = step(state, record['principal'], record['event'])
        core.require(result == record['result'])
    return state
