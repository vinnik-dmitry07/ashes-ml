'''Five small executable harness shapes, not performance reproductions.'''

from .environment import AGENT_PARAMS, INTENT_TYPE


def lit(value, tag):
    return {'op': 'lit', 'type': tag, 'value': value}


def var(key):
    return {'op': 'var', 'name': key}


def builtin(key, *args):
    return {'op': 'builtin', 'name': key, 'args': list(args)}


def call(key, *args):
    return {'op': 'call', 'name': key, 'args': list(args)}


def choose(test, yes, no):
    return {'op': 'if', 'test': test, 'yes': yes, 'no': no}


def function(params, result, body):
    return {'params': params, 'result': result, 'body': body}


def program(body, output, params=None):
    return {'entry': 'main', 'functions': {
        'main': function({} if params is None else params, output, body),
    }}


def observation(field):
    return {'op': 'get', 'record': var('observation'), 'field': field}


def action(value):
    return {'op': 'some', 'value': {'op': 'record', 'fields': {
        'action': value,
        'prediction': {'op': 'record', 'fields': {
            'position': observation('position'),
        }},
        'state': var('state'),
    }}}


def corridor_agent(style='solver'):
    if style == 'solver':
        next_pos = builtin('add', observation('position'), lit(1, 'Int'))
        unlocked = builtin('contains_int', observation('opened'), next_pos)
        choice = choose(
            builtin('lt', observation('position'), observation('level')),
            choose(unlocked, lit('right', 'Text'),
                   choose(observation('key'), lit('unlock', 'Text'),
                          lit('take', 'Text'))),
            lit('right', 'Text'))
        body = action(choice)
    else:
        body = choose(builtin('eq', var('index'), lit(0, 'Int')),
                      action(lit(style, 'Text')),
                      lit(None, {'Option': INTENT_TYPE}))
    return program(body, {'Option': INTENT_TYPE}, AGENT_PARAMS)


def council():
    body = builtin('borda', lit(['a', 'b', 'c'], {'List': 'Text'}),
                   lit([['b', 'a', 'c'], ['a', 'b', 'c'], ['b', 'c', 'a']],
                       {'List': {'List': 'Text'}}))
    result = program(call('aggregate'), 'Text')
    result['functions']['aggregate'] = function({}, 'Text', body)
    return result


def islands():
    return program(builtin('pareto', lit([[4, 1], [2, 3], [1, 1], [3, 2]],
                                         {'List': {'List': 'Int'}})),
                   {'List': 'Int'})


def recursive_context():
    body = choose(
        builtin('eq', builtin('length_int', var('chunks')), lit(0, 'Int')),
        lit(0, 'Int'),
        builtin('add', {'op': 'index', 'list': var('chunks'),
                        'index': lit(0, 'Int')},
                call('fold', builtin('tail_int', var('chunks')))))
    result = program(call('fold', lit([1, 2, 3, 4], {'List': 'Int'})), 'Int')
    result['functions']['fold'] = function({'chunks': {'List': 'Int'}},
                                           'Int', body)
    return result


def group_relative_controller():
    rewards = [{'num': 0, 'den': 1}, {'num': 1, 'den': 1},
               {'num': 1, 'den': 1}]
    return program(builtin('centered', lit(rewards, {'List': 'Rat'})),
                   {'List': 'Rat'})
