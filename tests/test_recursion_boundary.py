'''The declared L12 limits must not depend on Python recursion depth.'''

from copy import deepcopy
import sys
import unittest

from src.admission import Session
from src.api import handle
from src.codec import Rejected, canonical, cid, decode
from src.examples import (
    builtin, call, choose, corridor_agent, function, lit, program, var,
)
from src.language import check, execute


def loop_function():
    body = choose(
        builtin('eq', var('n'), lit(0, 'Int')), lit(0, 'Int'),
        call('loop', builtin('sub', var('n'), lit(1, 'Int'))),
    )
    for index in range(16):
        body = {
            'op': 'let', 'name': 'unused' + str(index),
            'value': lit(0, 'Int'), 'body': body,
        }
    return function({'n': 'Int'}, 'Int', body)


class RecursionBoundaryTests(unittest.TestCase):
    def setUp(self):
        previous = sys.getrecursionlimit()
        self.addCleanup(sys.setrecursionlimit, previous)
        sys.setrecursionlimit(1000)

    def pure(self, iterations):
        result = program(call('loop', lit(iterations, 'Int')), 'Int')
        result['functions']['loop'] = loop_function()
        check(result)
        return result

    def test_in_domain_program_keeps_exact_result_and_fuel(self):
        self.assertEqual(execute(self.pure(60), [], 50000),
                         {'result': 0, 'fuel_used': 2439})

    def test_declared_depth_and_fuel_limits_remain_effective(self):
        for candidate, fuel, expected in (
            (self.pure(60), 2438, 'FUEL'),
            (self.pure(64), 50000, 'LIMIT'),
        ):
            with self.subTest(expected=expected):
                with self.assertRaises(Rejected) as caught:
                    execute(candidate, [], fuel)
                self.assertEqual(str(caught.exception), expected)

    def test_continuations_preserve_effect_order_and_lazy_branching(self):
        observed = []

        def mark(value):
            observed.append(value)
            return value

        def unreachable():
            raise AssertionError('An unselected branch was evaluated')

        def effect(value):
            return {'op': 'service', 'name': 'mark',
                    'args': [lit(value, 'Int')]}

        selected = choose(
            lit(False, 'Bool'),
            {'op': 'service', 'name': 'unreachable', 'args': []},
            call('difference', effect(2), effect(3)),
        )
        candidate = program(
            {'op': 'record', 'fields': {'z': selected, 'a': effect(1)}},
            {'Record': {'z': 'Int', 'a': 'Int'}},
        )
        candidate['functions']['difference'] = function(
            {'z': 'Int', 'a': 'Int'}, 'Int',
            builtin('sub', var('a'), var('z')),
        )
        services = {
            'mark': (['Int'], 'Int', mark),
            'unreachable': ([], 'Int', unreachable),
        }
        result = execute(candidate, [], 100, services)
        self.assertEqual(result, {'result': {'a': 1, 'z': -1},
                                  'fuel_used': 13})
        self.assertEqual(observed, [1, 2, 3])

    def test_g12_evaluation_settles_and_can_admit_recursive_candidate(self):
        candidate = corridor_agent()
        candidate['functions']['loop'] = loop_function()
        body = deepcopy(candidate['functions']['main']['body'])
        candidate['functions']['main']['body'] = {
            'op': 'let', 'name': 'discard',
            'value': call('loop', lit(60, 'Int')), 'body': body,
        }
        owner = Session(
            corridor_agent('paint'), 8,
            b'local-review-public-fixture-key-only', cid('Manifest', {}), [1],
        )

        def send(request):
            result = decode(handle(owner, canonical(request)))
            self.assertEqual(result['code'], 'OK')
            return result['value']

        plan = send({'op': 'propose', 'program': candidate})
        assignments = send({'op': 'evaluate', 'plan': plan})
        self.assertEqual(owner.ledger.state['open_runs'], 0)
        self.assertEqual(owner.ledger.state['spent'], 2)
        self.assertIsNone(owner.active_plan)
        self.assertTrue(all(job['phase'] == 'DONE'
                            for job in owner.ledger.state['jobs'].values()))
        verdict = send({'op': 'admit', 'plan': plan,
                        'assignments': assignments})
        self.assertTrue(verdict['accept'])
        self.assertEqual(verdict['improvement']['cost_pairs'][0][1]['vm_fuel'],
                         9842)
