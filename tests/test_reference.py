'''Executable audit regressions and contract boundary checks.'''

from copy import deepcopy
from fractions import Fraction
import itertools
import unittest

from src.admission import Session, assess_pairs, exact_pair_tests, formalize
from src.codec import Rejected, canonical, cid, decode, fraction, rat
from src.decisions import brier, expected, plurality, regret
from src.environment import (
    ACTIONS, ENVIRONMENT, Runner, audit_trace, goal, initial, observe,
    solution, transition, verify_edge,
)
from src.examples import (
    builtin,
    call,
    corridor_agent,
    council,
    function,
    group_relative_controller,
    islands,
    lit,
    program,
    recursive_context,
    var,
)
from src.kernel import Ledger, invariant, replay, step
from src.knowledge import compose, mutate_literal, trim_alias
from src.language import check, execute
from src.proofs import certify, check_certificate, formula, search
from src.types import type_ok, value_ok


MANIFEST = cid('TestManifest', {'version': 1})
KEY = b'reference-test-only-not-production-secret'
A = cid('TestCandidate', 'A')
B = cid('TestCandidate', 'B')


class Base(unittest.TestCase):
    def rejects(self, code, function, *args, **kwargs):
        with self.assertRaises(Rejected) as raised:
            function(*args, **kwargs)
        self.assertEqual(str(raised.exception), code)

    def session(self, levels=None):
        return Session(corridor_agent('paint'), 96, KEY, MANIFEST,
                       [1, 2] if levels is None else levels)


