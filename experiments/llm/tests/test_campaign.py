'''Campaign accounting, immutable inputs, and independent replay checks.'''

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ahsl.codec import Rejected, canonical
from llmbench.experiment import (
    ROOT, check_sources, make_plan, replay_campaign, run_campaign,
    source_manifest,
)
from llmbench.protocol import Journal, digest, read_journal
from llmbench.providers import FixtureProvider
from llmbench.statistics import summarize, tail_mean, quantile_interval


CONFIG = json.loads((ROOT / 'configs/fixture.json').read_text())


class CampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = TemporaryDirectory()
        cls.output = Path(cls.temporary.name) / 'complete'
        cls.config = dict(CONFIG, cases=2)
        cls.report = run_campaign(cls.config, cls.output)
        cls.head = cls.report['journal_head']
        cls.plan = json.loads((cls.output / 'plan.json').read_text())
        cls.identity = {'plan': digest('CampaignPlan', cls.plan)}
        cls.records = read_journal(
            cls.output / 'events.jsonl', cls.identity, cls.head)
        cls.results = [row['value'] for row in cls.records
                       if row['kind'] == 'run_end']

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def rewrite(self, records):
        directory = Path(self.temporary.name) / self._testMethodName
        directory.mkdir()
        (directory / 'plan.json').write_bytes(canonical(self.plan))
        journal = Journal(directory / 'events.jsonl', self.identity)
        for row in records:
            journal.append(row['kind'], row['value'])
        journal.close()
        return directory, journal.head

    def test_real_campaign_replays_all_requests_costs_and_traces(self):
        replayed = replay_campaign(self.output, self.head)
        self.assertEqual(replayed['status'], 'COMPLETE')
        self.assertEqual(replayed['replayed_completed_runs'], 8)
        self.assertFalse(self.report['quality_evidence_from_llm'])
        self.assertEqual(self.report['ledger']['accounted_cost_microusd'],
                         sum(row['accounted_cost_microusd']
                             for row in self.results))

    def test_planned_cases_are_paired_and_have_identical_budgets(self):
        plan = make_plan(self.config, 'a' * 64, FixtureProvider.mode)
        self.assertEqual(plan, make_plan(
            self.config, 'a' * 64, FixtureProvider.mode))
        for case in range(2):
            slots = [slot for slot in plan['slots'] if slot['case'] == case]
            self.assertEqual(len(slots), 4)
            self.assertEqual(len({slot['level'] for slot in slots}), 1)
            self.assertEqual(len({slot['model_seed'] for slot in slots}), 1)

    def test_journal_tamper_fails_against_external_head(self):
        records = deepcopy(self.records)
        records[-1]['value']['completed_runs'] = 99
        directory, _ = self.rewrite(records)
        with self.assertRaises(Rejected):
            replay_campaign(directory, self.head)

    def test_rehashed_false_cost_fails_semantic_replay(self):
        records = deepcopy(self.records)
        row = next(row for row in records if row['kind'] == 'call_end')
        row['value']['charge_microusd'] = 0
        directory, head = self.rewrite(records)
        with self.assertRaises(Rejected):
            replay_campaign(directory, head)

    def test_rehashed_false_call_role_fails_semantic_replay(self):
        records = deepcopy(self.records)
        row = next(row for row in records if row['kind'] == 'call_start')
        row['value']['role'] = 'unrecorded-role'
        directory, head = self.rewrite(records)
        with self.assertRaises(Rejected):
            replay_campaign(directory, head)

    def test_missing_footer_is_incomplete_even_with_all_results(self):
        directory, head = self.rewrite(self.records[:-1])
        replayed = replay_campaign(directory, head)
        self.assertEqual(replayed['replayed_completed_runs'], 8)
        self.assertEqual(replayed['status'], 'INCOMPLETE')

    def test_missing_runs_keep_denominator_and_disable_inference(self):
        report = summarize(self.plan, self.results[:-1], 'LIVE_HTTP')
        self.assertEqual(report['missing_requested_runs'], 1)
        self.assertFalse(report['quality_evidence_from_llm'])
        self.assertEqual(report['selector_minus_baseline'], {})
        for row in report['conditions'].values():
            self.assertEqual(row['requested'], 2)
            self.assertIsNone(row['failure_95_interval'])

    def test_provider_breach_disables_all_quality_inference(self):
        results = deepcopy(self.results)
        results[0]['provider_contract_violated'] = True
        report = summarize(self.plan, results, 'LIVE_HTTP')
        self.assertEqual(report['status'], 'PROVIDER_CONTRACT_VIOLATION')
        self.assertFalse(report['quality_evidence_from_llm'])
        self.assertEqual(report['selector_minus_baseline'], {})

    def test_all_done_but_source_drift_cannot_attest_completion(self):
        directory = Path(self.temporary.name) / self._testMethodName
        manifest = check_sources()
        # Initial check + before/after four runs: drift at the final check.
        checks = [manifest] * 8 + [Rejected('INTEGRITY')]
        with patch('llmbench.experiment.check_sources', side_effect=checks):
            with self.assertRaises(Rejected):
                run_campaign(dict(CONFIG, cases=1), directory)
        report = json.loads((directory / 'summary.json').read_text())
        self.assertEqual(report['missing_requested_runs'], 0)
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertFalse(report['quality_evidence_from_llm'])
        self.assertEqual(report['campaign_error'], 'Rejected')

    def test_interrupted_request_remains_reserved_and_never_resumed(self):
        directory = Path(self.temporary.name) / self._testMethodName

        class InterruptedProvider(FixtureProvider):
            def complete(self, request):
                raise KeyboardInterrupt()

        with patch('llmbench.experiment.FixtureProvider', InterruptedProvider):
            with self.assertRaises(KeyboardInterrupt):
                run_campaign(dict(CONFIG, cases=1), directory)
        report = json.loads((directory / 'summary.json').read_text())
        self.assertEqual(report['missing_requested_runs'], 4)
        self.assertEqual(report['ledger']['pending_calls'], 1)
        self.assertGreater(report['ledger']['accounted_cost_microusd'], 0)
        self.assertEqual(report['ledger']['accounted_cost_microusd'],
                         report['ledger']['pending_reservation_microusd'])
        with self.assertRaises(FileExistsError):
            run_campaign(dict(CONFIG, cases=1), directory)

    def test_source_check_detects_a_changed_runtime_file(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'module.py').write_text('x = 1\n')
            (root / 'source-manifest.json').write_bytes(
                canonical(source_manifest(root)))
            check_sources(root)
            (root / 'module.py').write_text('x = 2\n')
            with self.assertRaises(Rejected):
                check_sources(root)

    def test_five_perfect_runs_do_not_certify_bottom_decile(self):
        interval = quantile_interval([1] * 5, 0.1, 0, 1)
        self.assertEqual(interval, [0, 1])
        self.assertAlmostEqual(tail_mean([0, 10, 20], fraction=0.5), 10 / 3)

    def test_selector_comparisons_include_tail_uncertainty(self):
        for row in self.report['selector_minus_baseline'].values():
            interval = row['simultaneous_worst_10_percent_gain_interval']
            self.assertLessEqual(interval[0], 0)
            self.assertGreaterEqual(interval[1], 0)


if __name__ == '__main__':
    unittest.main()
