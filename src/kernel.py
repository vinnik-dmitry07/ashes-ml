'''
K12: deterministic ledger; authority is supplied by the trusted
transport.
'''

from copy import deepcopy

from .codec import canonical, cid, fields, integer, name, need, ref


def invariant(state):
    fields(state, ('total', 'free', 'spent', 'jobs', 'active', 'generation',
                   'open_runs', 'sequence'))
    for field in ('total', 'free', 'spent', 'generation', 'open_runs',
                  'sequence'):
        integer(state[field], 0)
    ref(state['active'])
    need(type(state['jobs']) is dict)
    reserved = 0
    for key, job in state['jobs'].items():
        name(key)
        fields(job, ('upper', 'charge', 'phase', 'fence', 'receipt'))
        integer(job['upper'], 1)
        integer(job['charge'], 0, job['upper'])
        need(job['phase'] in ('RESERVED', 'RUNNING', 'UNKNOWN', 'DONE',
                              'SEALED', 'CANCELLED'))
        need(type(job['fence']) is bool)
        need(job['receipt'] is None or type(job['receipt']) is str)
        live = job['phase'] in ('RESERVED', 'RUNNING', 'UNKNOWN')
        if live:
            need(job['charge'] == 0 and job['receipt'] is None, 'INTEGRITY')
            reserved += job['upper']
        if job['phase'] in ('SEALED', 'CANCELLED'):
            need(job['fence'], 'INTEGRITY')
        if job['phase'] == 'SEALED':
            need(job['charge'] == job['upper'], 'INTEGRITY')
        if job['phase'] == 'DONE':
            ref(job['receipt'])
    need(state['total'] == state['free'] + state['spent'] + reserved,
         'INTEGRITY')
    need(state['spent'] == sum(job['charge']
         for job in state['jobs'].values()), 'INTEGRITY')
    return True


def initial(total, active):
    integer(total, 1)
    ref(active)
    state = {'total': total, 'free': total, 'spent': 0, 'jobs': {},
             'active': active, 'generation': 0, 'open_runs': 0, 'sequence': 0}
    invariant(state)
    return state


ROLES = {
    'reserve': 'agent', 'start_run': 'agent', 'close_run': 'agent',
    'dispatch': 'executor', 'unknown': 'executor', 'complete': 'executor',
    'fence': 'executor', 'cancel': 'supervisor', 'seal': 'supervisor',
    'publish': 'admitter', 'rollback': 'supervisor',
}


def step(state, principal, event):
    invariant(state)
    canonical(event)
    need(type(event) is dict and type(event.get('op')) is str)
    op = event['op']
    need(op in ROLES)
    need(principal == ROLES[op], 'AUTHORITY')
    new = deepcopy(state)
    if op == 'reserve':
        fields(event, ('op', 'job', 'upper'))
        key = name(event['job'])
        upper = integer(event['upper'], 1)
        need(key not in new['jobs'], 'DUPLICATE')
        need(len(new['jobs']) < 4096, 'LIMIT')
        need(new['free'] >= upper, 'BUDGET')
        new['free'] -= upper
        new['jobs'][key] = {'upper': upper, 'charge': 0, 'phase': 'RESERVED',
                            'fence': False, 'receipt': None}
    elif op in ('start_run', 'close_run'):
        fields(event, ('op',))
        if op == 'start_run':
            new['open_runs'] += 1
        else:
            need(new['open_runs'] > 0, 'PHASE')
            need(all(job['phase'] in ('DONE', 'SEALED', 'CANCELLED')
                     for job in new['jobs'].values()), 'PHASE')
            new['open_runs'] -= 1
    elif op in ('publish', 'rollback'):
        fields(event, ('op', 'candidate', 'generation'))
        ref(event['candidate'])
        integer(event['generation'], 0)
        need(event['generation'] == new['generation'], 'STALE')
        need(new['open_runs'] == 0, 'PHASE')
        need(all(job['phase'] in ('DONE', 'SEALED', 'CANCELLED')
                 for job in new['jobs'].values()), 'PHASE')
        new['active'] = event['candidate']
        new['generation'] += 1
    else:
        names = ('op', 'job', 'actual', 'receipt') if op == 'complete' else (
            'op', 'job')
        fields(event, names)
        key = name(event['job'])
        need(key in new['jobs'], 'REFERENCE')
        job = new['jobs'][key]
        phase = job['phase']
        if op == 'dispatch':
            need(phase == 'RESERVED' and not job['fence'], 'PHASE')
            job['phase'] = 'RUNNING'
        elif op == 'unknown':
            need(phase == 'RUNNING', 'PHASE')
            job['phase'] = 'UNKNOWN'
        elif op == 'fence':
            need(phase in ('RUNNING', 'UNKNOWN', 'RESERVED'), 'PHASE')
            job['fence'] = True
        elif op == 'cancel':
            need(phase == 'RESERVED', 'PHASE')
            job['phase'] = 'CANCELLED'
            job['fence'] = True
            new['free'] += job['upper']
        elif op == 'seal':
            need(phase in ('RUNNING', 'UNKNOWN') and job['fence'], 'PHASE')
            job['phase'] = 'SEALED'
            job['charge'] = job['upper']
            new['spent'] += job['upper']
        elif op == 'complete':
            actual = integer(event['actual'], 0, job['upper'])
            receipt = ref(event['receipt'])
            if phase == 'SEALED':
                return deepcopy(state), {'code': 'LATE', 'receipt': None}
            if phase == 'DONE':
                need(job['receipt'] == receipt and job['charge'] == actual,
                     'CONFLICT')
                return deepcopy(state), {'code': 'REPEAT', 'receipt': receipt}
            need(phase in ('RUNNING', 'UNKNOWN'), 'PHASE')
            job['phase'] = 'DONE'
            job['charge'] = actual
            job['receipt'] = receipt
            new['spent'] += actual
            new['free'] += job['upper'] - actual
    new['sequence'] += 1
    invariant(new)
    return new, {'code': 'OK', 'receipt': None}


def replay(initial_state, log, expected_head):
    '''The expected head must come from a trusted store, not this snapshot.'''
    state = deepcopy(initial_state)
    head = cid('Genesis', state)
    for record in log:
        fields(record, ('principal', 'event', 'before', 'after', 'previous'))
        need(record['previous'] == head, 'INTEGRITY')
        need(record['before'] == cid('State', state), 'INTEGRITY')
        state, _ = step(state, record['principal'], record['event'])
        need(record['after'] == cid('State', state), 'INTEGRITY')
        head = cid('LogRecord', record)
    need(head == expected_head, 'INTEGRITY')
    return state


class Ledger:
    '''Trusted owner. Its mutable Python fields are not agent capabilities.'''

    def __init__(self, total, active):
        self.genesis = initial(total, active)
        self.state = deepcopy(self.genesis)
        self.log = []
        self.head = cid('Genesis', self.genesis)

    def apply(self, principal, event):
        new, output = step(self.state, principal, event)
        record = {
            'principal': principal, 'event': deepcopy(event), 'before': cid(
                'State', self.state), 'after': cid(
                'State', new), 'previous': self.head}
        self.log.append(record)
        self.head = cid('LogRecord', record)
        self.state = new
        return output

    def restore(self, snapshot, log):
        restored = replay(self.genesis, log, self.head)
        need(canonical(snapshot) == canonical(restored), 'INTEGRITY')
        self.state = restored
        self.log = deepcopy(log)
        return True