class CodecTests(Base):
    def test_every_production_hash_domain_has_a_named_schema(self):
        import ast
        from pathlib import Path
        from src.schema import HASH_KINDS
        root = Path(__file__).resolve().parents[1] / 'src'
        used = set()
        for path in root.glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == 'cid'
                        and node.args
                        and isinstance(node.args[0], ast.Constant)):
                    used.add(node.args[0].value)
        self.assertLessEqual(used, set(HASH_KINDS))

    def test_manifest_covers_init_and_detects_added_source(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import verify
        original = verify.ROOT
        try:
            with TemporaryDirectory() as directory:
                verify.ROOT = Path(directory)
                (verify.ROOT / '__init__.py').write_text('')
                pinned = verify.manifest()
                self.assertIn('__init__.py', pinned)
                (verify.ROOT / 'unlisted.py').write_text('x = 1\n')
                self.assertNotEqual(verify.manifest(), pinned)
        finally:
            verify.ROOT = original

    def test_frozen_vectors_and_schema_export(self):
        import json
        from pathlib import Path
        from src.schema import SCHEMAS
        root = Path(__file__).resolve().parents[1]
        cases = json.loads((root / 'encoding-vectors.json').read_text())
        for case in cases:
            self.assertEqual(canonical(case['value']).hex(), case['bytes_hex'])
            self.assertEqual(cid('EncodingFixture', case['value']), case['id'])
        self.assertEqual(
            json.loads(
                (root / 'protocol-schemas.json').read_text()),
            SCHEMAS)

    def test_round_trip_and_domain_separation(self):
        value = {'z': [True, None, -2], 'a': 'quote"\\'}
        data = canonical(value)
        self.assertEqual(decode(data), value)
        self.assertNotEqual(cid('One', value), cid('Two', value))

    def test_noncanonical_wire_forms(self):
        for data in (b'{"a":1,"a":1}', b'1.0', b'-0', b' 1', b'1 ',
                     b'NaN', b'Infinity', b'"\\u0061"', b'{"z":0,"a":0}'):
            with self.subTest(data=data), self.assertRaises(Rejected):
                decode(data)

    def test_hostile_values(self):
        cycle = []
        cycle.append(cycle)
        for value in (float('nan'), float('inf'), -float('inf'), '\ud800',
                      2 ** 64, cycle, {0: 'x'}, b'x'):
            with self.subTest(kind=type(value)), self.assertRaises(Rejected):
                canonical(value)

    def test_exact_depth_boundary(self):
        value = 0
        for _ in range(31):
            value = [value]
        canonical(value)
        self.rejects('LIMIT', canonical, [value])

    def test_aliases_are_not_cycles(self):
        common = [1]
        self.assertEqual(decode(canonical([common, common])), [[1], [1]])

    def test_rationals_are_reduced_and_exact(self):
        self.assertEqual(rat(fraction(Fraction(-3, 7))), Fraction(-3, 7))
        for value in ({'num': 2, 'den': 4}, {'num': 0, 'den': 2},
                      {'num': 1, 'den': 0}, {'num': True, 'den': 1}):
            with self.assertRaises(Rejected):
                rat(value)


class LanguageTests(Base):
    def test_five_shapes_are_executable(self):
        self.assertEqual(execute(council(), [], 100)['result'], 'b')
        self.assertEqual(execute(islands(), [], 100)['result'], [0, 1, 3])
        self.assertEqual(execute(recursive_context(), [], 100)['result'], 10)
        self.assertEqual(execute(group_relative_controller(), [],
                                 100)['result'],
                         [fraction(Fraction(-2, 3)), fraction(Fraction(1, 3)),
                          fraction(Fraction(1, 3))])
        self.assertTrue(check(corridor_agent()))

    def test_function_argument_order_is_canonical(self):
        item = program(call('sub', lit(9, 'Int'), lit(3, 'Int')), 'Int')
        item['functions']['sub'] = function(
            {'z': 'Int', 'a': 'Int'},
            'Int', builtin('sub', var('a'),
                           var('z')))
        self.assertEqual(execute(item, [], 100),
                         execute(decode(canonical(item)), [], 100))
        self.assertEqual(execute(item, [], 100)['result'], 6)

    def test_type_check_precedes_any_effect(self):
        calls = []
        services = {'observe': ([], 'Int', lambda: calls.append(1) or 1)}
        bad = program({'op': 'service', 'name': 'observe', 'args': []}, 'Bool')
        self.rejects('TYPE', execute, bad, [], 100, services)
        self.assertEqual(calls, [])

    def test_component_output_contract(self):
        services = {'broken': ([], 'Int', lambda: True)}
        item = program({'op': 'service', 'name': 'broken', 'args': []}, 'Int')
        with self.assertRaises(Rejected):
            execute(item, [], 100, services)

    def test_fuel_and_recursion_are_bounded(self):
        self.rejects('FUEL', execute, recursive_context(), [], 2)
        item = program(call('main'), 'Int')
        self.rejects('LIMIT', execute, item, [], 1000)

    def test_collection_and_record_types(self):
        value_ok([{'x': fraction(Fraction(1, 3))}],
                 {'List': {'Record': {'x': 'Rat'}}})
        for value, tag in ((True, 'Int'), ([1], {'List': 'Bool'}),
                           ({'x': 1, 'y': 2}, {'Record': {'x': 'Int'}})):
            with self.assertRaises(Rejected):
                value_ok(value, tag)

    def test_signature_and_expression_extra_fields_rejected(self):
        item = program(lit(1, 'Int'), 'Int')
        item['functions']['main']['body']['authority'] = 'admitter'
        self.rejects('SCHEMA', check, item)

    def test_decision_probabilities_and_scores(self):
        probabilities = [fraction(Fraction(1, 4)), fraction(Fraction(3, 4))]
        self.assertEqual(expected(probabilities, [fraction(2), fraction(6)]),
                         fraction(5))
        self.assertEqual(brier(probabilities, 1), fraction(Fraction(1, 8)))
        self.assertEqual(regret([fraction(2), fraction(6)], 0), fraction(4))
        self.rejects('PRECONDITION', expected, [fraction(2)], [fraction(1)])
        self.rejects('PRECONDITION', plurality, ['a'], [])

    def test_mutation_checks_types_and_trimming_reassigns_calls(self):
        item = program(lit(1, 'Int'), 'Int')
        self.assertEqual(execute(mutate_literal(item, 'main', [], 7), [], 10)[
            'result'], 7)
        with self.assertRaises(Rejected):
            mutate_literal(item, 'main', [], 'untyped')
        item = program(call('alias', lit(5, 'Int')), 'Int')
        item['functions']['alias'] = function({'x': 'Int'}, 'Int',
                                              call('identity', var('x')))
        item['functions']['identity'] = function({'x': 'Int'}, 'Int', var('x'))
        trimmed = trim_alias(item, 'alias')
        self.assertEqual(execute(item, [], 100)['result'],
                         execute(trimmed['program'], [], 100)['result'])
        self.assertNotIn('alias', trimmed['program']['functions'])


class ProofTests(Base):
    def test_boolean_does_not_impersonate_certificate_cost(self):
        certificate = certify(['top'], ['unit'])
        certificate['visits'] = True
        self.rejects('INTEGRITY', check_certificate, certificate, {})

    def setUp(self):
        self.p = ['atom', 'P']
        self.q = ['atom', 'Q']
        self.identity = ['lam', self.p, ['var', 0]]

    def test_closed_root_and_certificate_recheck(self):
        goal = ['imp', self.p, self.p]
        certificate = certify(goal, self.identity)
        self.assertEqual(check_certificate(certificate, {}),
                         cid('ProofCertificate', certificate))
        certificate['goal'] = self.q
        self.rejects('TYPE', check_certificate, certificate, {})

    def test_cannot_escape_assumptions(self):
        self.rejects('SCHEMA', certify, self.p, ['var', 0])
        self.rejects('TYPE', certify, self.p, self.identity)
        self.rejects('SCHEMA', certify, self.p, ['sorry'])

    def test_and_or_elimination_and_ex_falso(self):
        p, q = self.p, self.q
        examples = [
            (['imp', ['and', p, q], p], ['lam', ['and', p, q],
                                         ['fst', ['var', 0]]]),
            (['imp', ['and', p, q], q], ['lam', ['and', p, q],
                                         ['snd', ['var', 0]]]),
            (['imp', p, ['or', p, q]], ['lam', p, ['inl', ['var', 0], q]]),
            (['imp', q, ['or', p, q]], ['lam', q, ['inr', p, ['var', 0]]]),
            (['imp', ['bot'], p], ['lam', ['bot'],
                                   ['absurd', p, ['var', 0]]]),
            (['imp', ['or', p, p], p], ['lam', ['or', p, p],
                                        ['case', ['var', 0],
                                        ['lam', p, ['var', 0]],
                                        ['lam', p, ['var', 0]]]]),
            (['top'], ['unit']),
        ]
        for goal, term in examples:
            with self.subTest(goal=goal):
                certify(goal, term)

    def test_shared_library_and_application(self):
        imp = ['imp', self.p, self.p]
        library = {'identity': {'goal': imp, 'term': self.identity}}
        goal = ['and', imp, imp]
        certificate = certify(goal, ['pair', ['ref', 'identity'],
                                     ['ref', 'identity']], library)
        self.assertEqual(certificate['visits'], 5)
        certify(imp, ['app', ['lam', imp, ['var', 0]], ['ref', 'identity']],
                library)

    def test_cycles_and_wrong_library_rejected(self):
        library = {'a': {'goal': self.p, 'term': ['ref', 'b']},
                   'b': {'goal': self.p, 'term': ['ref', 'a']}}
        self.rejects('CONFLICT', certify, self.p, ['ref', 'a'], library)
        certificate = certify(['imp', self.p, self.p], self.identity)
        extra = {'i': {'goal': ['imp', self.p, self.p], 'term': self.identity}}
        self.rejects('INTEGRITY', check_certificate, certificate, extra)

    def test_indexed_control_matches_decomposition_budget(self):
        library = {}
        for key in ('A', 'B', 'C', 'D'):
            atom = ['atom', key]
            library[key] = {'goal': ['imp', atom, atom],
                            'term': ['lam', atom, ['var', 0]]}
        goal = ['and', library['C']['goal'], library['D']['goal']]
        forward = search(goal, library, 1, 'forward')
        directed = search(goal, library, 1, 'decompose')
        self.assertEqual(forward['status'], 'CHECKED')
        self.assertEqual(forward['attempts'], directed['attempts'])
        self.assertEqual(forward['certificate_visits'],
                         directed['certificate_visits'])
        self.assertEqual(directed['status'], 'CHECKED')
        check_certificate(directed['certificate'], library)
        self.assertEqual(search(goal, library, 16)['status'], 'CHECKED')

    def test_formula_boundary_and_negation_representation(self):
        formula(['imp', self.p, ['bot']])
        self.rejects('SCHEMA', formula, ['not', self.p])
        value = ['top']
        for _ in range(31):
            value = ['imp', ['top'], value]
        formula(value)
        self.rejects('LIMIT', formula, ['imp', ['top'], value])


class KernelTests(Base):
    def test_fence_cannot_be_reused_for_a_later_dispatch(self):
        ledger = Ledger(2, A)
        ledger.apply('agent', {'op': 'reserve', 'job': 'j', 'upper': 2})
        ledger.apply('executor', {'op': 'fence', 'job': 'j'})
        self.rejects('PHASE', ledger.apply, 'executor',
                     {'op': 'dispatch', 'job': 'j'})

    def test_unknown_has_a_charged_recovery_and_late_output_is_inert(self):
        ledger = Ledger(10, A)
        events = [('agent', {'op': 'reserve', 'job': 'j', 'upper': 5}),
                  ('executor', {'op': 'dispatch', 'job': 'j'}),
                  ('executor', {'op': 'unknown', 'job': 'j'})]
        for principal, event in events:
            ledger.apply(principal, event)
        self.rejects('PHASE', ledger.apply, 'supervisor',
                     {'op': 'seal', 'job': 'j'})
        ledger.apply('executor', {'op': 'fence', 'job': 'j'})
        ledger.apply('supervisor', {'op': 'seal', 'job': 'j'})
        before = deepcopy(ledger.state)
        output = ledger.apply('executor', {'op': 'complete', 'job': 'j',
                                           'actual': 1, 'receipt': A})
        self.assertEqual(output['code'], 'LATE')
        self.assertEqual(before, ledger.state)
        self.assertEqual((before['free'], before['spent']), (5, 5))

    def test_wrong_principal_and_over_budget_rejected(self):
        ledger = Ledger(2, A)
        self.rejects('AUTHORITY', ledger.apply, 'agent',
                     {'op': 'publish', 'candidate': B, 'generation': 0})
        self.rejects('BUDGET', ledger.apply, 'agent',
                     {'op': 'reserve', 'job': 'j', 'upper': 3})

    def test_invariant_is_checked_at_transition_boundary(self):
        ledger = Ledger(2, A)
        bad = deepcopy(ledger.state)
        bad['free'] = 3
        self.rejects('INTEGRITY', step, bad, 'agent', {'op': 'start_run'})

    def test_aba_generation_and_active_run_protection(self):
        ledger = Ledger(2, A)
        ledger.apply('admitter', {'op': 'publish', 'candidate': B,
                                  'generation': 0})
        ledger.apply('supervisor', {'op': 'rollback', 'candidate': A,
                                    'generation': 1})
        self.rejects('STALE', ledger.apply, 'admitter',
                     {'op': 'publish', 'candidate': B, 'generation': 0})
        ledger.apply('agent', {'op': 'start_run'})
        self.rejects('PHASE', ledger.apply, 'admitter',
                     {'op': 'publish', 'candidate': B, 'generation': 2})

    def test_snapshot_forgery_and_rewritten_history_rejected(self):
        ledger = Ledger(2, A)
        ledger.apply('agent', {'op': 'start_run'})
        correct = deepcopy(ledger.state)
        forged = deepcopy(correct)
        forged['active'] = B
        self.rejects('INTEGRITY', ledger.restore, forged, ledger.log)
        self.rejects('INTEGRITY', ledger.restore, ledger.genesis, [])
        self.assertTrue(ledger.restore(correct, deepcopy(ledger.log)))

    def test_completion_is_idempotent_and_conflicts_rejected(self):
        ledger = Ledger(2, A)
        ledger.apply('agent', {'op': 'reserve', 'job': 'j', 'upper': 2})
        ledger.apply('executor', {'op': 'dispatch', 'job': 'j'})
        event = {'op': 'complete', 'job': 'j', 'actual': 1, 'receipt': A}
        ledger.apply('executor', event)
        self.assertEqual(ledger.apply('executor', event)['code'], 'REPEAT')
        self.rejects('CONFLICT', ledger.apply, 'executor',
                     {**event, 'receipt': B})


class GroundingTests(Base):
    def test_controller_budget_boundary(self):
        from src.api import handle
        session = self.session()
        request = canonical({'op': 'not_a_command'})
        for _ in range(1024):
            result = decode(handle(session, request))
            self.assertEqual(result['code'], 'SCHEMA')
        self.assertEqual(session.requests_used, 1024)
        self.assertEqual(decode(handle(session, request))['code'], 'BUDGET')

    def test_receipt_order_does_not_change_release_decision(self):
        decisions = []
        for order in itertools.permutations(range(2)):
            session = self.session([1])
            plan = session.prepare(corridor_agent(), [1])
            receipts = session.evaluate(plan)
            decisions.append(session.admit(plan, [receipts[i] for i in order]))
        self.assertEqual(decisions[0], decisions[1])

    def test_hard_episode_limit_and_failed_gate_consumes_assignments(self):
        from src.examples import action
        from src.environment import AGENT_PARAMS, INTENT_TYPE
        loop = program(action(lit('noop', 'Text')), {'Option': INTENT_TYPE},
                       AGENT_PARAMS)
        session = self.session([12])
        plan = session.prepare(loop, [12])
        receipts = session.evaluate(plan)
        trace = receipts[1]['receipt']['trace']
        self.assertEqual(len(trace['steps']), 64)
        self.assertEqual(trace['termination'], 'LIMIT')
        self.assertFalse(session.admit(plan, receipts)['accept'])
        self.rejects('DUPLICATE', session.admit, plan, receipts)

    def test_public_initialization_is_structured_and_total(self):
        from src.api import initialize
        for value in (None, [], {'total': -1}):
            owner, result = initialize(canonical(value), KEY)
            self.assertIsNone(owner)
            self.assertNotEqual(decode(result)['code'], 'OK')
        owner, result = initialize(canonical({
            'baseline': corridor_agent('paint'), 'total': 24,
            'manifest': MANIFEST, 'levels': [1],
        }), KEY)
        self.assertIsNotNone(owner)
        self.assertEqual(decode(result)['code'], 'OK')

    def test_complete_snapshot_preserves_consumption_and_trust_anchor(self):
        session = self.session()
        plan = session.prepare(corridor_agent(), [1, 2])
        envelopes = session.evaluate(plan)
        session.admit_training(envelopes[1])
        snapshot = session.snapshot()
        anchor = cid('SessionSnapshot', snapshot)
        restored = Session.restore_integrity(snapshot, KEY, anchor)
        self.assertEqual(canonical(restored.snapshot()), canonical(snapshot))
        self.rejects('DUPLICATE', restored.admit_training, envelopes[1])
        forged = deepcopy(snapshot)
        forged['training_used'] = []
        self.rejects('INTEGRITY', Session.restore_integrity,
                     forged, KEY, anchor)

    def test_resume_after_receipt_before_settlement(self):
        session = self.session([1])
        plan = session.prepare(corridor_agent(), [1])
        assignment = session.plans[plan]['assignments'][0][0]
        session.ledger.apply('agent', {'op': 'start_run'})
        session.active_plan = plan
        session.ledger.apply(
            'agent', {
                'op': 'reserve', 'job': 'j0', 'upper': 1})
        session.ledger.apply('executor', {'op': 'dispatch', 'job': 'j0'})
        session.runner.run(assignment, corridor_agent('paint'))
        snapshot = session.snapshot()
        restored = Session.restore_integrity(
            snapshot, KEY, cid(
                'SessionSnapshot', snapshot))
        restored.evaluate(plan)
        self.assertEqual(restored.ledger.state['spent'], 2)
        self.assertEqual(restored.ledger.state['open_runs'], 0)

    def test_unknown_execution_is_sealed_and_never_silently_retried(self):
        session = self.session([1])
        plan = session.prepare(corridor_agent(), [1])
        assignment = session.plans[plan]['assignments'][0][0]
        session.ledger.apply('agent', {'op': 'start_run'})
        session.active_plan = plan
        session.ledger.apply(
            'agent', {
                'op': 'reserve', 'job': 'j0', 'upper': 1})
        session.ledger.apply('executor', {'op': 'dispatch', 'job': 'j0'})
        self.rejects('PHASE', session.evaluate, plan)
        self.assertTrue(session.abandon(plan))
        self.assertEqual(session.ledger.state['spent'], 1)
        self.rejects('PHASE', session.runner.run, assignment,
                     corridor_agent('paint'))
        next_plan = session.prepare(corridor_agent(), [1])
        envelopes = session.evaluate(next_plan)
        self.assertTrue(session.admit(next_plan, envelopes)['accept'])

    def test_wire_boundary_rejects_malformed_requests_without_authority(self):
        from src.api import handle
        session = self.session()
        values = [
            None, [], 0, True, {
                'op': 'publish', 'principal': 'admitter'}, {
                'op': []}, {
                'op': 'evaluate', 'plan': []}, {
                    'op': 'propose', 'program': {
                        'entry': [], 'functions': {}}}]
        for value in values:
            result = decode(handle(session, canonical(value)))
            self.assertNotEqual(result['code'], 'OK')
        proposed = decode(
            handle(
                session,
                canonical({'op': 'propose', 'program': corridor_agent()})))
        plan = proposed['value']
        evaluated = decode(
            handle(session, canonical({'op': 'evaluate', 'plan': plan})))
        result = decode(
            handle(
                session,
                canonical(
                    {'op': 'admit', 'plan': plan,
                     'assignments': evaluated['value']})))
        self.assertTrue(result['value']['accept'])

    def test_full_chain_and_condensation_formalization_cycle(self):
        session = self.session()
        plan = session.prepare(corridor_agent(), [1, 2])
        envelopes = session.evaluate(plan)
        decision = session.admit(plan, envelopes)
        self.assertTrue(decision['accept'])
        good = [item for item in envelopes
                if item['receipt']['trace']['candidate'] ==
                cid('Program', corridor_agent())]
        for envelope in good:
            session.admit_training(envelope)
        session.ledger.apply('agent', {'op': 'start_run'})
        generation = session.ledger.state['generation']
        local = session.condense(list(session.dataset))
        self.assertEqual(session.ledger.state['generation'], generation)
        session.ledger.apply('agent', {'op': 'close_run'})
        compiled = formalize(local)
        runner = Runner(KEY, MANIFEST)
        for level in (1, 2):
            assignment = runner.assign(cid('Program', compiled), 0, level, 0)
            envelope = runner.run(assignment, compiled)
            self.assertTrue(runner.verify(envelope)['ground_success'])

    def test_visible_reward_does_not_admit_exploit_to_training(self):
        session = self.session()
        plan = session.prepare(corridor_agent(), [1, 2])
        envelopes = session.evaluate(plan)
        exploit = envelopes[0]
        self.assertTrue(exploit['receipt']['trace']['reward'])
        self.assertFalse(session.runner.verify(exploit)['ground_success'])
        self.rejects('INELIGIBLE', session.admit_training, exploit)
        self.rejects('INELIGIBLE', session.condense,
                     [exploit['receipt']['trace']['assignment']])

    def test_forged_observation_goal_and_renamed_sample_rejected(self):
        session = self.session()
        plan = session.prepare(corridor_agent(), [1, 2])
        envelopes = session.evaluate(plan)
        for field, value in (('assignment', A), ('reward', False),
                             ('candidate', A), ('generation', 99)):
            forged = deepcopy(envelopes[1])
            forged['receipt']['trace'][field] = value
            self.rejects('AUTHORITY', session.runner.verify, forged)
        duplicate = [envelopes[1]] * len(envelopes)
        self.rejects('DUPLICATE', session.admit, plan, duplicate)

    def test_candidate_cannot_select_easier_scope_or_impersonate_code(self):
        session = self.session()
        self.rejects('PRECONDITION', session.prepare, corridor_agent(), [1])
        assignment = session.runner.assign(cid('Program', corridor_agent()),
                                           0, 1, 0)
        self.rejects('INTEGRITY', session.runner.run, assignment,
                     corridor_agent('paint'))

    def test_predictions_are_committed_but_not_causal_certificates(self):
        session = self.session()
        plan = session.prepare(corridor_agent(), [1, 2])
        envelopes = session.evaluate(plan)
        good = envelopes[1]
        result = session.runner.verify(good)
        self.assertLess(result['prediction_hits'], result['steps'])
        self.assertEqual(session.admit_training(good)['kind'],
                         'TrainingAdmission')
        forged = deepcopy(good['receipt']['trace'])
        forged['steps'][0]['intent']['prediction'] = {}
        self.rejects('SCHEMA', audit_trace, forged)

    def test_trace_teleport_and_hash_chain_reordering(self):
        session = self.session()
        plan = session.prepare(corridor_agent(), [1, 2])
        trace = session.evaluate(plan)[1]['receipt']['trace']
        teleported = deepcopy(trace)
        teleported['steps'][0]['after']['position'] = 2
        self.rejects('POSTCONDITION', audit_trace, teleported)
        reordered = deepcopy(trace)
        reordered['steps'][0], reordered['steps'][1] = (
            reordered['steps'][1], reordered['steps'][0])
        self.rejects('INTEGRITY', audit_trace, reordered)

    def test_receipt_requires_settled_execution_and_training_dedup(self):
        session = self.session()
        assignment = session.runner.assign(cid('Program', corridor_agent()),
                                           0, 1, 0)
        envelope = session.runner.run(assignment, corridor_agent())
        self.rejects('PHASE', session.admit_training, envelope)
        plan = session.prepare(corridor_agent(), [1, 2])
        good = session.evaluate(plan)[1]
        session.admit_training(good)
        self.rejects('DUPLICATE', session.admit_training, good)

    def test_release_evidence_stale_after_rollback(self):
        session = self.session()
        baseline = session.ledger.state['active']
        plan = session.prepare(corridor_agent(), [1, 2])
        envelopes = session.evaluate(plan)
        session.admit(plan, envelopes)
        session.ledger.apply('supervisor', {'op': 'rollback',
                                            'candidate': baseline,
                                            'generation': 1})
        self.rejects('STALE', session.admit, plan, envelopes)

    def test_independent_relation_matches_all_reachable_small_states(self):
        for level in (1, 2, 3):
            queue = [initial(level)]
            seen = {canonical(queue[0])}
            for state in queue:
                for action in ACTIONS:
                    after = transition(state, action, level)
                    self.assertTrue(verify_edge(state, action, after, level))
                    key = canonical(after)
                    if key not in seen:
                        seen.add(key)
                        queue.append(after)


class StatisticsTests(Base):
    def test_gain_and_loss_use_different_sample_sizes(self):
        rows = [[True, True]] * 99 + [[False, True]]
        gain, loss = exact_pair_tests(rows, Fraction(1, 10))
        self.assertEqual(gain, Fraction(1, 2))
        self.assertEqual(loss, Fraction(9, 10) ** 100)

    def test_multiple_strata_gate_really_executes(self):
        rows = [[False, True]] * 128
        passed = assess_pairs({'a': rows, 'b': rows}, 1,
                              Fraction(1, 20), Fraction(1, 10))
        self.assertTrue(passed['accept'])
        self.assertEqual(passed['threshold'], '1/160')
        failed = assess_pairs({'a': rows, 'b': [[True, False]] * 128}, 1,
                              Fraction(1, 20), Fraction(1, 10))
        self.assertFalse(failed['accept'])

    def test_nonempty_rejection_regions_have_exact_error_control(self):
        # Enumerate full multinomial outcomes with n=20, not just discordances.
        from math import factorial
        n = 20
        alpha = Fraction(1, 8)
        null_gain = Fraction(0)
        nonempty = 0
        for wins in range(n + 1):
            for losses in range(n - wins + 1):
                ties = n - wins - losses
                probability = Fraction(factorial(n), factorial(wins)
                                       * factorial(losses) * factorial(ties))
                probability *= Fraction(1, 4) ** (wins + losses)
                probability *= Fraction(1, 2) ** ties
                rows = [[False, True]] * wins + [[True, False]] * losses + (
                    [[True, True]] * ties)
                gain, _ = exact_pair_tests(rows, Fraction(1, 4))
                if gain <= alpha:
                    nonempty += 1
                    null_gain += probability
        self.assertGreater(nonempty, 0)
        self.assertLessEqual(null_gain, alpha)
        loss_size = sum(Fraction(__import__('math').comb(n, c))
                        * Fraction(1, 4) ** c * Fraction(3, 4) ** (n - c)
                        for c in range(n + 1)
                        if exact_pair_tests([[True, False]] * c
                                            + [[True, True]] * (n - c),
                                            Fraction(1, 4))[1] <= alpha)
        self.assertGreater(loss_size, 0)
        self.assertLessEqual(loss_size, alpha)


class KnowledgeTests(Base):
    def test_same_scope_fact_requires_matching_grounded_assertion(self):
        from src.knowledge import ground_fact
        session = self.session([1])
        plan = session.prepare(corridor_agent(), [1])
        fact, registry = ground_fact(session.evaluate(plan)[1], session.runner)
        result = compose(
            [fact],
            fact,
            ENVIRONMENT,
            2000,
            'relevance',
            registry)
        self.assertEqual(result['entries'][0]['status'], 'FACT')
        forged = {**fact, 'polarity': False}
        result = compose(
            [forged],
            fact,
            ENVIRONMENT,
            2000,
            'relevance',
            registry)
        self.assertEqual(result['entries'][0]['status'], 'ASSUMPTION')

    def test_channels_scope_demotion_and_budget(self):
        item = {'text': 'door needs key', 'tokens': ['door', 'key'],
                'features': ['prerequisite'], 'predicate': 'opens',
                'arguments': ['door'], 'polarity': True, 'status': 'FACT',
                'scope': A, 'evidence': [B]}
        negative = {**item, 'polarity': False}
        analogy = {**item, 'tokens': ['compiler', 'header'],
                   'predicate': 'builds', 'status': 'ASSUMPTION'}
        result = compose([item, negative, analogy], item, B, 2000,
                         'contradiction')
        self.assertEqual(result['returned'], 1)
        self.assertEqual(result['entries'][0]['status'], 'ASSUMPTION')
        self.assertEqual(compose([analogy], item, A, 2000, 'analogy')[
            'returned'], 1)
        self.assertEqual(compose([analogy], item, A, 2000, 'relevance')[
            'returned'], 0)
        self.assertEqual(
            compose(
                [item],
                item,
                A,
                2,
                'relevance')['entries'],
            [])
