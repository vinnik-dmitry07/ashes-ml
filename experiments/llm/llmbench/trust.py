'''Versioned evidence and a durable, owner-authorized trust projection.'''

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import hmac
from pathlib import Path
import threading
import sys

from ahsl.codec import (
    Rejected, canonical, cid, decode, fields, integer, need, ref,
)
from ahsl.environment import ENVIRONMENT, audit_trace
from ahsl.proofs import certify
from .protocol import Journal, digest, read_journal


PROFILES = ('F2_PROOF_1', 'G12_TRACE_1', 'EVIDENCE_BUNDLE_1')
PURPOSES = ('retrieval', 'training', 'publish')
MAX_PAYLOAD = 262144
MAX_DEPTH = 64
MAX_MEMBERS = 64


def packed(value):
    data = canonical(value)
    need(len(data) <= MAX_PAYLOAD, 'LIMIT')
    return data.hex()


def unpacked(value):
    need(type(value) is str and len(value) <= 2 * MAX_PAYLOAD, 'LIMIT')
    try:
        return decode(bytes.fromhex(value))
    except ValueError:
        raise Rejected('ENCODING') from None


def checker_definition(profile, parameters, manifest):
    need(profile in PROFILES, 'SCHEMA')
    if profile == 'F2_PROOF_1':
        fields(parameters, ('fuel',))
        integer(parameters['fuel'], 1, 100000)
    elif profile == 'G12_TRACE_1':
        fields(parameters, ('max_steps', 'require_goal'))
        integer(parameters['max_steps'], 1, 64)
        need(type(parameters['require_goal']) is bool)
    else:
        fields(parameters, ())
    return {'profile': profile, 'parameters': deepcopy(parameters),
            'source_manifest': manifest, 'protocol': 'BOUND_EVIDENCE_1',
            'python': {'implementation': sys.implementation.name,
                       'version': list(sys.version_info[:3])}}


