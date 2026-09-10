'''Regression checks at the HTTP, accounting, and ground-trace boundaries.'''

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from ahsl.codec import Rejected, canonical
from ahsl.environment import audit_trace
from llmbench.adapter import Broker, run_episode
from llmbench.experiment import MemoryJournal, make_plan
from llmbench.protocol import Budget, Route, json_object
from llmbench.providers import FixtureProvider


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'configs/fixture.json').read_text())


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.route = Route(**CONFIG['route'])
        self.settings = make_plan(
            CONFIG, 'a' * 64, FixtureProvider.mode)['settings']
        self.slot = {'case': 0, 'level': 3, 'condition': 'fresh',
                     'model_seed': 123}

    def run_episode(self, condition='fresh', failure=None, settings=None):
        slot = dict(self.slot, condition=condition)
        provider = FixtureProvider(self.route, failure)
        memory = MemoryJournal()
        result = run_episode(slot, settings or self.settings, self.route,
                             provider, memory, 'a' * 64)
        return result, memory, provider

    def test_all_roles_share_budget(self):
        for condition, calls in (('fresh', 10), ('history', 10),
                                 ('plan', 11), ('selector', 12)):
            with self.subTest(condition=condition):
                result, _, _ = self.run_episode(condition)
                self.assertTrue(result['success'])
                self.assertEqual(result['calls'], calls)
                self.assertEqual(result['accounted_cost_microusd'],
                                 calls * self.route.charge(100, 20))

    def test_selector_overhead_can_turn_success_into_failure(self):
        settings = dict(self.settings, max_calls=10)
        fixed, _, _ = self.run_episode(settings=settings)
        selector, _, _ = self.run_episode('selector', settings=settings)
        self.assertTrue(fixed['success'])
        self.assertFalse(selector['success'])
        self.assertEqual(selector['calls'], 10)
        self.assertEqual(selector['envelope']['receipt']['trace']['error'],
                         'BUDGET')

    def test_monetary_cap_blocks_before_an_extra_http_call(self):
        settings = dict(self.settings,
                        run_budget_microusd=self.route.reservation)
        result, _, provider = self.run_episode(settings=settings)
        self.assertFalse(result['success'])
        self.assertEqual(provider.calls, 1)
        self.assertLessEqual(result['accounted_cost_microusd'],
                             settings['run_budget_microusd'])

    def test_timeout_and_missing_usage_burn_reservation(self):
        for failure in ('timeout', 'missing_usage'):
            with self.subTest(failure=failure):
                result, _, provider = self.run_episode(failure=failure)
                self.assertFalse(result['success'])
                self.assertEqual(provider.calls, 1)
                self.assertEqual(result['accounted_cost_microusd'],
                                 self.route.reservation)
                self.assertEqual(result['unknown_cost_calls'], 1)

    def test_bad_json_is_paid_without_retry(self):
        result, _, provider = self.run_episode(failure='bad_json')
        self.assertFalse(result['success'])
        self.assertEqual(provider.calls, 1)
        self.assertEqual(result['accounted_cost_microusd'],
                         self.route.charge(100, 20))
        self.assertEqual(result['unknown_cost_calls'], 0)

    def test_overrun_and_model_drift_fence(self):
        for failure in ('overrun', 'model_drift'):
            with self.subTest(failure=failure):
                result, _, provider = self.run_episode(failure=failure)
                self.assertTrue(result['provider_contract_violated'])
                self.assertFalse(result['success'])
                self.assertEqual(provider.calls, 1)

    def test_visible_reward_does_not_replace_ground_goal(self):
        result, _, _ = self.run_episode(failure='paint')
        trace = result['envelope']['receipt']['trace']
        self.assertTrue(trace['reward'])
        self.assertFalse(result['success'])
        self.assertFalse(audit_trace(trace)['ground_success'])
        forged = deepcopy(trace)
        forged['final']['position'] = 4
        with self.assertRaises(Rejected):
            audit_trace(forged)

    def test_selector_has_no_future_outcomes_or_test_labels(self):
        result, memory, _ = self.run_episode('selector')
        starts = [row['value'] for row in memory.records
                  if row['kind'] == 'call_start']
        self.assertEqual(starts[0]['role'], 'selector')
        context = json_object(starts[0]['request']['messages'][-1]['content'])
        self.assertEqual(set(context), {
            'role', 'observation', 'history', 'plan',
        })
        self.assertEqual(context['history'], [])
        self.assertEqual(context['plan'], '')
        self.assertEqual(context['observation']['position'], 0)
        self.assertEqual(result['call_roles'][:2], ['selector', 'planner'])

    def test_history_is_bounded_and_fresh_is_stateless(self):
        for condition in ('fresh', 'history'):
            result, memory, _ = self.run_episode(condition)
            starts = [row['value'] for row in memory.records
                      if row['kind'] == 'call_start']
            histories = [json_object(row['request']['messages'][-1][
                'content'])['history'] for row in starts]
            self.assertTrue(result['success'])
            self.assertTrue(all(len(history) <= 8 for history in histories))
            self.assertEqual(len(histories[-1]),
                             8 if condition == 'history' else 0)

    def test_route_is_frozen_and_content_bound(self):
        with self.assertRaises(FrozenInstanceError):
            self.route.model = 'changed'
        changed = replace(self.route, model='changed')
        self.assertNotEqual(changed.identifier, self.route.identifier)
        for endpoint in ('http://example.com/v1',
                         'https://key@example.com/v1',
                         'https://example.com/v1?api_key=secret'):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(Rejected):
                    replace(self.route, endpoint=endpoint)

    def test_output_cannot_change_route_or_add_tools(self):
        route = self.route

        class InjectedProvider(FixtureProvider):
            def complete(self, request):
                wire = super().complete(request)
                body = json_object(bytes.fromhex(wire['response_hex']))
                body['choices'][0]['message']['content'] = json.dumps({
                    'action': 'right', 'endpoint': 'https://attacker.invalid',
                })
                wire['response_hex'] = json.dumps(body).encode().hex()
                return wire

        budget = Budget(50000, 64)
        broker = Broker(InjectedProvider(route), route, budget,
                        MemoryJournal(), 'a' * 64, 1)
        with self.assertRaises(Rejected):
            broker.ask('actor', {'level': 3, 'position': 0, 'opened': [],
                                 'key': False})
        self.assertEqual(budget.calls, 1)
        self.assertEqual(route.identifier, self.route.identifier)

    def test_duplicate_json_fields_rejected(self):
        with self.assertRaises(Rejected):
            json_object('{"action":"take","action":"paint"}')

    def test_requests_use_single_completion_and_output_cap(self):
        result, memory, _ = self.run_episode()
        request = memory.records[1]['value']['request']
        canonical(request)
        self.assertEqual(request['n'], 1)
        self.assertFalse(request['stream'])
        self.assertEqual(request['max_completion_tokens'],
                         self.route.output_token_cap)
        self.assertTrue(result['success'])


if __name__ == '__main__':
    unittest.main()
