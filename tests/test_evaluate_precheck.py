'''Re-evaluating an abandoned plan must not change the ledger.'''

from copy import deepcopy
import unittest

from src.admission import Session
from src.api import handle
from src.codec import canonical, cid, decode
from src.examples import corridor_agent


KEY = b'local-review-public-fixture-key-only'


def send(owner, request):
    '''Return the decoded wire reply.'''
    return decode(handle(owner, canonical(request)))


class EvaluatePrecheckTests(unittest.TestCase):
    def test_abandoned_plan_rejects_before_the_ledger_changes(self):
        for reserved in (False, True):
            with self.subTest(reserved=reserved):
                self.check_abandoned(reserved)

    def check_abandoned(self, reserved):
        owner = Session(
            corridor_agent('paint'), 8, KEY, cid('Manifest', {}), [1],
        )
        first = send(owner, {
            'op': 'propose', 'program': corridor_agent(),
        })
        self.assertEqual(first['code'], 'OK')
        plan = first['value']
        owner.ledger.apply('agent', {'op': 'start_run'})
        owner.active_plan = plan
        if reserved:
            for pair in owner.plans[plan]['assignments']:
                for assignment in pair:
                    sequence = owner.runner.issued[assignment]['sequence']
                    owner.ledger.apply('agent', {
                        'op': 'reserve',
                        'job': 'j' + str(sequence),
                        'upper': 1,
                    })
        self.assertTrue(owner.abandon(plan))
        if reserved:
            phases = {
                job['phase']
                for job in owner.ledger.state['jobs'].values()
            }
            self.assertEqual(phases, {'CANCELLED'})
        else:
            self.assertEqual(owner.ledger.state['jobs'], {})
            self.assertTrue(owner.runner.fenced)
        before = deepcopy(owner.ledger.state)
        log_length = len(owner.ledger.log)
        rejected = send(owner, {'op': 'evaluate', 'plan': plan})
        self.assertEqual(rejected['code'], 'PHASE')
        self.assertEqual(owner.ledger.state, before)
        self.assertEqual(len(owner.ledger.log), log_length)
        self.assertIsNone(owner.active_plan)

        second = send(owner, {
            'op': 'propose', 'program': corridor_agent(),
        })
        self.assertEqual(second['code'], 'OK')
        evaluated = send(owner, {
            'op': 'evaluate', 'plan': second['value'],
        })
        self.assertEqual(evaluated['code'], 'OK')
        admitted = send(owner, {
            'op': 'admit', 'plan': second['value'],
            'assignments': evaluated['value'],
        })
        self.assertEqual(admitted['code'], 'OK')
        self.assertTrue(admitted['value']['accept'])
