'''Audit regressions: fair search, size invariance and durable freshness.'''

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from ahsl.admission import Session
from ahsl.api import handle
from ahsl.codec import Rejected, canonical, cid, decode
from ahsl.durable import DurableSession
from ahsl.examples import builtin, call, corridor_agent, function, lit
from ahsl.examples import program, var
from ahsl.language import alpha_normalize, check, execute, program_cost_bytes
from ahsl.obligations import create_mission
from ahsl.proofs import check_certificate, search


KEY = b'release-15-public-test-key-not-production'
MANIFEST = cid('Manifest', 'release-15-tests')


class Release15Tests(unittest.TestCase):
    def rejects(self, code, action, *args):
        with self.assertRaises(Rejected) as caught:
            action(*args)
        self.assertEqual(str(caught.exception), code)

    def owner(self, directory):
        path = Path(directory) / 'checkpoint.sqlite'
        owner = DurableSession.create(path, corridor_agent('paint'), 8,
                                      KEY, MANIFEST, [1])
        self.addCleanup(owner.close)
        return owner, path

    def send(self, owner, command):
        result = decode(owner.handle(canonical(command)))
        self.assertEqual(result['code'], 'OK')
        return result['value']

    def prepare_evaluated(self, owner):
        plan = self.send(owner, {'op': 'propose',
                                 'program': corridor_agent()})
        assignments = self.send(owner, {'op': 'evaluate', 'plan': plan})
        return {'op': 'admit', 'plan': plan, 'assignments': assignments}

    def test_alpha_rename_cannot_be_a_cost_improvement(self):
        baseline = corridor_agent()
        candidate = deepcopy(baseline)
        candidate['entry'] = 'a'
        candidate['functions']['a'] = candidate['functions'].pop('main')
        self.assertLess(len(canonical(candidate)), len(canonical(baseline)))
        owner = Session(baseline, 8, KEY, MANIFEST, [1, 2])
        plan = owner.prepare(candidate, [1, 2])
        result = owner.admit(plan, owner.evaluate(plan))
        self.assertEqual(result['pairs'], [[True, True], [True, True]])
        self.assertFalse(result['accept'])
        self.assertFalse(result['improvement']['cost_strict'])
        for parent, child in result['improvement']['cost_pairs']:
            self.assertEqual(parent, child)
        self.assertEqual(owner.ledger.state['generation'], 0)

    def test_alpha_names_preserve_calls_parameters_and_shadowing(self):
        def build(entry, helper, parameter, local):
            body = {'op': 'let', 'name': local, 'value': lit(3, 'Int'),
                    'body': {'op': 'let', 'name': local,
                             'value': builtin('add', var(local),
                                              lit(2, 'Int')),
                             'body': var(local)}}
            return {'entry': entry, 'functions': {
                entry: function({}, 'Int', call(helper, body)),
                helper: function({parameter: 'Int'}, 'Int',
                                 builtin('add', var(parameter),
                                         lit(1, 'Int'))),
            }}
        left = build('long_entry', 'a_helper', 'long_arg', 'long_local')
        right = build('a', 'z', 'x', 'q')
        self.assertEqual(program_cost_bytes(left), program_cost_bytes(right))
        for item in (left, right):
            self.assertEqual(execute(item, [], 100),
                             execute(alpha_normalize(item), [], 100))
            self.assertEqual(execute(item, [], 100)['result'], 6)

    def test_alpha_normalization_leaves_literal_code_lookalikes_opaque(self):
        payload = {'op': 'call', 'name': 'main', 'args': ['unused']}
        tag = {'Record': {'op': 'Text', 'name': 'Text',
                          'args': {'List': 'Text'}}}
        item = program(lit(payload, tag), tag)
        normalized = alpha_normalize(item)
        self.assertEqual(normalized['functions']['f00']['body']['value'],
                         payload)
        self.assertEqual(execute(normalized, [], 100)['result'], payload)

    def test_shared_ast_nodes_are_normalized_per_lexical_occurrence(self):
        shared = var('value')
        body = builtin('add', shared, {
            'op': 'let', 'name': 'value', 'value': lit(10, 'Int'),
            'body': shared,
        })
        item = program(body, 'Int', {'value': 'Int'})
        original = canonical(item)
        normalized = alpha_normalize(item)
        self.assertEqual(execute(normalized, [3], 100),
                         execute(item, [3], 100))
        self.assertEqual(execute(normalized, [3], 100)['result'], 13)
        self.assertEqual(canonical(item), original)

    def test_equal_principals_are_rejected_by_low_level_mission(self):
        principal = cid('Principal', 'same')
        self.rejects('AUTHORITY', create_mission, MANIFEST, [1],
                     principal, principal)

    def test_invalid_service_registry_is_rejected_before_effects(self):
        calls = []
        item = program({'op': 'service', 'name': 's', 'args': []}, 'Int')
        registries = [0, [], {'s': None}, {'s': ([], 'Int')},
                      {'s': (None, 'Int', lambda: calls.append(1))},
                      {'s': ([], 'Int', 42)}]
        for registry in registries:
            self.rejects('SCHEMA', check, item, registry)
            self.rejects('SCHEMA', execute, item, [], 100, registry)
        self.assertEqual(calls, [])

    def test_same_conjunction_fragment_and_budget_for_both_searches(self):
        library = {}
        for key in ('A', 'B', 'C', 'D'):
            atom = ['atom', key]
            library[key] = {'goal': ['imp', atom, atom],
                            'term': ['lam', atom, ['var', 0]]}
        flat = ['and', library['C']['goal'], library['D']['goal']]
        nested = ['and', ['and', library['A']['goal'], library['B']['goal']],
                  flat]
        for goal, budget in ((flat, 1), (nested, 3)):
            reports = [search(goal, library, budget, mode)
                       for mode in ('forward', 'decompose')]
            self.assertEqual(reports[0], reports[1])
            self.assertEqual(reports[0]['attempts'], budget)
            self.assertEqual(reports[0]['status'], 'CHECKED')
            check_certificate(reports[0]['certificate'], library)
            for mode in ('forward', 'decompose'):
                self.assertEqual(search(goal, library, budget - 1,
                                        mode)['status'], 'UNKNOWN')

    def test_old_snapshot_cannot_repeat_an_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            owner, path = self.owner(directory)
            command = self.prepare_evaluated(owner)
            old, old_anchor = owner.checkpoint()
            self.assertTrue(self.send(owner, command)['accept'])
            for _ in range(4):
                self.rejects('STALE', DurableSession.restore,
                             path, old, KEY, old_anchor)
            current, anchor = owner.checkpoint()
            self.assertEqual(current['ledger']['state']['spent'], 2)
            restored = DurableSession.restore(path, current, KEY, anchor)
            self.addCleanup(restored.close)
            self.rejects('STALE', owner.handle, canonical(command))
            result = decode(restored.handle(canonical(command)))
            self.assertEqual(result['code'], 'STALE')
            final, _ = restored.checkpoint()
            self.assertEqual(final['ledger']['state']['spent'], 2)
            self.assertEqual(final['ledger']['state']['generation'], 1)

    def test_restore_claim_is_single_use_even_when_blob_has_not_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            owner, path = self.owner(directory)
            snapshot, anchor = owner.checkpoint()
            recovered = DurableSession.restore(path, snapshot, KEY, anchor)
            self.addCleanup(recovered.close)
            same, newer = recovered.checkpoint()
            self.assertEqual(same, snapshot)
            self.assertGreater(newer['revision'], anchor['revision'])
            self.rejects('STALE', DurableSession.restore,
                         path, snapshot, KEY, anchor)
            self.rejects('STALE', owner.checkpoint)

    def test_open_recovers_commit_without_a_new_client_side_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            owner, path = self.owner(directory)
            command = self.prepare_evaluated(owner)
            old, anchor = owner.checkpoint()
            owner.handle(canonical(command))
            owner.close()
            recovered = DurableSession.open(path, KEY)
            self.addCleanup(recovered.close)
            current, _ = recovered.checkpoint()
            self.assertEqual(current['ledger']['state']['generation'], 1)
            self.assertEqual(current['ledger']['state']['spent'], 2)
            self.rejects('STALE', DurableSession.restore,
                         path, old, KEY, anchor)
            self.assertEqual(decode(recovered.handle(
                canonical(command)))['code'], 'STALE')

    def test_competing_restores_have_exactly_one_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            owner, path = self.owner(directory)
            snapshot, anchor = owner.checkpoint()
            barrier = threading.Barrier(2)

            def restore():
                barrier.wait(timeout=5)
                try:
                    restored = DurableSession.restore(path, snapshot,
                                                      KEY, anchor)
                    restored.close()
                    return 'OK'
                except Rejected as error:
                    return str(error)

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: restore(), range(2)))
            self.assertCountEqual(results, ['OK', 'STALE'])

    def test_snapshot_integrity_and_root_authority_remain_required(self):
        with tempfile.TemporaryDirectory() as directory:
            owner, path = self.owner(directory)
            snapshot, anchor = owner.checkpoint()
            changed = deepcopy(snapshot)
            changed['requests_used'] += 1
            self.rejects('INTEGRITY', DurableSession.restore,
                         path, changed, KEY, anchor)
            self.rejects('AUTHORITY', DurableSession.restore,
                         path, snapshot, b'wrong-root-key-at-least-32-bytesxx',
                         anchor)
            self.assertEqual(owner.checkpoint(), (snapshot, anchor))

    def test_uncertain_operation_blocks_automatic_retry_after_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            owner, path = self.owner(directory)
            command = self.prepare_evaluated(owner)
            snapshot, anchor = owner.checkpoint()

            def crash_after_execution(session, request):
                handle(session, request)
                raise KeyboardInterrupt

            with patch('ahsl.durable.handle',
                       side_effect=crash_after_execution):
                with self.assertRaises(KeyboardInterrupt):
                    owner.handle(canonical(command))
            self.rejects('PHASE', owner.checkpoint)
            self.rejects('PHASE', owner.handle, canonical(command))
            self.rejects('PHASE', DurableSession.restore,
                         path, snapshot, KEY, anchor)
            self.rejects('PHASE', DurableSession.open, path, KEY)

    def test_completed_plans_keep_the_documented_lifetime_limit(self):
        owner = Session(corridor_agent('paint'), 24, KEY, MANIFEST, [1])
        for index in range(4):
            candidate = corridor_agent()
            key = 'entry' + str(index)
            candidate['entry'] = key
            candidate['functions'][key] = candidate['functions'].pop('main')
            plan = owner.prepare(candidate, [1], mode='retain')
            self.assertTrue(owner.admit(plan, owner.evaluate(plan))['accept'])
        self.assertEqual(owner.ledger.state['generation'], 4)
        self.assertEqual(owner.ledger.state['spent'], 8)
        result = decode(handle(owner, canonical({
            'op': 'propose', 'program': corridor_agent(),
        })))
        self.assertEqual(result['code'], 'LIMIT')
        self.assertEqual(len(owner.plans), 4)

    def test_outer_wire_rejection_does_not_advance_durable_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            owner, _ = self.owner(directory)
            before = owner.checkpoint()
            for request, code in (('not-bytes', 'SCHEMA'),
                                  (b'x' * 131073, 'LIMIT')):
                for _ in range(4):
                    self.assertEqual(decode(owner.handle(request))['code'],
                                     code)
            self.assertEqual(owner.checkpoint(), before)
