'''Deterministic Session fixture, including contracts and the request log.'''

import json
from pathlib import Path

from src.admission import Session, formalize
from src.api import handle
from src.codec import canonical, cid, decode
from src.examples import corridor_agent
from src.obligations import DEFAULT_GUARANTEES


def run(manifest):
    owner = Session(corridor_agent('paint'), 4,
                    b'replay-fixture-key-not-for-production', manifest, [1])

    def request(command):
        reply = decode(handle(owner, canonical(command)))
        assert reply['code'] == 'OK', reply
        return reply['value']

    guarantees = dict(DEFAULT_GUARANTEES, max_actions=4)
    plan = request({'op': 'propose_contracted', 'program': corridor_agent(),
                    'guarantees': guarantees, 'mode': 'improve'})
    ids = request({'op': 'evaluate', 'plan': plan})
    decision = request({'op': 'admit', 'plan': plan, 'assignments': ids})
    assert decision['accept']
    receipt = request({'op': 'read_receipt', 'assignment': ids[1]})
    request({'op': 'train', 'envelope': receipt})
    policy = request({'op': 'condense', 'assignments': [ids[1]]})
    plan = request({'op': 'propose_contracted', 'program': formalize(policy),
                    'guarantees': guarantees, 'mode': 'retain'})
    ids = request({'op': 'evaluate', 'plan': plan})
    decision = request({'op': 'admit', 'plan': plan, 'assignments': ids})
    assert decision['accept']
    return cid('SessionSnapshot', owner.snapshot())


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / 'manifest.json').read_text())
    print(run(cid('Manifest', manifest)))