class EvidenceLedger:
    '''The host owns this object; agents receive JSON, never owner handles.'''

    def __init__(self, path, key, manifest, max_checks=256, max_events=2048,
                 max_bytes=16000000):
        from .experiment import check_sources
        need(type(key) is bytes and len(key) >= 32, 'AUTHORITY')
        need(manifest == check_sources(), 'INTEGRITY')
        integer(max_checks, 1, 10000)
        integer(max_events, 1, 100000)
        integer(max_bytes, 1024, 1000000000)
        self._key = key
        self._owner = object()
        self._lock = threading.RLock()
        self._fenced = False
        self._identity = {
            'kind': 'TrustLedger', 'source_manifest': manifest,
            'owner': hashlib.sha256(key).hexdigest(),
            'max_checks': max_checks, 'max_events': max_events,
            'max_bytes': max_bytes,
        }
        self._state = self._empty()
        self._bytes = 0
        self._journal = Journal(path, self._identity)

    @staticmethod
    def _empty():
        return {'checkers': {}, 'checker_status': {}, 'receipts': {},
                'receipt_status': {}, 'pending': {}, 'checks': 0,
                'artifact_barriers': {}}

    @property
    def owner_handle(self):
        return self._owner

    @property
    def identity(self):
        return deepcopy(self._identity)

    @property
    def head(self):
        return self._journal.head

    def close(self):
        self._journal.close()

    def _owner_only(self, handle):
        need(handle is self._owner, 'AUTHORITY')

    def _sign(self, value):
        signature = hmac.new(self._key, canonical(value), hashlib.sha256)
        return signature.hexdigest()

    def _closure(self, state, roots):
        pending = list(roots)
        found = set()
        while pending:
            current = pending.pop()
            need(current in state['receipts'], 'REFERENCE')
            if current in found:
                continue
            found.add(current)
            need(len(found) <= 2048, 'LIMIT')
            pending.extend(state['receipts'][current]['dependencies'])
        return sorted(found)

    def _eligible(self, state, roots):
        closure = self._closure(state, roots)
        blocked = []
        for identifier in closure:
            receipt = state['receipts'][identifier]
            if (state['receipt_status'][identifier] != 'ACTIVE'
                    or state['checker_status'][receipt['checker']] != 'ACTIVE'
                    or receipt['check_sequence'] < state[
                        'artifact_barriers'].get(
                            receipt['artifact'], -1)):
                blocked.append(identifier)
        return closure, blocked

    def status(self, identifier):
        with self._lock:
            if self._fenced:
                return {'status': 'UNAVAILABLE', 'blocked_by': []}
            _, blocked = self._eligible(self._state, [identifier])
            own = self._state['receipt_status'][identifier]
            status = own if own != 'ACTIVE' else (
                'BLOCKED' if blocked else 'ACTIVE')
            return {'status': status, 'blocked_by': blocked}

    def register(self, handle, profile, parameters):
        with self._lock:
            self._owner_only(handle)
            definition = checker_definition(
                profile, parameters, self._identity['source_manifest'])
            return self._commit({'op': 'REGISTER', 'definition': definition})

    def change_trust(self, handle, target, identifier, status, reason):
        with self._lock:
            self._owner_only(handle)
            return self._commit({'op': 'TRUST', 'target': target,
                                 'id': identifier, 'status': status,
                                 'reason': deepcopy(reason)})

    def _request(self, checker, artifact, claim, context, supersedes):
        need(checker in self._state['checkers'], 'REFERENCE')
        need(self._state['checker_status'][checker] == 'ACTIVE', 'STALE')
        request = {'checker': checker, 'artifact_hex': packed(artifact),
                   'claim_hex': packed(claim), 'context_hex': packed(context),
                   'supersedes': supersedes}
        artifact_id = digest('EvidenceArtifact', request['artifact_hex'])
        need(artifact_id not in self._state['artifact_barriers']
             or supersedes is not None, 'STALE')
        if supersedes is not None:
            need(supersedes in self._state['receipts'], 'REFERENCE')
            old = self._state['receipts'][supersedes]
            for key in ('artifact_hex', 'claim_hex', 'context_hex'):
                need(request[key] == old[key], 'INTEGRITY')
        return request

    def submit(self, checker, artifact, claim, context):
        return self._submit(checker, artifact, claim, context, None)

    def _submit(self, checker, artifact, claim, context, supersedes):
        with self._lock:
            request = self._request(checker, artifact, claim, context,
                                    supersedes)
            sequence = self._commit({'op': 'START', 'request': request})
            return self._commit({'op': 'FINISH', 'check': sequence})

    def revalidate(self, handle, identifier, checker):
        with self._lock:
            self._owner_only(handle)
            need(identifier in self._state['receipts'], 'REFERENCE')
            old = self._state['receipts'][identifier]
            return self._submit(checker, unpacked(old['artifact_hex']),
                                unpacked(old['claim_hex']),
                                unpacked(old['context_hex']), identifier)

    def resolve_pending(self, handle, sequence):
        with self._lock:
            self._owner_only(handle)
            # These checkers are pure. Rechecking has no external API effect.
            return self._commit({'op': 'FINISH', 'check': sequence})

    def bundle(self, checker, members):
        need(type(members) is list and members, 'SCHEMA')
        for member in members:
            ref(member)
        members = sorted(set(members))
        need(members and len(members) <= MAX_MEMBERS, 'LIMIT')
        with self._lock:
            need(all(key in self._state['receipts'] for key in members),
                 'REFERENCE')
            scopes = {self._state['receipts'][key]['scope']
                      for key in members}
            need(len(scopes) == 1, 'TYPE')
            artifact = {'members': members}
            claim = {'kind': 'EvidenceBundle', 'members': members}
            return self.submit(checker, artifact, claim,
                               {'member_scope': scopes.pop()})

    def _evaluate(self, state, request):
        definition = state['checkers'][request['checker']]
        need(state['checker_status'][request['checker']] == 'ACTIVE', 'STALE')
        artifact = unpacked(request['artifact_hex'])
        context = unpacked(request['context_hex'])
        expected = unpacked(request['claim_hex'])
        profile = definition['profile']
        parameters = definition['parameters']
        dependencies = []
        if profile == 'F2_PROOF_1':
            fields(artifact, ('goal', 'term', 'library'))
            fields(context, ('library',))
            library_id = cid('ProofLibrary', artifact['library'])
            need(context['library'] == library_id,
                 'INTEGRITY')
            certificate = certify(artifact['goal'], artifact['term'],
                                  artifact['library'], parameters['fuel'])
            claim = {'kind': 'Proposition',
                     'goal': digest('Formula', certificate['goal'])}
            scope = digest('EvidenceContext', context)
        elif profile == 'G12_TRACE_1':
            fields(context, ('environment',))
            need(context['environment'] == ENVIRONMENT, 'STALE')
            outcome = audit_trace(artifact)
            need(outcome['steps'] <= parameters['max_steps'], 'POSTCONDITION')
            need(not parameters['require_goal'] or outcome['ground_success'],
                 'POSTCONDITION')
            claim = {'kind': 'TraceConsistency', 'trace': outcome['trace'],
                     'ground_success': outcome['ground_success']}
            scope = ENVIRONMENT
        else:
            fields(artifact, ('members',))
            fields(context, ('member_scope',))
            members = artifact['members']
            need(type(members) is list and 0 < len(members) <= MAX_MEMBERS)
            need(all(type(key) is str for key in members))
            need(members == sorted(set(members)))
            _, blocked = self._eligible(state, members)
            need(not blocked, 'STALE')
            need(all(state['receipts'][key]['scope'] == context['member_scope']
                     for key in members), 'TYPE')
            dependencies = members
            claim = {'kind': 'EvidenceBundle', 'members': members}
            scope = context['member_scope']
        need(canonical(expected) == canonical(claim), 'TYPE')
        depth = 1 + max((state['receipts'][key]['depth']
                         for key in dependencies), default=0)
        need(depth <= MAX_DEPTH, 'LIMIT')
        return {'claim': claim, 'scope': scope, 'depth': depth,
                'dependencies': dependencies}

    def _reduce(self, state, event, index):
        op = event['op']
        if op == 'REGISTER':
            fields(event, ('op', 'definition'))
            definition = event['definition']
            expected = checker_definition(
                definition['profile'], definition['parameters'],
                self._identity['source_manifest'])
            need(definition == expected, 'INTEGRITY')
            identifier = digest('Checker', definition)
            need(identifier not in state['checkers'], 'DUPLICATE')
            state['checkers'][identifier] = deepcopy(definition)
            state['checker_status'][identifier] = 'ACTIVE'
            return identifier
        if op == 'TRUST':
            fields(event, ('op', 'target', 'id', 'status', 'reason'))
            need(event['target'] in ('checker', 'receipt'))
            need(event['status'] in ('QUARANTINED', 'REVOKED'))
            fields(event['reason'], ('code', 'evidence'))
            need(type(event['reason']['code']) is str
                 and 0 < len(event['reason']['code']) <= 120)
            evidence = event['reason']['evidence']
            need(type(evidence) is list and len(evidence) <= 64)
            need(all(key in state['receipts']
                 for key in evidence), 'REFERENCE')
            mapping = state[event['target'] + '_status']
            need(event['id'] in mapping, 'REFERENCE')
            old = mapping[event['id']]
            need(old != 'REVOKED' and old != event['status'], 'PHASE')
            mapping[event['id']] = event['status']
            if event['target'] == 'receipt':
                artifact = state['receipts'][event['id']]['artifact']
                state['artifact_barriers'][artifact] = index
            return {'target': event['id'], 'status': event['status']}
        if op == 'START':
            fields(event, ('op', 'request'))
            need(state['checks'] < self._identity['max_checks'], 'BUDGET')
            request = event['request']
            fields(request, ('checker', 'artifact_hex', 'claim_hex',
                             'context_hex', 'supersedes'))
            need(request['checker'] in state['checkers'], 'REFERENCE')
            need(state['checker_status'][request['checker']] == 'ACTIVE',
                 'STALE')
            for key in ('artifact_hex', 'claim_hex', 'context_hex'):
                unpacked(request[key])
            previous = request['supersedes']
            artifact = digest('EvidenceArtifact', request['artifact_hex'])
            need(artifact not in state['artifact_barriers']
                 or previous is not None, 'STALE')
            if previous is not None:
                need(previous in state['receipts'], 'REFERENCE')
                need(all(request[key] == state['receipts'][previous][key]
                         for key in ('artifact_hex', 'claim_hex',
                                     'context_hex')), 'INTEGRITY')
            state['pending'][str(index)] = deepcopy(request)
            state['checks'] += 1
            return index
        fields(event, ('op', 'check'))
        need(op == 'FINISH')
        key = str(integer(event['check'], 0))
        need(key in state['pending'], 'REFERENCE')
        request = state['pending'].pop(key)
        try:
            measured = self._evaluate(state, request)
        except Rejected as error:
            code = str(error)
            return {'status': 'INCOMPLETE' if code == 'FUEL' else 'REJECTED',
                    'code': code, 'receipt': None}
        except (KeyError, TypeError, ValueError, IndexError, RecursionError):
            return {'status': 'REJECTED', 'code': 'SCHEMA', 'receipt': None}
        receipt = {
            'kind': 'EvidenceReceipt', 'checker': request['checker'],
            'artifact': digest('EvidenceArtifact', request['artifact_hex']),
            'context': digest('EvidenceContext', request['context_hex']),
            'claim': measured['claim'], 'scope': measured['scope'],
            'dependencies': measured['dependencies'],
            'depth': measured['depth'],
            'supersedes': request['supersedes'],
            'check_sequence': event['check'],
            'artifact_hex': request['artifact_hex'],
            'claim_hex': request['claim_hex'],
            'context_hex': request['context_hex'],
        }
        identifier = digest('EvidenceReceipt', receipt)
        state['receipts'][identifier] = receipt
        state['receipt_status'][identifier] = 'ACTIVE'
        return {'status': 'CHECKED', 'code': 'OK', 'receipt': identifier}

    def _commit(self, event):
        need(not self._fenced, 'PHASE')
        need(self._journal.index < self._identity['max_events'], 'BUDGET')
        canonical(event)
        state = deepcopy(self._state)
        index = self._journal.index
        result = self._reduce(state, event, index)
        # Every published projection must remain a valid replay snapshot.
        canonical(state)
        body = {'sequence': index, 'previous': self.head,
                'event': deepcopy(event), 'result': result}
        record = {'body': body, 'signature': self._sign(body)}
        # Reserve outer-record bytes before appending or publishing.
        size = len(canonical({'index': index, 'kind': 'trust',
                              'value': record, 'previous': self.head})) + 1
        pending = len(state['pending'])
        need(index + 1 + pending <= self._identity['max_events'],
             'BUDGET')
        need(self._bytes + size + 2048 * pending
             <= self._identity['max_bytes'], 'BUDGET')
        try:
            self._journal.append('trust', record)
        except OSError:
            self._fenced = True
            raise
        self._state = state
        self._bytes += size
        return deepcopy(result)

    def receipt(self, identifier):
        with self._lock:
            need(identifier in self._state['receipts'], 'REFERENCE')
            return deepcopy(self._state['receipts'][identifier])

    def select(self, identifiers, scope):
        with self._lock:
            need(not self._fenced, 'PHASE')
            result = []
            for identifier in sorted(set(identifiers)):
                need(identifier in self._state['receipts'], 'REFERENCE')
                receipt = self._state['receipts'][identifier]
                if receipt['scope'] == scope and not self._eligible(
                        self._state, [identifier])[1]:
                    result.append({'receipt': identifier,
                                   'checker': receipt['checker'],
                                   'claim': deepcopy(receipt['claim'])})
            return result

    def authorize(self, identifiers, scope, purpose):
        with self._lock:
            need(not self._fenced, 'PHASE')
            need(purpose in PURPOSES)
            ref(scope)
            need(type(identifiers) in (list, tuple, set))
            for identifier in identifiers:
                ref(identifier)
            roots = sorted(set(identifiers))
            need(roots and len(roots) <= MAX_MEMBERS, 'LIMIT')
            closure, blocked = self._eligible(self._state, roots)
            need(not blocked, 'STALE')
            need(all(self._state['receipts'][key]['scope'] == scope
                     for key in closure), 'TYPE')
            leaves = [key for key in closure
                      if not self._state['receipts'][key]['dependencies']]
            if purpose == 'training':
                need(all(self._state['receipts'][key]['claim']['kind']
                         == 'Proposition' or self._state['receipts'][key][
                             'claim'].get('ground_success') is True
                         for key in leaves), 'INELIGIBLE')
            body = {'roots': roots, 'scope': scope, 'purpose': purpose,
                    'leaves': leaves, 'issued_head': self.head,
                    'projection': digest('TrustProjection', {
                        key: self._state['receipts'][key]['checker']
                        for key in closure})}
            return {'body': body, 'signature': self._sign(body)}

    def validate_authorization(self, authorization, purpose):
        with self._lock:
            fields(authorization, ('body', 'signature'))
            body = authorization['body']
            need(type(authorization['signature']) is str and
                 hmac.compare_digest(authorization['signature'],
                                     self._sign(body)), 'AUTHORITY')
            need(body['purpose'] == purpose, 'AUTHORITY')
            current = self.authorize(body['roots'], body['scope'], purpose)
            old = {key: value for key, value in body.items()
                   if key != 'issued_head'}
            new = {key: value for key, value in current['body'].items()
                   if key != 'issued_head'}
            need(old == new, 'STALE')
            return deepcopy(body['leaves'])

    @contextmanager
    def guard(self, authorization, purpose):
        '''Hold the trust lock through a trusted local commit.'''
        with self._lock:
            yield self.validate_authorization(authorization, purpose)

    @classmethod
    def replay(cls, path, key, identity, expected_head):
        from .experiment import check_sources
        need(identity['source_manifest'] == check_sources(), 'INTEGRITY')
        need(identity['owner'] == hashlib.sha256(key).hexdigest(), 'AUTHORITY')
        records = read_journal(path, identity, expected_head)
        instance = object.__new__(cls)
        instance._key = key
        instance._identity = deepcopy(identity)
        state = cls._empty()
        need(len(records) <= identity['max_events'], 'BUDGET')
        need(Path(path).stat().st_size <= identity['max_bytes'], 'BUDGET')
        for index, row in enumerate(records):
            need(row['kind'] == 'trust', 'SCHEMA')
            fields(row['value'], ('body', 'signature'))
            body = row['value']['body']
            fields(body, ('sequence', 'previous', 'event', 'result'))
            need(body['sequence'] == index and body['previous']
                 == row['previous'], 'INTEGRITY')
            need(hmac.compare_digest(row['value']['signature'],
                                     instance._sign(body)), 'AUTHORITY')
            result = instance._reduce(state, body['event'], index)
            canonical(state)
            need(canonical(result) == canonical(body['result']), 'INTEGRITY')
        return {'head': expected_head, 'events': len(records),
                'state': state, 'state_digest': digest('TrustState', state)}
