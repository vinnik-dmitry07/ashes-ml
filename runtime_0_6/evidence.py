'''Exact, preregistered tests for paired binary experiment outcomes.'''

from fractions import Fraction
from math import comb

from kernel import core


def rational(value):
    core.fields(value, ('num', 'den'))
    core.nat(value['num'])
    core.nat(value['den'])
    core.require(0 < value['num'] < value['den'])
    return Fraction(value['num'], value['den'])


def encoded(value):
    return {'num': str(value.numerator), 'den': str(value.denominator)}


def gain_p(wins, losses):
    discordant = wins + losses
    return Fraction(
        sum(comb(discordant, k) for k in range(wins, discordant + 1)),
        2 ** discordant,
    )


def loss_p(n, losses, tolerance):
    return sum((
        comb(n, k) * tolerance ** k * (1 - tolerance) ** (n - k)
        for k in range(losses + 1)
    ), Fraction(0))


def validate_protocol(policy):
    rational(policy['alpha'])
    core.require(type(policy['strata']) is dict and policy['strata'])
    for name, spec in policy['strata'].items():
        core.identifier(name)
        core.fields(spec, ('n', 'regression', 'gain'))
        core.nat(spec['n'])
        core.require(0 < spec['n'] <= 512)
        rational(spec['regression'])
        core.require(type(spec['gain']) is bool)
    core.require(any(item['gain'] for item in policy['strata'].values()))


def validate_report(report):
    core.fields(report, ('strata', 'violations'))
    core.nat(report['violations'])
    core.require(type(report['strata']) is dict)
    for name, rows in report['strata'].items():
        core.identifier(name)
        core.require(type(rows) is list and len(rows) <= 512)
        for row in rows:
            core.fields(row, ('id', 'parent', 'candidate'))
            core.identifier(row['id'])
            core.require(type(row['parent']) is bool)
            core.require(type(row['candidate']) is bool)


def sample_ids(report):
    return [row['id'] for rows in report['strata'].values() for row in rows]


def assess(policy, trial_number, claim, report):
    '''Caller checks schema and fresh sample IDs before this function.'''
    strata = policy['strata']
    if set(report['strata']) != set(strata) or any(
        len(report['strata'][name]) != spec['n']
        for name, spec in strata.items()
    ):
        return {'accepted': False, 'code': 'PROTOCOL_MISMATCH', 'tests': {}}
    tests_count = len(strata)
    if claim == 'improve':
        tests_count += sum(spec['gain'] for spec in strata.values())
    threshold = rational(policy['alpha']) / (
        trial_number * (trial_number + 1) * tests_count
    )
    accepted = report['violations'] == 0
    results = {}
    for name, spec in sorted(strata.items()):
        rows = report['strata'][name]
        wins = sum(not row['parent'] and row['candidate'] for row in rows)
        losses = sum(row['parent'] and not row['candidate'] for row in rows)
        retention = loss_p(spec['n'], losses, rational(spec['regression']))
        gain = gain_p(wins, losses)
        passed = retention <= threshold
        if claim == 'improve' and spec['gain']:
            passed = passed and gain <= threshold
        accepted = accepted and passed
        results[name] = {
            'n': spec['n'], 'wins': wins, 'losses': losses,
            'loss_p': encoded(retention), 'gain_p': encoded(gain),
            'passed': passed,
        }
    return {
        'accepted': accepted, 'code': 'ACCEPT' if accepted else 'REJECT',
        'threshold': encoded(threshold), 'tests': results,
    }
