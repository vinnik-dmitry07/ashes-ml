'''
Total bounded wire boundary. Administrative authority is not an input
field.
'''

from .codec import Rejected, canonical, decode, fields, need
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


def handle(session, request):
    '''Returns canonical Result bytes; no exception text is exposed.'''
    try:
        need(session.requests_used < 1024, 'BUDGET')
        session.requests_used += 1
        command = decode(request)
        op = command['op']
        if op == 'propose':
            fields(command, ('op', 'program'))
            value = session.prepare(command['program'], session.levels)
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
