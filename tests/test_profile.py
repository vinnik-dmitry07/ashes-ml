from copy import deepcopy
from fractions import Fraction
from math import comb
import unittest

import artifacts
import contracts
import decisions
import evidence
from examples.scenario import fixture, report, value
from kernel import core
import system
import workflow


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.policy, self.registry, self.configuration = fixture()
        self.state = system.initial(self.policy, self.registry, self.configuration)
        self.serial = 0

    def event(self, kind, principal='agent', **fields):
        self.serial += 1
        event = {'id': 'e' + str(self.serial), 'kind': kind, **fields}
        before = deepcopy(self.state)
        self.state, result, requests = system.step(self.state, principal, event)
        self.assertTrue(system.invariants(self.state))
        self.assertEqual(before['policy'], self.state['policy'])
        return result, requests

    def proposal(self, name='proposal1', change=1):
        candidate = deepcopy(self.configuration)
        candidate['program']['fuel'] += change
        result, _ = self.event('propose', proposal=name, configuration=candidate)
        self.assertEqual(result['code'], 'OK')
        return result['configuration']

    def trial(self, name='trial1', proposal='proposal1', claim='improve'):
        result, _ = self.event('start_trial', trial=name, proposal=proposal, claim=claim)
        self.assertEqual(result['code'], 'OK')

    def assess(self, name='trial1', data=None, charge=6):
        return self.event(
            'assessment', principal='provider', trial=name, charge=charge,
            outcome={'kind': 'report', 'report': report() if data is None else data},
        )[0]

    def start_execution(self):
        result, _ = self.event('start_run', run='run1', args={'x': value(2)})
        self.assertEqual(result['code'], 'OK')
        return self.event('drive', run='run1')

    def complete(self, output=3, charge=3):
        return self.event('deliver', principal='provider', run='run1', event={
            'id': 'provider-event', 'kind': 'complete', 'job': 'J1',
            'charge': charge, 'outcome': {
                'kind': 'success', 'value': value(output),
                'writes': [{'op': 'replace', 'cell': 'memory', 'value': value(9)}],
            },
        })[0]

    def test_typed_execution_and_global_conservation(self):
        _, requests = self.start_execution()
        self.assertEqual(len(requests), 1)
        self.assertEqual(self.state['available'], 90)
        self.assertEqual(self.complete()['result']['code'], 'SUCCESS')
        self.event('drive', run='run1')
        self.event('drive', run='run1')
        self.assertEqual(self.state['runs']['run1']['vm']['result'], value(3))
        result, _ = self.event('close_run', run='run1')
        self.assertEqual(result['code'], 'OK')
        self.assertEqual((self.state['available'], self.state['spent']), (97, 3))

    def test_protected_postcondition_rejects_writes_but_settles_charge(self):
        self.start_execution()
        result = self.complete(output=1)
        self.assertEqual(result['result']['detail'], 'POSTCONDITION')
        kernel = self.state['runs']['run1']['kernel']
        self.assertEqual(kernel['cells']['memory']['value'], value(0))
        self.assertEqual(self.state['spent'], 3)

    def test_protected_precondition_prevents_dispatch(self):
        self.policy['contracts']['transform']['pre'] = {'op': 'false'}
        self.state = system.initial(self.policy, self.registry, self.configuration)
        _, requests = self.start_execution()
        self.assertEqual(requests, [])
        kernel = self.state['runs']['run1']['kernel']
        self.assertEqual(kernel['available'], 10)
        self.assertEqual(kernel['jobs']['J1']['status'], 'cancelled')

    def test_final_contract_cannot_be_bypassed_by_halt(self):
        program = self.configuration['program']
        program['entry'] = 'finish'
        self.state = system.initial(self.policy, self.registry, self.configuration)
        self.start_execution()
        vm = self.state['runs']['run1']['vm']
        self.assertEqual(vm['status'], 'failed')
        self.assertIsNone(vm['result'])

    def test_external_input_precondition(self):
        self.policy['interface']['pre'] = {'op': 'false'}
        self.state = system.initial(self.policy, self.registry, self.configuration)
        result, _ = self.event('start_run', run='run1', args={'x': value(2)})
        self.assertEqual(result['code'], 'INPUT_PRECONDITION')
        self.assertEqual(self.state['available'], 100)

    def test_interface_change_is_invalid(self):
        candidate = deepcopy(self.configuration)
        candidate['program']['inputs'] = []
        result, _ = self.event('propose', proposal='bad', configuration=candidate)
        self.assertEqual(result['code'], 'INVALID_CONFIGURATION')

    def test_protected_initial_cell_cannot_change_through_candidate(self):
        self.policy['initializable'] = []
        self.state = system.initial(self.policy, self.registry, self.configuration)
        candidate = deepcopy(self.configuration)
        candidate['initial']['memory'] = value(999)
        result, _ = self.event('propose', proposal='bad-initial', configuration=candidate)
        self.assertEqual(result['code'], 'INVALID_CONFIGURATION')

    def test_unknown_retains_budget_and_prevents_close(self):
        self.start_execution()
        self.event('deliver', principal='provider', run='run1', event={
            'id': 'inner', 'kind': 'unknown', 'job': 'J1',
        })
        self.event('drive', run='run1')
        self.event('drive', run='run1')
        result, _ = self.event('close_run', run='run1')
        self.assertEqual(result['code'], 'JOBS_PENDING')
        self.assertEqual(self.state['available'], 90)
        self.assertEqual(self.state['runs']['run1']['kernel']['jobs']['J1']['held'], 4)
        self.complete()
        result, _ = self.event('close_run', run='run1')
        self.assertEqual(result['code'], 'OK')

    def test_wait_is_not_a_retry_or_fuel_consumption(self):
        self.start_execution()
        before = self.state['runs']['run1']['vm']['fuel']
        for _ in range(3):
            result, outgoing = self.event('drive', run='run1')
            self.assertEqual(result['code'], 'WAITING')
            self.assertEqual(outgoing, [])
        self.assertEqual(before, self.state['runs']['run1']['vm']['fuel'])

    def test_invalidation_rejects_late_write_and_new_runs(self):
        self.start_execution()
        self.event('invalidate_context', principal='supervisor', context='v2')
        result = self.complete()
        self.assertEqual(result['result']['code'], 'STALE_POLICY')
        result, _ = self.event('drive', run='run1')
        self.assertEqual(result['code'], 'STALE_RUN')
        self.event('close_run', run='run1')
        result, _ = self.event('start_run', run='run2', args={'x': value(2)})
        self.assertEqual(result['code'], 'REVALIDATION_REQUIRED')

    def test_release_requires_independent_report_and_is_replayable(self):
        candidate = self.proposal()
        self.trial()
        result = self.assess()
        self.assertTrue(result['verdict']['accepted'])
        self.event('publish', trial='trial1')
        self.assertEqual(self.state['active'], candidate)
        self.assertEqual(self.state['generation'], 1)
        replayed = system.replay(
            self.policy, self.registry, self.configuration, self.state['log'],
        )
        self.assertEqual(replayed, self.state)

    def test_quiescence_required_for_release(self):
        self.proposal()
        self.trial()
        self.assess()
        self.start_execution()
        result, _ = self.event('publish', trial='trial1')
        self.assertEqual(result['code'], 'RUNS_OPEN')

    def test_stale_report_is_charged_and_consumed(self):
        self.proposal()
        self.trial()
        self.event('invalidate_context', principal='supervisor', context='v2')
        result = self.assess()
        self.assertEqual(result['verdict']['code'], 'STALE_EVIDENCE')
        self.assertEqual(self.state['spent'], 6)
        self.assertEqual(len(self.state['used_samples']), 128)

    def test_reused_samples_rejected(self):
        self.proposal()
        self.trial()
        self.assess()
        self.trial(name='trial2')
        result = self.assess(name='trial2')
        self.assertEqual(result['verdict']['code'], 'REUSED_SAMPLE')
        self.assertEqual(self.state['trial_count'], 2)

    def test_duplicate_within_report_rejected(self):
        self.proposal()
        self.trial()
        data = report()
        data['strata']['composition'][1]['id'] = data['strata']['composition'][0]['id']
        self.assertEqual(self.assess(data=data)['verdict']['code'], 'REUSED_SAMPLE')

    def test_aba_does_not_resurrect_certificate(self):
        baseline = self.state['active']
        self.proposal()
        self.trial()
        self.trial(name='trial2')
        self.assess()
        self.assess(name='trial2', data=report('fresh'))
        self.event('publish', trial='trial1')
        self.event('rollback', principal='supervisor', configuration=baseline)
        result, _ = self.event('publish', trial='trial2')
        self.assertEqual(result['code'], 'STALE_EVIDENCE')
        self.assertEqual(self.state['trial_count'], 2)
        self.assertEqual(self.state['spent'], 12)

    def test_wrong_report_size_consumes_cost_not_certificate(self):
        self.proposal()
        self.trial()
        data = report()
        data['strata']['composition'].pop()
        result = self.assess(data=data)
        self.assertEqual(result['verdict']['code'], 'PROTOCOL_MISMATCH')
        self.assertEqual(self.state['spent'], 6)

    def test_forged_assessment_role_and_field_rejected(self):
        self.proposal()
        self.trial()
        result, _ = self.event('assessment', trial='trial1', charge=0,
                               outcome={'kind': 'report', 'report': report()})
        self.assertEqual(result['code'], 'FORBIDDEN')
        result, _ = self.event('publish', trial='trial1', accepted=True)
        self.assertEqual(result['code'], 'BAD_SCHEMA')

    def test_event_replay_never_redispatches(self):
        self.start_execution()
        record = deepcopy(self.state['log'][-1])
        state, result, outgoing = system.step(
            self.state, record['principal'], record['event'],
        )
        self.assertEqual(state, self.state)
        self.assertEqual(result, record['result'])
        self.assertEqual(outgoing, [])
        altered = dict(record['event'], run='different')
        _, result, _ = system.step(self.state, 'agent', altered)
        self.assertEqual(result['code'], 'EVENT_ID_REUSE')

    def test_rejected_schema_does_not_consume_event_id(self):
        before = deepcopy(self.state)
        event = {'id': 'bad', 'kind': 'drive', 'run': 'x', 'extra': True}
        after, result, _ = system.step(before, 'agent', event)
        self.assertEqual(result['code'], 'BAD_SCHEMA')
        self.assertEqual(before, after)

    def test_statistical_gate_rejects_observed_violation(self):
        self.proposal()
        self.trial()
        data = report()
        data['violations'] = 1
        self.assertFalse(self.assess(data=data)['verdict']['accepted'])

    def test_retention_is_not_an_improvement_claim(self):
        self.proposal()
        self.trial(claim='retain')
        data = report(parent=True, candidate=True)
        self.assertTrue(self.assess(data=data)['verdict']['accepted'])
        self.trial(name='trial2')
        data = report('other', parent=True, candidate=True)
        self.assertFalse(self.assess(name='trial2', data=data)['verdict']['accepted'])

    def test_insufficient_global_budget(self):
        self.policy['total_budget'] = 7
        self.state = system.initial(self.policy, self.registry, self.configuration)
        self.proposal()
        result, outgoing = self.event('start_trial', trial='t', proposal='proposal1',
                                      claim='improve')
        self.assertEqual((result['code'], outgoing), ('BUDGET', []))
        self.assertEqual(self.state['trial_count'], 0)

    def test_missing_artifact_dependencies(self):
        artifact = deepcopy(self.registry[0])
        artifact['dependencies'] = ['missing']
        result, _ = self.event('add_artifact', artifact=artifact)
        self.assertEqual(result['code'], 'MISSING_DEPENDENCY')

    def test_loop_fuel_is_bounded(self):
        program = self.configuration['program']
        program['nodes'] = {'loop': {'op': 'jump', 'next': 'loop'}}
        program['entry'] = 'loop'
        program['fuel'] = 2
        self.state = system.initial(self.policy, self.registry, self.configuration)
        self.start_execution()
        self.event('drive', run='run1')
        result, _ = self.event('drive', run='run1')
        self.assertEqual(result['code'], 'FUEL_EXHAUSTED')

    def test_type_error_and_unknown_opcode_rejected(self):
        for change in ({'op': 'Repeat'}, {'op': 'branch', 'test': {'literal': value(1)},
                                        'then': 'finish', 'else': 'finish'}):
            program = deepcopy(self.configuration['program'])
            program['nodes']['invoke'] = change
            with self.assertRaises(core.SchemaError):
                workflow.validate(program, self.policy['manifest'])

    def test_contract_cannot_read_undeclared_cell(self):
        component = deepcopy(self.policy['manifest']['components']['transform'])
        component['read'], component['write'] = [], []
        pred = {'op': 'eq', 'left': {'before': 'memory'},
                'right': {'literal': value(1)}}
        with self.assertRaises(core.SchemaError):
            contracts.validate_predicate(pred, component, self.policy['manifest']['cells'], 'pre')

    def test_parallel_calls_are_subject_to_snapshot_conflicts(self):
        program = self.configuration['program']
        program['handles']['second'] = 'transform'
        program['nodes']['invoke']['ok'] = 'invoke2'
        program['nodes']['invoke2'] = dict(
            program['nodes']['invoke'], handle='second', ok='wait',
        )
        self.state = system.initial(self.policy, self.registry, self.configuration)
        self.start_execution()
        _, requests = self.event('drive', run='run1')
        self.assertEqual(requests[0]['request']['job'], 'J2')
        self.complete()
        result, _ = self.event('deliver', principal='provider', run='run1', event={
            'id': 'reply2', 'kind': 'complete', 'job': 'J2', 'charge': 2,
            'outcome': {'kind': 'success', 'value': value(5), 'writes': [
                {'op': 'replace', 'cell': 'memory', 'value': value(10)},
            ]},
        })
        self.assertEqual(result['result']['code'], 'CONFLICT')
        self.assertEqual(self.state['spent'], 5)

    def test_context_revalidation_does_not_reset_statistical_budget(self):
        self.proposal()
        self.trial()
        self.assess()
        self.event('invalidate_context', principal='supervisor', context='v2')
        result, _ = self.event('rollback', principal='supervisor',
                               configuration=self.state['active'])
        self.assertEqual(result['code'], 'REVALIDATION_REQUIRED')
        self.event('propose', proposal='revalidate', configuration=self.configuration)
        self.trial(name='trial2', proposal='revalidate', claim='retain')
        self.assess(name='trial2', data=report('v2sample', True, True))
        result, _ = self.event('publish', trial='trial2')
        self.assertEqual(result['code'], 'OK')
        self.assertEqual(self.state['trial_count'], 2)
        result, _ = self.event('start_run', run='fresh', args={'x': value(2)})
        self.assertEqual(result['code'], 'OK')


