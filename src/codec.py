'''Closed protocol encoding, exact rationals and structured rejections.'''

from fractions import Fraction
import hashlib
import json
import re


MAX_INT = 2 ** 63 - 1
MAX_DEPTH = 32
MAX_NODES = 2000000
MAX_BYTES = 16000000
ERRORS = frozenset({
    'ENCODING', 'SCHEMA', 'LIMIT', 'TYPE', 'REFERENCE', 'AUTHORITY',
    'INTEGRITY', 'PHASE', 'BUDGET', 'DUPLICATE', 'STALE', 'CONFLICT',
    'FUEL', 'PRECONDITION', 'POSTCONDITION', 'UNKNOWN', 'INELIGIBLE',
})


class Rejected(Exception):
    '''A public, finite protocol error code.'''


def need(condition, code='SCHEMA'):
    if not condition:
        raise Rejected(code)


def fields(value, names):
    need(type(value) is dict and set(value) == set(names))


def integer(value, minimum=-MAX_INT, maximum=MAX_INT):
    need(type(value) is int and minimum <= value <= maximum)
    return value


def name(value):
    need(type(value) is str and re.fullmatch(
        r'[A-Za-z][A-Za-z0-9_]{0,63}', value))
    return value


def ref(value):
    need(type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value))
    return value


def validate(value):
    '''Root depth is one, including scalars; cycles and aliases are safe.'''
    count = 0
    ancestors = set()

    def visit(item, depth):
        nonlocal count
        count += 1
        need(count <= MAX_NODES and depth <= MAX_DEPTH, 'LIMIT')
        if item is None or type(item) is bool:
            return
        if type(item) is int:
            integer(item)
            return
        if type(item) is str:
            need(len(item) <= MAX_BYTES, 'LIMIT')
            need(all(32 <= ord(char) <= 126 for char in item), 'ENCODING')
            return
        need(type(item) in (dict, list))
        marker = id(item)
        need(marker not in ancestors, 'ENCODING')
        ancestors.add(marker)
        if type(item) is dict:
            for key, child in item.items():
                need(type(key) is str)
                need(all(32 <= ord(char) <= 126 for char in key), 'ENCODING')
                visit(child, depth + 1)
        else:
            for child in item:
                visit(child, depth + 1)
        ancestors.remove(marker)

    visit(value, 1)


def canonical(value):
    validate(value)
    data = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
        allow_nan=False,
    ).encode('ascii')
    need(len(data) <= MAX_BYTES, 'LIMIT')
    return data


def decode(data):
    need(type(data) is bytes and len(data) <= MAX_BYTES, 'LIMIT')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'ENCODING')
            result[key] = value
        return result

    try:
        value = json.loads(data, object_pairs_hook=unique)
        need(canonical(value) == data, 'ENCODING')
        return value
    except Rejected:
        raise
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise Rejected('ENCODING') from None


def cid(kind, value):
    name(kind)
    return hashlib.sha256(
        b'AHSL/1.5/' + kind.encode('ascii') + b'\x00' + canonical(value)
    ).hexdigest()


def rat(value):
    fields(value, ('num', 'den'))
    n = integer(value['num'])
    d = integer(value['den'], 1)
    result = Fraction(n, d)
    need(result.numerator == n and result.denominator == d)
    return result


def fraction(value):
    result = Fraction(value)
    integer(result.numerator)
    integer(result.denominator, 1)
    return {'num': result.numerator, 'den': result.denominator}


def attempt(function, *args, **kwargs):
    try:
        return {'code': 'OK', 'value': function(*args, **kwargs)}
    except Rejected as error:
        code = str(error)
        need(code in ERRORS, 'INTEGRITY')
        return {'code': code, 'value': None}
