'''Live trust consumers: retrieval, export, and behavior archives.'''

from copy import deepcopy
import os
from pathlib import Path

from ahsl.codec import canonical, fields, need
from ahsl.environment import ACTIONS, audit_trace
from .protocol import digest
from .trust import unpacked


def behavior_descriptor(trace):
    '''Measure behavior from checked transitions.'''
    outcome = audit_trace(trace)
    counts = {action: 0 for action in ACTIONS}
    backtracks = 0
    for row in trace['steps']:
        counts[row['intent']['action']] += 1
        backtracks += int(row['after']['position'] < row['before']['position'])
    values = {'ground_success': outcome['ground_success'],
              'steps': outcome['steps'], 'backtracks': backtracks,
              'action_counts': counts}
    cell = {'ground_success': outcome['ground_success'],
            'step_band': outcome['steps'] // 8,
            'backtracks': bool(backtracks), 'paint': bool(counts['paint'])}
    return {'profile': 'G12_BEHAVIOR_1', 'values': values, 'cell': cell,
            'cell_id': digest('BehaviorCell', cell)}


class TrustedMemory:
    def __init__(self, ledger):
        self.ledger = ledger
        self._members = set()

    def add(self, receipt):
        self.ledger.receipt(receipt)
        self._members.add(receipt)

    def read(self, scope):
        # Recompute trust on every read. No ASSUMPTION fallback for quarantine.
        return self.ledger.select(self._members, scope)

    def prepare(self, scope, purpose='retrieval'):
        identifiers = [row['receipt'] for row in self.read(scope)]
        return self.ledger.authorize(identifiers, scope, purpose)

    def consume(self, authorization, purpose='retrieval'):
        identifiers = self.ledger.validate_authorization(
            authorization, purpose)
        return self.ledger.select(identifiers, authorization['body']['scope'])

    def dataset(self, roots, scope):
        authorization = self.ledger.authorize(roots, scope, 'training')
        rows = []
        seen = set()
        for identifier in authorization['body']['leaves']:
            receipt = self.ledger.receipt(identifier)
            if receipt['artifact'] in seen:
                continue
            seen.add(receipt['artifact'])
            artifact = unpacked(receipt['artifact_hex'])
            if receipt['claim']['kind'] == 'TraceConsistency':
                sample = {
                    'kind': 'SYNTHETIC_VALIDATED_TRACE',
                    'level': artifact['level'],
                    'actions': [row['intent']['action']
                                for row in artifact['steps']],
                }
            else:
                need(receipt['claim']['kind'] == 'Proposition', 'TYPE')
                sample = {'kind': 'CHECKED_FORMULA', 'artifact_hex':
                          receipt['artifact_hex']}
            rows.append({'evidence': identifier, 'sample': sample})
        body = {'authorization': authorization, 'rows': rows}
        return {'id': digest('EvidenceDataset', body), 'body': body}

    def validate_dataset(self, dataset):
        fields(dataset, ('id', 'body'))
        body = dataset['body']
        fields(body, ('authorization', 'rows'))
        need(dataset['id'] == digest('EvidenceDataset', body), 'INTEGRITY')
        auth = body['authorization']
        self.ledger.validate_authorization(auth, 'training')
        expected = self.dataset(auth['body']['roots'], auth['body']['scope'])
        need(canonical(body['rows']) == canonical(expected['body']['rows']),
             'INTEGRITY')
        return deepcopy(body['rows'])

    def export_dataset(self, dataset, path):
        auth = dataset['body']['authorization']
        with self.ledger.guard(auth, 'training'):
            self.validate_dataset(dataset)
            data = canonical(dataset)
            with Path(path).open('xb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())


class BehaviorArchive:
    '''Archive coverage is conditional on this explicit G12 descriptor.'''

    def __init__(self, ledger):
        self.ledger = ledger
        self._members = set()

    def add(self, receipt):
        record = self.ledger.receipt(receipt)
        need(record['claim']['kind'] == 'TraceConsistency', 'TYPE')
        need(self.ledger.status(receipt)['status'] == 'ACTIVE', 'STALE')
        self._members.add(receipt)

    def cells(self):
        result = {}
        for identifier in sorted(self._members):
            if self.ledger.status(identifier)['status'] != 'ACTIVE':
                continue
            receipt = self.ledger.receipt(identifier)
            descriptor = behavior_descriptor(unpacked(receipt['artifact_hex']))
            result.setdefault(descriptor['cell_id'], {
                'cell': descriptor['cell'], 'members': [],
            })['members'].append(identifier)
        return result