class MathematicalTests(unittest.TestCase):
    def test_mcnemar_small_exact_cases(self):
        self.assertEqual(evidence.gain_p(0, 0), 1)
        self.assertEqual(evidence.gain_p(3, 0), Fraction(1, 8))
        self.assertEqual(evidence.gain_p(2, 1), Fraction(1, 2))

    def test_loss_exact_case(self):
        self.assertEqual(evidence.loss_p(3, 0, Fraction(1, 2)), Fraction(1, 8))

    def test_gain_test_type_one_error_exhaustive_small_null(self):
        alpha = Fraction(1, 20)
        for n in range(1, 15):
            probability = sum((
                Fraction(comb(n, wins), 2 ** n)
                for wins in range(n + 1)
                if evidence.gain_p(wins, n - wins) <= alpha
            ), Fraction(0))
            self.assertLessEqual(probability, alpha)

    def test_loss_test_type_one_error_exhaustive_small_boundary(self):
        alpha, tolerance = Fraction(1, 20), Fraction(1, 5)
        for n in range(1, 15):
            probability = sum((
                comb(n, losses) * tolerance ** losses * (1 - tolerance) ** (n - losses)
                for losses in range(n + 1)
                if evidence.loss_p(n, losses, tolerance) <= alpha
            ), Fraction(0))
            self.assertLessEqual(probability, alpha)

    def test_alpha_spending_telescopes(self):
        self.assertEqual(sum((Fraction(1, r * (r + 1)) for r in range(1, 101)),
                             Fraction(0)), Fraction(100, 101))

    def test_canonical_identity_and_json_boundaries(self):
        self.assertEqual(artifacts.content_id({'b': 1, 'a': 2}),
                         artifacts.content_id({'a': 2, 'b': 1}))
        for invalid in (1.0, -1, {1: 'bad'}, {'bad': '\ud800'}):
            with self.assertRaises(core.SchemaError):
                artifacts.content_id(invalid)

    def test_aggregation_ties_abstention_and_invalid_ballots(self):
        vote = decisions.plurality(['b', 'a'], {'v1': 'b', 'v2': 'a', 'v3': None}, 2)
        self.assertEqual(vote['winner'], 'a')
        self.assertIsNone(decisions.plurality(['a'], {'v1': None}, 0)['winner'])
        with self.assertRaises(core.SchemaError):
            decisions.borda(['a', 'b'], {'v1': ['a']}, 1)
        self.assertEqual(decisions.borda(['a', 'b'], {'v1': ['b', 'a']}, 1)['winner'], 'b')

    def test_pareto_preserves_equal_vectors_and_tradeoffs(self):
        points = {'a': [1, 2], 'b': [1, 2], 'c': [2, 1], 'd': [3, 3]}
        self.assertEqual(decisions.pareto(points, ['min', 'min']), ['a', 'b', 'c'])


if __name__ == '__main__':
    unittest.main()
