'''Evaluator with a read-only observation capability and its own key.'''

from copy import deepcopy
import hashlib
import hmac

from .codec import canonical, cid, fields, need
from .environment import audit_trace, observe
from .language import execute
from .obligations import violations


def derive_key(root, purpose):
    need(type(root) is bytes and len(root) >= 32)
    return hmac.new(root, purpose.encode('ascii'), hashlib.sha256).digest()


def key_id(key):
    return hashlib.sha256(key).hexdigest()


class Evaluator:
    '''No dispatch, observation-write or executor-signing capability.'''

    def __init__(self, key, read_observation):
        need(type(key) is bytes and len(key) >= 32)
        self._key = key
        self.identifier = key_id(key)
        self._read_observation = read_observation

    def assess(self, envelope, program, mission, guarantees):
        canonical(envelope)
        fields(envelope, ('receipt', 'tag'))
        fields(envelope['receipt'], ('binding', 'trace'))
        trace = envelope['receipt']['trace']
        assignment = trace['assignment']
        observed = self._read_observation(assignment)
        need(canonical(observed) == canonical(envelope), 'AUTHORITY')
        binding = envelope['receipt']['binding']
        need(binding['mission'] == cid('Mission', mission), 'STALE')
        need(binding['guarantees'] == cid('Guarantees', guarantees), 'STALE')
        need(binding['manifest'] == mission['manifest'], 'STALE')
        need(binding['candidate'] == cid('Program', program), 'INTEGRITY')
        need(trace['candidate'] == binding['candidate'], 'INTEGRITY')
        need(mission['evaluator'] == self.identifier, 'AUTHORITY')
        outcome = audit_trace(trace)
        remaining = 50000
        for index, record in enumerate(trace['steps']):
            result = execute(program, [
                index, observe(record['before'], trace['level']),
                cid('GroundState', record['before']),
            ], remaining)
            remaining -= result['fuel_used']
            need(canonical(result['result']) == canonical(record['intent']),
                 'POSTCONDITION')
        body = {
            'kind': 'Assessment', 'principal': self.identifier,
            'assignment': assignment, 'source': cid('Envelope', envelope),
            'mission': cid('Mission', mission),
            'guarantees': cid('Guarantees', guarantees),
            'outcome': outcome,
            'violations': violations(outcome, program, guarantees),
        }
        tag = hmac.new(self._key, canonical(body), hashlib.sha256).hexdigest()
        return {'assessment': body, 'tag': tag}

    def verify(self, witness):
        fields(witness, ('assessment', 'tag'))
        expected = hmac.new(self._key, canonical(witness['assessment']),
                            hashlib.sha256).hexdigest()
        need(type(witness['tag']) is str
             and hmac.compare_digest(expected, witness['tag']), 'AUTHORITY')
        need(witness['assessment']['principal']
             == self.identifier, 'AUTHORITY')
        return deepcopy(witness['assessment'])
