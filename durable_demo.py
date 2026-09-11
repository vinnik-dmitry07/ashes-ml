'''Demonstrate stale snapshot rejection through the persistent owner.'''

from pathlib import Path
import tempfile

from ahsl.codec import Rejected, canonical, decode
from ahsl.durable import DurableSession
from ahsl.examples import corridor_agent


def run(manifest):
    key = b'durable-demo-public-key-not-production'
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'checkpoint.sqlite'
        owner = DurableSession.create(path, corridor_agent('paint'), 4,
                                      key, manifest, [1])

        def request(command):
            reply = decode(owner.handle(canonical(command)))
            assert reply['code'] == 'OK'
            return reply['value']

        plan = request({'op': 'propose', 'program': corridor_agent()})
        assignments = request({'op': 'evaluate', 'plan': plan})
        old, old_anchor = owner.checkpoint()
        command = {'op': 'admit', 'plan': plan, 'assignments': assignments}
        decision = request(command)
        assert decision['accept']
        stale_results = []
        for _ in range(4):
            try:
                unexpected = DurableSession.restore(path, old, key, old_anchor)
                unexpected.close()
                stale_results.append('UNEXPECTED_ACCEPT')
            except Rejected as error:
                stale_results.append(str(error))
        current, anchor = owner.checkpoint()
        restored = DurableSession.restore(path, current, key, anchor)
        duplicate = decode(restored.handle(canonical(command)))
        final, final_anchor = restored.checkpoint()
        restored.close()
        owner.close()
        assert stale_results == ['STALE'] * 4
        assert duplicate['code'] == 'STALE'
        return {'stale_restore_results': stale_results,
                'duplicate_admit_result': duplicate['code'],
                'generation': final['ledger']['state']['generation'],
                'spent_execution_tickets': final['ledger']['state']['spent'],
                'old_revision': old_anchor['revision'],
                'final_revision': final_anchor['revision']}
