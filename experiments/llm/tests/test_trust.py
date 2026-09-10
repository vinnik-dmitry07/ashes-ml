'''Adversarial checks of evidence identity, revocation, and consumers.'''

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ahsl.codec import Rejected, canonical, cid
from ahsl.environment import ENVIRONMENT, Runner, scripted, solution
from ahsl.examples import corridor_agent
from llmbench.evidence_views import (
    BehaviorArchive, TrustedMemory, behavior_descriptor,
)
from llmbench.experiment import check_sources
from llmbench.protocol import Journal, digest, read_journal
from llmbench.trust import EvidenceLedger, MAX_DEPTH


KEY = b'offline-fixture-key-never-use-for-real-authority'
REASON = {'code': 'reviewed_counterexample', 'evidence': []}


def proof_payload(atom='P'):
    p = ['atom', atom]
    goal = ['imp', p, p]
    artifact = {'goal': goal, 'term': ['lam', p, ['var', 0]], 'library': {}}
    claim = {'kind': 'Proposition', 'goal': digest('Formula', goal)}
    return artifact, claim, {'library': cid('ProofLibrary', {})}


def trace_payload(level=1, actions=None):
    runner = Runner(KEY, 'a' * 64)
    assignment = runner.assign('b' * 64, 0, level, 0)
    trace = runner._run(assignment, scripted(
        solution(level) if actions is None else actions))['receipt']['trace']
    from ahsl.environment import audit_trace
    result = audit_trace(trace)
    return trace, {'kind': 'TraceConsistency', 'trace': result['trace'],
                   'ground_success': result['ground_success']}, {
                       'environment': ENVIRONMENT}


class TrustTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / 'trust.jsonl'
        self.ledger = EvidenceLedger(self.path, KEY, check_sources())
        self.owner = self.ledger.owner_handle
        self.proof = self.ledger.register(self.owner, 'F2_PROOF_1',
                                          {'fuel': 10000})
        self.bundle_checker = self.ledger.register(
            self.owner, 'EVIDENCE_BUNDLE_1', {})
        self.trace = self.ledger.register(self.owner, 'G12_TRACE_1',
                                          {'max_steps': 64,
                                           'require_goal': False})

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def evidence(self, atom='P'):
        result = self.ledger.submit(self.proof, *proof_payload(atom))
        self.assertEqual(result['status'], 'CHECKED')
        return result['receipt']

    def bundle(self, members):
        result = self.ledger.bundle(self.bundle_checker, members)
        self.assertEqual(result['status'], 'CHECKED')
        return result['receipt']

    def test_false_goal_and_definition_shadowing_rejected(self):
        artifact, claim, context = proof_payload()
        artifact['goal'] = ['bot']
        claim['goal'] = digest('Formula', ['bot'])
        result = self.ledger.submit(self.proof, artifact, claim, context)
        self.assertEqual(result['status'], 'REJECTED')
        self.assertIsNone(result['receipt'])
        p, q = ['atom', 'P'], ['atom', 'Q']
        library = {'same': {'goal': ['imp', q, q],
                            'term': ['lam', q, ['var', 0]]}}
        result = self.ledger.submit(self.proof, {
            'goal': ['imp', p, p], 'term': ['ref', 'same'], 'library': library,
        }, proof_payload()[1], {'library': cid('ProofLibrary', library)})
        self.assertEqual(result['code'], 'TYPE')

    def test_context_digest_is_measured(self):
        artifact, claim, context = proof_payload()
        context['library'] = 'f' * 64
        self.assertEqual(self.ledger.submit(
            self.proof, artifact, claim, context)['code'], 'INTEGRITY')

    def test_arbitrary_checker_name_and_role_string_confer_no_authority(self):
        before = self.ledger.head
        with self.assertRaises(Rejected):
            self.ledger.submit('trusted-checker', *proof_payload())
        with self.assertRaises(Rejected):
            self.ledger.register('owner', 'F2_PROOF_1', {'fuel': 1})
        self.assertEqual(self.ledger.head, before)

    def test_descriptor_cannot_be_added_to_trace_payload(self):
        artifact, claim, context = trace_payload()
        artifact['descriptor'] = {'recursion': True}
        self.assertEqual(self.ledger.submit(
            self.trace, artifact, claim, context)['code'], 'SCHEMA')

    def test_quarantine_blocks_retrieval_cache_and_all_exports(self):
        root = self.evidence()
        child = self.bundle([root])
        scope = self.ledger.receipt(root)['scope']
        memory = TrustedMemory(self.ledger)
        memory.add(child)
        view = memory.prepare(scope)
        dataset = memory.dataset([child], scope)
        publication = self.ledger.authorize([child], scope, 'publish')
        self.ledger.change_trust(self.owner, 'receipt', root,
                                 'QUARANTINED', REASON)
        self.assertEqual(self.ledger.status(child)['status'], 'BLOCKED')
        self.assertEqual(memory.read(scope), [])
        for action in (lambda: memory.consume(view),
                       lambda: memory.validate_dataset(dataset),
                       lambda: self.ledger.validate_authorization(
                           publication, 'publish')):
            with self.assertRaises(Rejected):
                action()

    def test_duplicate_receipts_cannot_launder_quarantined_artifact(self):
        first = self.evidence()
        second = self.evidence()
        self.assertNotEqual(first, second)
        self.ledger.change_trust(self.owner, 'receipt', first,
                                 'QUARANTINED', REASON)
        self.assertEqual(self.ledger.status(second)['status'], 'BLOCKED')
        with self.assertRaises(Rejected):
            self.evidence()

    def test_candidate_cannot_revalidate_or_lift_quarantine(self):
        root = self.evidence()
        self.ledger.change_trust(self.owner, 'receipt', root,
                                 'QUARANTINED', REASON)
        before = self.ledger.head
        with self.assertRaises(Rejected):
            self.ledger.revalidate('owner', root, self.proof)
        with self.assertRaises(Rejected):
            self.ledger.change_trust(self.owner, 'receipt', root,
                                     'ACTIVE', REASON)
        self.assertEqual(self.ledger.head, before)

    def test_revalidation_creates_new_evidence_without_rewriting_history(self):
        root = self.evidence()
        before = self.ledger.receipt(root)
        self.ledger.change_trust(self.owner, 'receipt', root,
                                 'REVOKED', REASON)
        new = self.ledger.revalidate(self.owner, root, self.proof)['receipt']
        self.assertNotEqual(root, new)
        self.assertEqual(self.ledger.receipt(root), before)
        self.assertEqual(self.ledger.status(root)['status'], 'REVOKED')
        self.assertEqual(self.ledger.status(new)['status'], 'ACTIVE')
        self.assertEqual(self.ledger.receipt(new)['supersedes'], root)

    def test_checker_revocation_propagates_and_replacement_rechecks(self):
        root = self.evidence()
        child = self.bundle([root])
        self.ledger.change_trust(self.owner, 'checker', self.proof,
                                 'REVOKED', REASON)
        self.assertEqual(self.ledger.status(child)['status'], 'BLOCKED')
        new_checker = self.ledger.register(self.owner, 'F2_PROOF_1',
                                           {'fuel': 9999})
        new = self.ledger.revalidate(self.owner, root, new_checker)['receipt']
        self.assertNotEqual(self.proof, self.ledger.receipt(new)['checker'])
        self.assertEqual(self.ledger.status(new)['status'], 'ACTIVE')
        self.assertEqual(self.ledger.status(child)['status'], 'BLOCKED')
        rebuilt = self.bundle([new])
        self.assertEqual(self.ledger.status(rebuilt)['status'], 'ACTIVE')

    def test_incomplete_checker_does_not_mint_a_certificate(self):
        checker = self.ledger.register(self.owner, 'F2_PROOF_1', {'fuel': 1})
        result = self.ledger.submit(checker, *proof_payload())
        self.assertEqual(result, {'status': 'INCOMPLETE', 'code': 'FUEL',
                                  'receipt': None})

    def test_stricter_checker_rejects_previously_valid_trace(self):
        result = self.ledger.submit(
            self.trace, *trace_payload(actions=['paint']))
        self.assertEqual(result['status'], 'CHECKED')
        strict = self.ledger.register(self.owner, 'G12_TRACE_1',
                                      {'max_steps': 64, 'require_goal': True})
        rechecked = self.ledger.revalidate(
            self.owner, result['receipt'], strict)
        self.assertEqual(rechecked['code'], 'POSTCONDITION')
        with self.assertRaises(Rejected):
            self.ledger.authorize([result['receipt']], ENVIRONMENT, 'training')

    def test_diamond_dependencies_are_deduplicated(self):
        root = self.evidence()
        left, right = self.bundle([root]), self.bundle([root])
        top = self.bundle([left, right])
        scope = self.ledger.receipt(root)['scope']
        authorization = self.ledger.authorize([top], scope, 'training')
        self.assertEqual(authorization['body']['leaves'], [root])

    def test_unrelated_evidence_does_not_invalidate_a_cached_view(self):
        root = self.evidence()
        scope = self.ledger.receipt(root)['scope']
        view = self.ledger.authorize([root], scope, 'retrieval')
        self.evidence('Q')
        self.assertEqual(self.ledger.validate_authorization(view, 'retrieval'),
                         [root])

    def test_caller_cannot_edit_dataset_or_receipt(self):
        root = self.evidence()
        memory = TrustedMemory(self.ledger)
        scope = self.ledger.receipt(root)['scope']
        dataset = memory.dataset([root], scope)
        dataset['body']['rows'][0]['sample']['artifact_hex'] = '00'
        dataset['id'] = digest('EvidenceDataset', dataset['body'])
        with self.assertRaises(Rejected):
            memory.validate_dataset(dataset)
        receipt = self.ledger.receipt(root)
        receipt['claim']['goal'] = 'f' * 64
        self.assertNotEqual(receipt, self.ledger.receipt(root))

    def test_scope_and_purpose_are_checked_at_consumption(self):
        root = self.evidence()
        scope = self.ledger.receipt(root)['scope']
        self.assertEqual(self.ledger.select([root], 'f' * 64), [])
        view = self.ledger.authorize([root], scope, 'retrieval')
        with self.assertRaises(Rejected):
            self.ledger.validate_authorization(view, 'publish')
        view['body']['purpose'] = 'publish'
        with self.assertRaises(Rejected):
            self.ledger.validate_authorization(view, 'publish')

    def test_failed_claim_does_not_lock_an_artifact(self):
        artifact, claim, context = proof_payload()
        bad = dict(claim, goal='f' * 64)
        self.assertEqual(self.ledger.submit(
            self.proof, artifact, bad, context)['status'], 'REJECTED')
        self.assertEqual(self.ledger.submit(
            self.proof, artifact, claim, context)['status'], 'CHECKED')

    def test_finite_inspection_budget_stops_repeated_bad_proofs(self):
        path = Path(self.temp.name) / 'small.jsonl'
        ledger = EvidenceLedger(path, KEY, check_sources(), max_checks=2)
        try:
            checker = ledger.register(ledger.owner_handle, 'F2_PROOF_1',
                                      {'fuel': 1})
            for _ in range(2):
                self.assertEqual(ledger.submit(checker, *proof_payload())[
                    'status'], 'INCOMPLETE')
            head = ledger.head
            with self.assertRaises(Rejected):
                ledger.submit(checker, *proof_payload())
            self.assertEqual(ledger.head, head)
        finally:
            ledger.close()

    def test_missing_dependency_and_depth_limit(self):
        with self.assertRaises((Rejected, KeyError)):
            self.bundle(['f' * 64])
        current = self.evidence()
        for _ in range(MAX_DEPTH - 1):
            current = self.bundle([current])
        result = self.ledger.bundle(self.bundle_checker, [current])
        self.assertEqual(result['code'], 'LIMIT')

    def test_archive_and_training_views_drop_quarantined_trace(self):
        root = self.ledger.submit(self.trace, *trace_payload())['receipt']
        archive = BehaviorArchive(self.ledger)
        archive.add(root)
        memory = TrustedMemory(self.ledger)
        data = memory.dataset([root], ENVIRONMENT)
        self.assertEqual(data['body']['rows'][0]['sample']['kind'],
                         'SYNTHETIC_VALIDATED_TRACE')
        self.assertEqual(len(archive.cells()), 1)
        self.ledger.change_trust(self.owner, 'receipt', root,
                                 'QUARANTINED', REASON)
        self.assertEqual(archive.cells(), {})
        with self.assertRaises(Rejected):
            memory.validate_dataset(data)

    def test_descriptors_ignore_dead_code_and_detect_behavior_change(self):
        baseline = corridor_agent()
        embellished = deepcopy(baseline)
        embellished['functions']['Unused'] = {
            'params': {}, 'result': 'Text',
            'body': {'op': 'lit', 'type': 'Text',
                     'value': 'This uses recursion and dynamic programming.'},
        }
        descriptors = []
        for program in (baseline, embellished):
            runner = Runner(KEY, 'a' * 64)
            assignment = runner.assign(cid('Program', program), 0, 2, 0)
            trace = runner.run(assignment, program)['receipt']['trace']
            descriptors.append(behavior_descriptor(trace))
        self.assertEqual(descriptors[0], descriptors[1])
        painted = behavior_descriptor(trace_payload(actions=['paint'])[0])
        self.assertNotEqual(painted['cell_id'], descriptors[0]['cell_id'])

    def test_replay_checks_signatures_and_reruns_checkers(self):
        root = self.evidence()
        self.ledger.change_trust(self.owner, 'receipt', root,
                                 'QUARANTINED', REASON)
        report = EvidenceLedger.replay(self.path, KEY, self.ledger.identity,
                                       self.ledger.head)
        self.assertEqual(
            report['state']['receipt_status'][root], 'QUARANTINED')
        with self.assertRaises(Rejected):
            EvidenceLedger.replay(self.path, b'wrong-key' * 4,
                                  self.ledger.identity, self.ledger.head)
        records = read_journal(
            self.path, self.ledger.identity, self.ledger.head)
        records[-1]['value']['body']['result']['status'] = 'ACTIVE'
        forged_path = Path(self.temp.name) / 'forged.jsonl'
        journal = Journal(forged_path, self.ledger.identity)
        for row in records:
            journal.append(row['kind'], row['value'])
        journal.close()
        with self.assertRaises(Rejected):
            EvidenceLedger.replay(forged_path, KEY, self.ledger.identity,
                                  journal.head)

    def test_event_budget_reserves_space_to_finish_an_admitted_check(self):
        path = Path(self.temp.name) / 'events-cap.jsonl'
        ledger = EvidenceLedger(path, KEY, check_sources(), max_events=3)
        try:
            checker = ledger.register(ledger.owner_handle, 'F2_PROOF_1',
                                      {'fuel': 100})
            result = ledger.submit(checker, *proof_payload())
            self.assertEqual(result['status'], 'CHECKED')
            with self.assertRaises(Rejected):
                ledger.submit(checker, *proof_payload())
        finally:
            ledger.close()

    def test_interrupted_check_resolves_without_reusing_quota(self):
        with patch.object(self.ledger, '_evaluate',
                          side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.ledger.submit(self.proof, *proof_payload())
        report = EvidenceLedger.replay(self.path, KEY, self.ledger.identity,
                                       self.ledger.head)
        pending = report['state']['pending']
        self.assertEqual(len(pending), 1)
        sequence = int(next(iter(pending)))
        before_checks = report['state']['checks']
        result = self.ledger.resolve_pending(self.owner, sequence)
        self.assertEqual(result['status'], 'CHECKED')
        replayed = EvidenceLedger.replay(self.path, KEY, self.ledger.identity,
                                         self.ledger.head)
        self.assertEqual(replayed['state']['checks'], before_checks)
        self.assertEqual(replayed['state']['pending'], {})

    def test_local_export_rechecks_trust_at_write_boundary(self):
        root = self.evidence()
        memory = TrustedMemory(self.ledger)
        scope = self.ledger.receipt(root)['scope']
        dataset = memory.dataset([root], scope)
        first = Path(self.temp.name) / 'first.json'
        memory.export_dataset(dataset, first)
        self.assertTrue(first.is_file())
        self.ledger.change_trust(
            self.owner, 'receipt', root, 'REVOKED', REASON)
        second = Path(self.temp.name) / 'second.json'
        with self.assertRaises(Rejected):
            memory.export_dataset(dataset, second)
        self.assertFalse(second.exists())

    def test_insufficient_event_capacity_does_not_leave_pending_check(self):
        path = Path(self.temp.name) / 'no-completion-slot.jsonl'
        ledger = EvidenceLedger(path, KEY, check_sources(), max_events=2)
        try:
            checker = ledger.register(ledger.owner_handle, 'F2_PROOF_1',
                                      {'fuel': 100})
            before = ledger.head
            with self.assertRaises(Rejected):
                ledger.submit(checker, *proof_payload())
            self.assertEqual(ledger.head, before)
        finally:
            ledger.close()

    def test_oversize_payload_is_rejected_before_check_quota(self):
        before = self.ledger.head
        with self.assertRaises(Rejected):
            self.ledger.submit(self.proof, 'x' * 262145, {}, {})
        self.assertEqual(self.ledger.head, before)

    def test_unknown_or_malformed_bundle_member_is_structured_rejection(self):
        for members in (['f' * 64], [{}], ['not-a-receipt'], 'not-a-list'):
            with self.subTest(members=members):
                with self.assertRaises(Rejected):
                    self.ledger.bundle(self.bundle_checker, members)

    def test_fsync_failure_fences_writer_without_publishing_new_state(self):
        root = self.evidence()
        before = self.ledger.head
        with patch.object(self.ledger._journal, 'append',
                          side_effect=OSError('simulated disk failure')):
            with self.assertRaises(OSError):
                self.ledger.change_trust(self.owner, 'receipt', root,
                                         'QUARANTINED', REASON)
        self.assertEqual(self.ledger.head, before)
        self.assertEqual(self.ledger.status(root)['status'], 'UNAVAILABLE')
        with self.assertRaises(Rejected):
            self.evidence('Q')

    def test_snapshot_limit_preserves_encodable_replay(self):
        with patch('ahsl.codec.MAX_BYTES', 10000):
            for _ in range(30):
                try:
                    self.evidence()
                except Rejected as error:
                    self.assertEqual(str(error), 'LIMIT')
                    break
            else:
                self.fail('The aggregate snapshot limit was not enforced')
            report = EvidenceLedger.replay(
                self.path, KEY, self.ledger.identity, self.ledger.head)
            self.assertLessEqual(len(canonical(report['state'])), 10000)


if __name__ == '__main__':
    unittest.main()
