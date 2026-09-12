'''Closed structural types shared by language, components and contracts.'''

from src.codec import fields, integer, name, need, rat


SCALARS = ('Unit', 'Bool', 'Int', 'Text', 'Rat')


def type_ok(tag, depth=1):
    need(depth <= 16, 'LIMIT')
    if type(tag) is str:
        need(tag in SCALARS, 'TYPE')
        return
    need(type(tag) is dict and len(tag) == 1, 'TYPE')
    if 'List' in tag:
        type_ok(tag['List'], depth + 1)
    elif 'Option' in tag:
        type_ok(tag['Option'], depth + 1)
    else:
        fields(tag, ('Record',))
        need(type(tag['Record']) is dict and len(tag['Record']) <= 64)
        for key, child in tag['Record'].items():
            name(key)
            type_ok(child, depth + 1)


def value_ok(value, tag, depth=1):
    type_ok(tag)
    need(depth <= 32, 'LIMIT')
    if tag == 'Unit':
        need(value is None, 'TYPE')
    elif tag == 'Bool':
        need(type(value) is bool, 'TYPE')
    elif tag == 'Int':
        integer(value)
    elif tag == 'Text':
        need(type(value) is str, 'TYPE')
    elif tag == 'Rat':
        rat(value)
    elif 'List' in tag:
        need(type(value) is list and len(value) <= 4096, 'TYPE')
        for child in value:
            value_ok(child, tag['List'], depth + 1)
    elif 'Option' in tag:
        if value is not None:
            value_ok(value, tag['Option'], depth + 1)
    else:
        fields(value, tag['Record'])
        for key, child in value.items():
            value_ok(child, tag['Record'][key], depth + 1)


def signature(params, output):
    need(type(params) is dict and len(params) <= 64)
    for key, tag in params.items():
        name(key)
        type_ok(tag)
    type_ok(output)
