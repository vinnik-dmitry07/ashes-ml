'''Executable root mission and inherited finite-profile guarantees.'''

from copy import deepcopy

from .codec import canonical, cid, fields, integer, need, ref
from .environment import ENVIRONMENT


DEFAULT_GUARANTEES = {
    'require_ground_goal': True,
    'max_actions': 64,
    'max_program_bytes': 65536,
}


def validate_guarantees(value):
    fields(value, DEFAULT_GUARANTEES)
    need(type(value['require_ground_goal']) is bool)
    integer(value['max_actions'], 1, 64)
    integer(value['max_program_bytes'], 1, 65536)
    return True


def refines(child, parent):
    '''Fixed input domain; child postconditions imply parent postconditions.'''
    validate_guarantees(child)
    validate_guarantees(parent)
    return ((not parent['require_ground_goal']
             or child['require_ground_goal'])
            and child['max_actions'] <= parent['max_actions']
            and child['max_program_bytes'] <= parent['max_program_bytes'])


def create_mission(manifest, levels, observer, evaluator):
    ref(manifest)
    ref(observer)
    ref(evaluator)
    need(observer != evaluator, 'AUTHORITY')
    need(type(levels) is list and levels and levels == sorted(set(levels)))
    for level in levels:
        integer(level, 1, 12)
    return {
        'kind': 'Mission', 'environment': ENVIRONMENT,
        'manifest': manifest, 'levels': deepcopy(levels),
        'absolute_success': 'ALL', 'floor': deepcopy(DEFAULT_GUARANTEES),
        'observer': observer, 'evaluator': evaluator,
    }


def violations(outcome, program, guarantees):
    validate_guarantees(guarantees)
    result = []
    if guarantees['require_ground_goal'] and not outcome['ground_success']:
        result.append('GROUND_GOAL')
    if outcome['steps'] > guarantees['max_actions']:
        result.append('ACTION_BOUND')
    if len(canonical(program)) > guarantees['max_program_bytes']:
        result.append('PROGRAM_BOUND')
    return result


def check_mission(mission, expected):
    need(cid('Mission', mission) == expected, 'INTEGRITY')
    return True
