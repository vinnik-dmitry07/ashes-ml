'''Regression witnesses for the AST, snapshot and admission boundaries.'''

from copy import deepcopy
import unittest

from ahsl.admission import Session
from ahsl.api import handle
from ahsl.codec import Rejected, canonical, cid, decode
from ahsl.examples import (
    action, builtin, call, choose, corridor_agent, function, lit,
    observation, program, var,
)
from ahsl.knowledge import trim_alias
from ahsl.language import check, execute, program_cost_bytes
from ahsl.obligations import DEFAULT_GUARANTEES, IMPROVEMENT_PROFILE
from ahsl.schema import validate_schema


KEY = b'release-14-regression-root-key-only'
MANIFEST = cid('Manifest', {})


def tree_depth(value):
    children = (value.values() if type(value) is dict else value
                if type(value) is list else ())
    return 1 + max((tree_depth(child) for child in children), default=0)


def padded_solver(depth):
    candidate = corridor_agent()
    main = candidate['functions']['main']
    while tree_depth(candidate) < depth:
        main['body'] = {'op': 'let', 'name': 'unused',
                        'value': lit(0, 'Int'), 'body': main['body']}
    assert tree_depth(candidate) == depth
    return candidate


def delayed_solver():
    candidate = corridor_agent()
    main = candidate['functions']['main']
    main['body'] = choose(builtin('eq', var('index'), lit(0, 'Int')),
                          action(lit('noop', 'Text')), main['body'])
    return candidate


def padded_bytes(candidate, length, marker='a', normalized=False):
    candidate = deepcopy(candidate)
    candidate['functions']['padding'] = function({}, 'Text', lit('', 'Text'))
    padding = candidate['functions']['padding']['body']
    measure = program_cost_bytes if normalized else (
        lambda value: len(canonical(value)))
    padding['value'] = marker * (length - measure(candidate))
    assert measure(candidate) == length
    return candidate


