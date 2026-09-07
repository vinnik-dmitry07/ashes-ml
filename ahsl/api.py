'''
Total bounded wire boundary. Administrative authority is not an input
field.
'''

from .codec import Rejected, canonical, cid, decode, fields, need
from .language import execute
from .proofs import certify


def initialize(request, key):
    '''Trusted bootstrap: return (owner or None, canonical Result bytes).'''
    from .admission import Session
    try:
        config = decode(request)
        fields(config, ('baseline', 'total', 'manifest', 'levels'))
        owner = Session(config['baseline'], config['total'], key,
                        config['manifest'], config['levels'])
        return owner, canonical({'code': 'OK', 'value': owner.ledger.state})
    except Rejected as error:
        return None, canonical({'code': str(error), 'value': None})
    except (KeyError, TypeError, ValueError, IndexError, OverflowError,
            RecursionError):
        return None, canonical({'code': 'SCHEMA', 'value': None})


def _dispatch(session, request):
    '''Dispatch an admitted bounded request without exposing exception text.'''
    try:
        command = decode(request)
        op = command['op']
        if op == 'propose':
            fields(command, ('op', 'program'))
            value = session.prepare(command['program'], session.levels)
        elif op == 'propose_contracted':
            fields(command, ('op', 'program', 'guarantees', 'mode'))
            value = session.prepare(command['program'], session.levels,
                                    command['guarantees'], command['mode'])
        elif op == 'evaluate':
            fields(command, ('op', 'plan'))
            envelopes = session.evaluate(command['plan'])
            value = [item['receipt']['trace']['assignment']
                     for item in envelopes]
        elif op == 'read_receipt':
            fields(command, ('op', 'assignment'))
            value = session.runner.receipts[command['assignment']]
        elif op == 'admit':
            fields(command, ('op', 'plan', 'assignments'))
            envelopes = [session.runner.receipts[item]
                         for item in command['assignments']]
            value = session.admit(command['plan'], envelopes)
        elif op == 'train':
            fields(command, ('op', 'envelope'))
            value = session.admit_training(command['envelope'])
        elif op == 'condense':
            fields(command, ('op', 'assignments'))
            value = session.condense(command['assignments'])
        elif op == 'check_proof':
            fields(command, ('op', 'goal', 'term', 'library'))
            value = certify(
                command['goal'],
                command['term'],
                command['library'])
        elif op == 'run_pure':
            fields(command, ('op', 'program', 'arguments', 'fuel'))
            value = execute(command['program'], command['arguments'],
                            command['fuel'])
        else:
            raise Rejected('SCHEMA')
        return canonical({'code': 'OK', 'value': value})
    except Rejected as error:
        return canonical({'code': str(error), 'value': None})
    except (KeyError, TypeError, ValueError, IndexError, OverflowError,
            RecursionError):
        return canonical({'code': 'SCHEMA', 'value': None})


def handle(session, request):
    '''Bounded full-request audit; rejects do not consume trial evidence.'''
    try:
        need(type(request) is bytes, 'SCHEMA')
        need(len(request) <= 131072, 'LIMIT')
        need(session.requests_used < 1024, 'BUDGET')
        need(session.request_log_bytes + 2 * len(request) + 1024 <= 2000000,
             'BUDGET')
    except Rejected as error:
        return canonical({'code': str(error), 'value': None})
    session.requests_used += 1
    before = session.ledger.head
    result = _dispatch(session, request)
    record = {
        'index': len(session.request_log), 'request_hex': request.hex(),
        'before': before, 'after': session.ledger.head,
        'result': cid('WireResult', decode(result)),
        'code': decode(result)['code'], 'previous': session.request_log_head,
    }
    encoded = canonical(record)
    session.request_log_bytes += len(encoded)
    session.request_log.append(record)
    session.request_log_head = cid('RequestRecord', record)
    return result
