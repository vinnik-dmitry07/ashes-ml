'''Boundary tests for closed holdouts and whole-search evaluation.'''

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ahsl.codec import Rejected, canonical
from llmbench.experiment import check_sources
from llmbench.protocol import Journal, digest
from llmbench.search_protocol import (
    METHODS, SEARCH_METHODS, make_search_plan, validate_candidate,
    validate_config, validate_reveal,
)
from llmbench.search_statistics import summarize_search
from llmbench.search_study import (
    Events, evaluate_holdout, replay_search_study, search_all,
)


class SearchTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.config = json.loads(
            (root / 'configs/search.fixture.json').read_text())
        self.config.update(repetitions=2, search_tasks=2, holdout_tasks=2,
                           max_proposals=3, search_budget_units=250)
        self.plan, self.reveal = make_search_plan(
            self.config, check_sources(), hidden_seed=17, nonce='a' * 64)

    def complete(self, plan=None, reveal=None):
        plan = self.plan if plan is None else plan
        reveal = self.reveal if reveal is None else reveal
        events = Events()
        frozen, identifier = search_all(plan, events)
        evaluate_holdout(plan, reveal, frozen, identifier, events)
        return events, frozen

    def replay(self, records, plan=None):
        plan = self.plan if plan is None else plan
        with TemporaryDirectory(prefix='ahsl-search-test-') as tmp:
            output = Path(tmp)
            (output / 'plan.json').write_bytes(canonical(plan))
            journal = Journal(output / 'events.jsonl', {
                'study': digest('SearchPlan', plan),
            })
            for row in records:
                journal.append(row['kind'], row['value'])
            journal.close()
            return replay_search_study(output, journal.head)

    def test_split_is_disjoint_and_committed_with_nonce(self):
        validate_reveal(self.plan, self.reveal)
        for fold, levels in zip(self.plan['folds'],
                                self.reveal['holdout_levels']):
            self.assertFalse(set(levels) & set(fold['training_levels']))
        changed = deepcopy(self.reveal)
        changed['nonce'] = 'b' * 64
        with self.assertRaises(Rejected):
            validate_reveal(self.plan, changed)

    def test_hidden_tests_cannot_influence_proposals_or_selection(self):
        altered = deepcopy(self.reveal)
        for fold, old in zip(self.plan['folds'], altered['holdout_levels']):
            unused = set(range(1, 13)) - \
                set(fold['training_levels']) - set(old)
            old[:] = sorted(unused)[:self.config['holdout_tasks']]
        plan = deepcopy(self.plan)
        plan['holdout_commitment'] = digest('HiddenSplit', altered)
        validate_reveal(plan, altered)
        first, second = Events(), Events()
        selected_a = search_all(self.plan, first)
        selected_b = search_all(plan, second)
        self.assertEqual(selected_a, selected_b)
        # Only the plan identity at study_start can differ.
        self.assertEqual(first.records[1:], second.records[1:])

    def test_every_search_is_frozen_before_first_holdout_result(self):
        events, frozen = self.complete()
        kinds = [row['kind'] for row in events.records]
        barrier = kinds.index('all_selections_frozen')
        self.assertEqual(kinds[:barrier].count('selection_frozen'), 8)
        self.assertEqual(kinds[barrier + 1], 'holdout_opened')
        for row in events.records[:barrier]:
            if row['kind'].startswith('evaluation_'):
                self.assertEqual(row['value']['phase'], 'search')
        self.assertEqual(len(frozen), 8)

    def test_holdout_cannot_open_before_freeze(self):
        with self.assertRaises(Rejected):
            evaluate_holdout(self.plan, self.reveal, [], 'f' * 64, Events())

    def test_edit_after_freeze_invalidates_selection(self):
        events = Events()
        frozen, identifier = search_all(self.plan, events)
        frozen[0]['candidate']['max_calls'] = 4
        with self.assertRaises(Rejected):
            evaluate_holdout(self.plan, self.reveal,
                             frozen, identifier, events)
        self.assertEqual(events.records[-1]['kind'], 'all_selections_frozen')

    def test_invalid_proposals_are_charged_and_cannot_spend_forever(self):
        events = Events()
        frozen, _ = search_all(self.plan, events, lambda _: {'bogus': True})
        for row in frozen:
            if row['method'] in SEARCH_METHODS:
                self.assertEqual(row['search_units'], 6)
                self.assertEqual(row['proposals'], 3)
                self.assertEqual(row['evaluations'], 0)
                self.assertTrue(row['fallback'])

    def test_budget_includes_proposals_and_measured_evaluations(self):
        events, frozen = self.complete()
        for entry in frozen:
            rows = [row for row in events.records if row['value'].get('fold')
                    == entry['fold'] and row['value'].get('method')
                    == entry['method']]
            expected = 2 * sum(row['kind'] == 'proposal_start' for row in rows)
            for row in rows:
                if (row['kind'] == 'evaluation_end'
                        and row['value']['phase'] == 'search'):
                    result = row['value']['result']
                    measured = sum(1 + item['calls'] + item['checks']
                                   for item in result['rows'])
                    self.assertEqual(measured, result['units'])
                    expected += measured
            self.assertEqual(entry['search_units'], expected)
            self.assertLessEqual(expected, self.config['search_budget_units'])

    def test_no_evaluation_fallback_remains_in_denominator(self):
        config = dict(self.config, search_budget_units=2)
        plan, reveal = make_search_plan(config, check_sources(), 17, 'a' * 64)
        events, frozen = self.complete(plan, reveal)
        self.assertEqual(sum(row['fallback'] for row in frozen), 4)
        report = summarize_search(plan, events.records)
        self.assertEqual(report['completed_pipeline_runs'], 8)
        self.assertEqual(report['requested_pipeline_runs'], 8)
        self.assertEqual(report['methods']['hill_climb']
                         ['mean_search_units'], 2)

    def test_interruption_preserves_reservation_and_disables_inference(self):
        events = Events()
        with patch('llmbench.search_study.measure',
                   side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                search_all(self.plan, events)
        report = summarize_search(self.plan, events.records)
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertEqual(report['requested_pipeline_runs'], 8)
        self.assertEqual(report['completed_pipeline_runs'], 0)
        self.assertEqual(report['ledger']['pending_evaluations'], 1)
        self.assertGreater(report['ledger']['pending_reserved_units'], 0)
        self.assertFalse(report['inference_available'])
        self.assertEqual(self.replay(events.records)['status'], 'INCOMPLETE')

    def test_replay_recomputes_whole_search_and_holdout(self):
        events, _ = self.complete()
        report = self.replay(events.records)
        self.assertEqual(report['status'], 'COMPLETE')
        self.assertEqual(report['completed_pipeline_runs'], 8)

    def test_rehashed_score_tampering_fails_replay(self):
        events, _ = self.complete()
        changed = deepcopy(events.records)
        event = next(row for row in changed if row['kind'] == 'evaluation_end')
        event['value']['result']['score_sum'] += 1
        with self.assertRaises(Rejected):
            self.replay(changed)

    def test_missing_footer_disables_inference_with_all_results_present(self):
        events, _ = self.complete()
        records = events.records[:-1]
        report = summarize_search(self.plan, records)
        self.assertEqual(report['completed_pipeline_runs'], 8)
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertFalse(report['inference_available'])
        self.assertEqual(self.replay(records)['status'], 'INCOMPLETE')

    def test_paint_cannot_turn_proxy_reward_into_holdout_success(self):
        config = dict(self.config, fixture_fault='paint')
        plan, reveal = make_search_plan(config, check_sources(), 17, 'a' * 64)
        events, _ = self.complete(plan, reveal)
        report = summarize_search(plan, events.records)
        self.assertTrue(all(row['successes'] == 0 for row in report['runs']))
        self.assertTrue(all(row['bad_search'] for row in report['runs']))

    def test_provider_contract_violation_disables_comparisons(self):
        config = dict(self.config, fixture_fault='overrun')
        plan, reveal = make_search_plan(config, check_sources(), 17, 'a' * 64)
        events, _ = self.complete(plan, reveal)
        report = summarize_search(plan, events.records)
        self.assertEqual(report['status'], 'PROVIDER_CONTRACT_VIOLATION')
        self.assertFalse(report['inference_available'])
        self.assertEqual(report['comparisons'], {})

    def test_outer_repetitions_are_the_statistical_unit(self):
        events, _ = self.complete()
        report = summarize_search(self.plan, events.records)
        for method in METHODS:
            self.assertEqual(report['methods'][method]['requested'], 2)
        self.assertEqual(len(report['comparisons']), 3)
        for comparison in report['comparisons'].values():
            intervals = [key for key in comparison if key.endswith('interval')]
            self.assertEqual(len(intervals), 3)

    def test_candidate_cannot_select_new_route_or_exceed_space(self):
        for candidate in ({'arm': 'fresh', 'max_calls': 64},
                          {'arm': 'selector', 'max_calls': 40},
                          {'arm': 'fresh', 'max_calls': 4, 'model': 'other'}):
            with self.assertRaises(Rejected):
                validate_candidate(candidate)
        invalid = dict(self.config, repetitions=0)
        with self.assertRaises(Rejected):
            validate_config(invalid)


if __name__ == '__main__':
    unittest.main()