class Release14Tests(unittest.TestCase):
    def owner(self, baseline=None, levels=None, guarantees=None):
        baseline = corridor_agent('paint') if baseline is None else baseline
        return Session(baseline,
                       96, KEY, MANIFEST, [1, 2] if levels is None else levels,
                       guarantees)

    def round_trip(self, owner):
        snapshot = owner.snapshot()
        validate_schema(snapshot, 'SessionSnapshot')
        encoded = canonical(snapshot)
        restored = Session.restore_integrity(decode(encoded), KEY,
                                             cid('SessionSnapshot', snapshot))
        self.assertEqual(canonical(restored.snapshot()), encoded)
        self.assertEqual(restored.programs, owner.programs)
        return restored

    def admit(self, owner, candidate, mode='improve', guarantees=None):
        plan = owner.prepare(candidate, owner.levels, guarantees, mode)
        result = owner.admit(plan, owner.evaluate(plan))
        validate_schema(result, 'ReleaseDecision')
        return result

    def test_trim_preserves_ast_shaped_literals_in_records_and_lists(self):
        shape = {'Record': {'op': 'Text', 'name': 'Text',
                            'args': {'List': 'Int'}}}
        data = {'op': 'call', 'name': 'alias', 'args': []}
        for value, tag in ((data, shape), ([data], {'List': shape})):
            with self.subTest(tag=tag):
                candidate = program(lit(value, tag), tag)
                candidate['functions']['alias'] = function(
                    {}, 'Int', call('target'))
                candidate['functions']['target'] = function(
                    {}, 'Int', lit(7, 'Int'))
                before = canonical(candidate)
                trimmed = trim_alias(candidate, 'alias')['program']
                self.assertEqual(execute(candidate, [], 100),
                                 execute(trimmed, [], 100))
                self.assertEqual(execute(trimmed, [], 100)['result'], value)
                self.assertEqual(canonical(candidate), before)

    def test_trim_rebinds_nested_calls_but_keeps_builtin_names(self):
        cases = [
            (builtin('add', call('add'), lit(2, 'Int')), 'Int', 2),
            ({'op': 'let', 'name': 'x', 'value': call('add'),
              'body': call('add')}, 'Int', 0),
            (choose(builtin('eq', call('add'), lit(0, 'Int')),
                    call('add'), call('add')), 'Int', 0),
            ({'op': 'some', 'value': call('add')}, {'Option': 'Int'}, 0),
            ({'op': 'get', 'record': {'op': 'record', 'fields': {
                'x': call('add')}}, 'field': 'x'}, 'Int', 0),
            ({'op': 'index', 'list': lit([9], {'List': 'Int'}),
              'index': call('add')}, 'Int', 9),
            (call('identity', call('add')), 'Int', 0),
        ]
        for body, tag, expected in cases:
            with self.subTest(op=body['op']):
                candidate = program(body, tag)
                candidate['functions'].update({
                    'add': function({}, 'Int', call('target')),
                    'target': function({}, 'Int', lit(0, 'Int')),
                    'identity': function({'x': 'Int'}, 'Int', var('x')),
                })
                trimmed = trim_alias(candidate, 'add')['program']
                check(trimmed)
                self.assertNotIn('add', trimmed['functions'])
                self.assertEqual(execute(trimmed, [], 200)['result'], expected)

    def test_wire_depth_boundary_stays_encodable_through_release(self):
        owner = self.owner()
        candidate = padded_solver(31)
        request = canonical({'op': 'propose', 'program': candidate})
        self.assertEqual(tree_depth(decode(request)), 32)
        result = decode(handle(owner, request))
        self.assertEqual(result['code'], 'OK')
        owner = self.round_trip(owner)
        receipts = owner.evaluate(result['value'])
        owner = self.round_trip(owner)
        self.assertTrue(owner.admit(result['value'], receipts)['accept'])
        owner.admit_training(receipts[1])
        self.round_trip(owner)

    def test_direct_depth_boundary_survives_bootstrap_and_prepare(self):
        candidate = padded_solver(32)
        check(candidate)
        self.round_trip(self.owner(candidate))
        owner = self.owner()
        owner.prepare(candidate, owner.levels)
        self.round_trip(owner)
        before = deepcopy(owner.plans)
        # The wire wrapper still has its own unchanged C12 depth bound.
        import json
        request = json.dumps({'op': 'propose', 'program': candidate},
                             sort_keys=True, separators=(',', ':')).encode()
        self.assertEqual(decode(handle(owner, request))['code'], 'LIMIT')
        self.assertEqual(owner.plans, before)
        self.round_trip(owner)

    def test_five_maximum_size_programs_remain_encodable(self):
        baseline = padded_bytes(padded_solver(32), 65536)
        owner = self.owner(baseline)
        for marker in ('b', 'c', 'd', 'e'):
            candidate = padded_bytes(padded_solver(31), 65536, marker)
            request = canonical({'op': 'propose', 'program': candidate})
            self.assertEqual(decode(handle(owner, request))['code'], 'OK')
            owner = self.round_trip(owner)
        self.assertEqual(len(owner.programs), 5)

    def test_snapshot_with_all_tickets_steps_and_training_records(self):
        baseline = corridor_agent()
        main = baseline['functions']['main']
        level = observation('level')
        delay = builtin('sub', lit(63, 'Int'),
                        builtin('add', level, builtin('add', level, level)))
        main['body'] = choose(builtin('lt', var('index'), delay),
                              action(lit('noop', 'Text')), main['body'])
        owner = self.owner(baseline, list(range(1, 13)))
        for marker in ('b', 'c', 'd', 'e'):
            candidate = padded_bytes(baseline, 2500, marker)
            plan = owner.prepare(candidate, owner.levels, mode='retain')
            receipts = owner.evaluate(plan)
            self.assertTrue(owner.admit(plan, receipts)['accept'])
            for receipt in receipts:
                self.assertEqual(len(receipt['receipt']['trace']['steps']), 64)
                owner.admit_training(receipt)
        self.assertEqual(owner.ledger.state['spent'], 96)
        self.assertEqual(len(owner.dataset), 96)
        self.round_trip(owner)

    def test_snapshot_requires_canonical_program_text_and_matching_id(self):
        original = self.owner().snapshot()
        identifier = next(iter(original['programs']))
        for encoded, code in (
                (' ' + original['programs'][identifier], 'ENCODING'),
                (canonical(corridor_agent()).decode('ascii'), 'INTEGRITY')):
            snapshot = deepcopy(original)
            snapshot['programs'][identifier] = encoded
            with self.subTest(code=code), self.assertRaises(Rejected) as error:
                Session.restore_integrity(snapshot, KEY,
                                          cid('SessionSnapshot', snapshot))
            self.assertEqual(str(error.exception), code)
        stale = deepcopy(original)
        stale['version'] = '1.3'
        with self.assertRaises(Rejected) as error:
            Session.restore_integrity(
                stale, KEY, cid('SessionSnapshot', stale))
        self.assertEqual(str(error.exception), 'STALE')

    def test_improve_continues_after_full_success(self):
        owner = self.owner(levels=list(range(1, 13)))
        first = self.admit(owner, delayed_solver())
        self.assertTrue(first['accept'])
        self.assertTrue(first['improvement']['success_gain'])
        second = self.admit(owner, corridor_agent())
        self.assertTrue(second['accept'])
        self.assertFalse(second['improvement']['success_gain'])
        self.assertTrue(second['improvement']['cost_strict'])
        self.assertEqual(second['pairs'], [[True, True]] * 12)
        for parent, child in second['improvement']['cost_pairs']:
            self.assertLess(child['actions'], parent['actions'])
            self.assertLess(child['vm_fuel'], parent['vm_fuel'])
            self.assertLess(child['program_bytes'], parent['program_bytes'])
        self.assertEqual(owner.ledger.state['generation'], 2)
        self.assertEqual(owner.ledger.state['spent'], 48)
        self.round_trip(owner)

    def test_fuel_only_improvement_with_equal_size_and_actions(self):
        fast = corridor_agent()
        slow = deepcopy(fast)
        main = slow['functions']['main']
        main['body'] = {'op': 'let', 'name': 'unused',
                        'value': lit(0, 'Int'), 'body': main['body']}
        owner = self.owner(padded_bytes(slow, 4000, normalized=True))
        verdict = self.admit(owner, padded_bytes(fast, 4000, normalized=True))
        self.assertTrue(verdict['accept'])
        for parent, child in verdict['improvement']['cost_pairs']:
            self.assertEqual(parent['program_bytes'], child['program_bytes'])
            self.assertEqual(parent['actions'], child['actions'])
            self.assertGreater(parent['vm_fuel'], child['vm_fuel'])

    def test_size_only_improvement(self):
        owner = self.owner(padded_bytes(corridor_agent(), 4000))
        verdict = self.admit(owner, corridor_agent())
        self.assertTrue(verdict['accept'])
        for parent, child in verdict['improvement']['cost_pairs']:
            self.assertEqual(parent['actions'], child['actions'])
            self.assertEqual(parent['vm_fuel'], child['vm_fuel'])
            self.assertLess(child['program_bytes'], parent['program_bytes'])

    def test_equal_cost_different_source_is_not_improvement(self):
        owner = self.owner(padded_bytes(corridor_agent(), 4000, 'a'))
        verdict = self.admit(owner, padded_bytes(corridor_agent(), 4000, 'b'))
        self.assertFalse(verdict['accept'])
        self.assertTrue(verdict['improvement']['cost_nonworse'])
        self.assertFalse(verdict['improvement']['cost_strict'])

    def test_lower_action_count_cannot_hide_higher_fuel(self):
        owner = self.owner(padded_bytes(delayed_solver(), 5000))
        slow = padded_bytes(padded_solver(30), 5000)
        verdict = self.admit(owner, slow)
        self.assertFalse(verdict['accept'])
        for parent, child in verdict['improvement']['cost_pairs']:
            self.assertLess(child['actions'], parent['actions'])
            self.assertGreater(child['vm_fuel'], parent['vm_fuel'])

    def test_average_gain_cannot_hide_one_level_regression(self):
        baseline = corridor_agent()
        candidate = corridor_agent()
        for item, comparison in ((baseline, 'eq'), (candidate, 'lt')):
            main = item['functions']['main']
            condition = builtin(comparison, observation('level'),
                                lit(2, 'Int'))
            delay = choose(condition, lit(3, 'Int'), lit(0, 'Int'))
            main['body'] = choose(builtin('lt', var('index'), delay),
                                  action(lit('noop', 'Text')), main['body'])
        owner = self.owner(padded_bytes(baseline, 5000))
        verdict = self.admit(owner, padded_bytes(candidate, 5000))
        self.assertEqual(verdict['pairs'], [[True, True], [True, True]])
        costs = verdict['improvement']['cost_pairs']
        self.assertGreater(costs[0][1]['actions'], costs[0][0]['actions'])
        self.assertLess(costs[1][1]['actions'], costs[1][0]['actions'])
        self.assertFalse(verdict['accept'])

    def test_cheaper_failure_and_contract_violation_cannot_pass(self):
        owner = self.owner(delayed_solver())
        self.assertFalse(self.admit(owner, corridor_agent('noop'))['accept'])
        strict = {**DEFAULT_GUARANTEES, 'max_actions': 3}
        # A designated baseline need not already satisfy its contract.
        owner = self.owner(delayed_solver(), levels=[1], guarantees=strict)
        verdict = self.admit(owner, corridor_agent())
        self.assertTrue(verdict['improvement']['cost_strict'])
        self.assertFalse(verdict['accept'])

    def test_cost_is_evaluator_measured_signed_and_not_wire_input(self):
        owner = self.owner(delayed_solver(), levels=[1])
        candidate = corridor_agent()
        request = {'op': 'propose', 'program': candidate,
                   'cost': {'actions': 0, 'vm_fuel': 0, 'program_bytes': 0}}
        self.assertEqual(decode(handle(owner, canonical(request)))['code'],
                         'SCHEMA')
        plan = owner.prepare(candidate, [1])
        receipt = owner.evaluate(plan)[1]
        witness = owner.evaluator.assess(receipt, candidate, owner.mission,
                                         DEFAULT_GUARANTEES)
        measured = witness['assessment']['cost']
        self.assertEqual(measured['actions'], 4)
        self.assertEqual(measured['program_bytes'],
                         program_cost_bytes(candidate))
        self.assertGreater(measured['vm_fuel'], 0)
        witness['assessment']['cost']['vm_fuel'] = 0
        with self.assertRaises(Rejected) as error:
            owner.evaluator.verify(witness)
        self.assertEqual(str(error.exception), 'AUTHORITY')
        self.assertEqual(owner.mission['improvement_profile'],
                         IMPROVEMENT_PROFILE)
        owner.mission['improvement_profile'] = 'AGENT_CHOICE'
        with self.assertRaises(Rejected) as error:
            owner.admit(plan, owner.evaluate(plan))
        self.assertEqual(str(error.exception), 'INTEGRITY')
        self.assertFalse(owner.used)

    def test_retain_keeps_absolute_success_and_previous_cost_semantics(self):
        owner = self.owner(corridor_agent())
        verdict = self.admit(owner, delayed_solver(), 'retain')
        self.assertTrue(verdict['accept'])
        self.assertFalse(verdict['improvement']['cost_nonworse'])
        self.assertFalse(self.admit(owner, corridor_agent('noop'), 'retain')
                         ['accept'])


if __name__ == '__main__':
    unittest.main()
