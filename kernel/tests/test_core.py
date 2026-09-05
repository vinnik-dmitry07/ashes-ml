'''Behavioral conformance cases and adversarial event inputs.'''

from copy import deepcopy
import unittest

from core import (
    MAX_NAT, SchemaError, initial, invariants, load_json, replay, step,
)


def value(number):
    return {'type': 'nat', 'value': number}


def manifest(budget=2):
    return {
        'version': '0.5', 'budget': budget,
        'cells': {
            'x': {'type': 'nat', 'live': True, 'value': value(0)},
            'untouched': {'type': 'nat', 'live': True, 'value': value(7)},
        },
        'components': {
            'worker': {
                'inputs': {}, 'output': 'nat', 'read': ['x'],
                'write': ['x'], 'cost': 1,
            },
        },
    }


class KernelCases(unittest.TestCase):
    def setUp(self):
        self.state = initial(manifest())
        self.count = 0

    def event(self, kind, principal='agent', **kwargs):
        self.count += 1
        event = {'id': f'e{self.count}', 'kind': kind, **kwargs}
        old = deepcopy(self.state)
        self.state, result, requests = step(self.state, principal, event)
        self.assertTrue(invariants(self.state))
        self.assertEqual(old['manifest'], self.state['manifest'])
        self.assertEqual(
            old['cells']['untouched'], self.state['cells']['untouched']
        )
        return result, requests

    def reserve(self, job='j1'):
        return self.event('reserve', job=job, component='worker', args={})

    def start(self, job='j1'):
        self.assertEqual(self.reserve(job)[0]['code'], 'OK')
        self.assertEqual(self.event('dispatch', job=job)[0]['code'], 'OK')

    def complete(self, job='j1', writes=None, charge=1, output=None):
        if writes is None:
            writes = [{'op': 'replace', 'cell': 'x', 'value': value(1)}]
        outcome = {
            'kind': 'success', 'value': value(1) if output is None else output,
            'writes': writes,
        }
        return self.event(
            'complete', principal='provider', job=job,
            charge=charge, outcome=outcome,
        )

    def test_conflict_still_charges(self):
        self.start('j1')
        self.start('j2')
        self.assertEqual(self.complete('j1')[0]['result']['code'], 'SUCCESS')
        result, _ = self.complete('j2')
        self.assertEqual(result['result']['code'], 'CONFLICT')
        self.assertEqual(self.state['spent'], 2)
        self.assertEqual(self.state['cells']['x']['version'], 1)

    def test_reply_after_unknown(self):
        self.start()
        self.event('unknown', principal='provider', job='j1')
        self.assertEqual(self.state['available'], 1)
        for kind in ('cancel', 'dispatch'):
            self.assertEqual(
                self.event(kind, job='j1')[0]['code'], 'BAD_PHASE'
            )
        self.assertEqual(self.complete()[0]['result']['code'], 'SUCCESS')

    def test_cancellation_refunds_only_reserved(self):
        self.reserve()
        self.event('cancel', job='j1')
        self.assertEqual(self.state['available'], 2)
        self.assertEqual(self.state['spent'], 0)
        self.assertEqual(self.reserve()[0]['code'], 'JOB_EXISTS')

    def test_budget_rejects_oversubscription(self):
        self.state = initial(manifest(1))
        self.reserve('j1')
        self.assertEqual(self.reserve('j2')[0]['code'], 'BUDGET')
        self.assertNotIn('j2', self.state['jobs'])

    def test_revoked_in_flight_work_is_charged_without_commit(self):
        self.start()
        self.event('revoke', principal='supervisor', component='worker')
        result, _ = self.complete()
        self.assertEqual(result['result']['code'], 'STALE_POLICY')
        self.assertEqual(self.state['spent'], 1)
        self.assertEqual(self.state['cells']['x']['version'], 0)

    def test_unauthorized_principal_cannot_revoke(self):
        result, _ = self.event('revoke', component='worker')
        self.assertEqual(result['code'], 'FORBIDDEN')
        self.assertEqual(self.state['epoch'], 0)

    def test_stale_dispatch_can_be_cancelled(self):
        self.reserve()
        self.event('revoke', principal='supervisor', component='worker')
        self.assertEqual(
            self.event('dispatch', job='j1')[0]['code'], 'STALE_POLICY'
        )
        self.assertEqual(self.event('cancel', job='j1')[0]['code'], 'OK')

    def test_idempotence_never_redispatches(self):
        self.reserve()
        event = {'id': 'delivery', 'kind': 'dispatch', 'job': 'j1'}
        first, result, requests = step(self.state, 'agent', event)
        second, repeated, repeated_requests = step(first, 'agent', event)
        self.assertEqual(first, second)
        self.assertEqual(result, repeated)
        self.assertEqual(len(requests), 1)
        self.assertEqual(repeated_requests, [])
        event['job'] = 'j2'
        _, error, _ = step(first, 'agent', event)
        self.assertEqual(error['code'], 'EVENT_ID_REUSE')

    def test_same_completion_different_id_does_not_double_charge(self):
        self.start()
        self.complete()
        self.assertEqual(self.complete()[0]['code'], 'BAD_PHASE')
        self.assertEqual(self.state['spent'], 1)

    def test_rejected_write_set_is_atomic(self):
        self.start()
        writes = [
            {'op': 'replace', 'cell': 'x', 'value': value(3)},
            {'op': 'replace', 'cell': 'untouched', 'value': value(3)},
        ]
        self.assertEqual(
            self.complete(writes=writes)[0]['result']['code'], 'WRITE_DENIED'
        )
        self.assertEqual(self.state['cells']['x']['value'], value(0))

    def test_duplicate_write_does_not_increment_twice(self):
        self.start()
        write = {'op': 'replace', 'cell': 'x', 'value': value(3)}
        result, _ = self.complete(writes=[write, write])
        self.assertEqual(result['result']['code'], 'DUPLICATE_WRITE')
        self.assertEqual(self.state['cells']['x']['version'], 0)

    def test_type_error_still_charges(self):
        self.start()
        result, _ = self.complete(output={'type': 'bool', 'value': True})
        self.assertEqual(result['result']['code'], 'OUTPUT_TYPE')
        self.assertEqual(self.state['spent'], 1)

    def test_write_type_error_is_atomic(self):
        self.start()
        writes = [{'op': 'replace', 'cell': 'x', 'value': {'type': 'unit'}}]
        result, _ = self.complete(writes=writes)
        self.assertEqual(result['result']['code'], 'WRITE_TYPE')

    def test_tombstone_keeps_monotone_version(self):
        self.start('j1')
        self.complete('j1', writes=[{'op': 'delete', 'cell': 'x'}])
        self.start('j2')
        result, _ = self.complete('j2', writes=[{
            'op': 'create', 'cell': 'x', 'value': value(4),
        }])
        self.assertEqual(result['result']['code'], 'SUCCESS')
        self.assertEqual(self.state['cells']['x']['version'], 2)
        self.assertTrue(self.state['cells']['x']['live'])

    def test_aba_delete_create_invalidates_old_snapshot(self):
        self.state = initial(manifest(3))
        self.start('old')
        self.start('delete')
        self.complete('delete', writes=[{'op': 'delete', 'cell': 'x'}])
        self.start('create')
        self.complete('create', writes=[{
            'op': 'create', 'cell': 'x', 'value': value(0),
        }])
        self.assertEqual(self.complete('old')[0]['result']['code'], 'CONFLICT')

    def test_wrong_lifecycle_rejected(self):
        self.start()
        result, _ = self.complete(writes=[{
            'op': 'create', 'cell': 'x', 'value': value(4),
        }])
        self.assertEqual(result['result']['code'], 'CELL_LIFECYCLE')

    def test_out_of_envelope_charge_keeps_reservation(self):
        self.start()
        result, _ = self.complete(charge=2)
        self.assertEqual(result['code'], 'CHARGE_EXCEEDS_RESERVE')
        self.assertEqual(self.state['jobs']['j1']['held'], 1)
        self.assertEqual(self.state['spent'], 0)

    def test_partial_charge_returns_remainder(self):
        self.start()
        self.complete(charge=0)
        self.assertEqual(self.state['available'], 2)

    def test_component_failure_settles(self):
        self.start()
        result, _ = self.event(
            'complete', principal='provider', job='j1', charge=1,
            outcome={'kind': 'failure', 'code': 'model_error'},
        )
        self.assertEqual(result['result']['code'], 'COMPONENT_FAILURE')
        self.assertEqual(self.state['spent'], 1)

    def test_replay_matches_exact_control_state(self):
        self.start()
        self.event('unknown', principal='provider', job='j1')
        self.complete()
        reconstructed = replay(self.state['manifest'], self.state['log'])
        self.assertEqual(reconstructed, self.state)

    def test_boolean_is_not_natural(self):
        bad = deepcopy(manifest())
        bad['budget'] = True
        with self.assertRaises(SchemaError):
            initial(bad)

    def test_invalid_json_is_rejected(self):
        for data in ('{"a":1,"a":2}', '1.0', 'NaN', '"\\ud800"', '-1'):
            with self.subTest(data=data), self.assertRaises(SchemaError):
                load_json(data)

    def test_malformed_events_do_not_mutate_state(self):
        for event in (None, [], {}, {'kind': []}, {'id': 'e', 'kind': 'halt'}):
            state, result, requests = step(self.state, 'agent', event)
            self.assertEqual(result['code'], 'BAD_SCHEMA')
            self.assertEqual(state, self.state)
            self.assertEqual(requests, [])

    def test_version_exhaustion_cannot_wrap(self):
        self.state['cells']['x']['version'] = MAX_NAT
        self.start()
        result, _ = self.complete()
        self.assertEqual(result['result']['code'], 'VERSION_EXHAUSTED')
        self.assertEqual(self.state['cells']['x']['version'], MAX_NAT)

    def test_empty_write_still_validates_snapshot(self):
        self.start('j1')
        self.start('j2')
        self.complete('j1')
        self.assertEqual(
            self.complete('j2', writes=[])[0]['result']['code'], 'CONFLICT'
        )

    def test_input_aliases_cannot_mutate_state(self):
        data = manifest()
        state = initial(data)
        data['cells']['x']['value']['value'] = 100
        self.assertEqual(state['cells']['x']['value'], value(0))

    def test_response_aliases_cannot_mutate_state(self):
        self.start()
        result, _ = self.complete()
        result['result']['value']['value'] = 100
        stored = self.state['jobs']['j1']['result']['value']
        self.assertEqual(stored, value(1))


if __name__ == '__main__':
    unittest.main()
