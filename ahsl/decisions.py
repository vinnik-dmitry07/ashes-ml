'''Deterministic aggregators and exact decision scores, callable by the VM.'''

from fractions import Fraction

from .codec import cid, fraction, integer, need, rat


def plurality(candidates, ballots):
    need(candidates and len(set(candidates)) == len(candidates))
    need(all(vote in candidates for vote in ballots))
    need(ballots, 'PRECONDITION')
    counts = {candidate: ballots.count(candidate) for candidate in candidates}
    return min(candidates, key=lambda item: (-counts[item], item))


def borda(candidates, ballots):
    need(candidates and len(set(candidates)) == len(candidates))
    need(ballots, 'PRECONDITION')
    need(all(len(vote) == len(candidates) and set(vote) == set(candidates)
             for vote in ballots))
    counts = {candidate: 0 for candidate in candidates}
    for vote in ballots:
        for index, candidate in enumerate(vote):
            counts[candidate] += len(candidates) - index - 1
    return min(candidates, key=lambda item: (-counts[item], item))


def pareto(points):
    '''All coordinates are maximized; return undominated input indices.'''
    need(points and points[0])
    need(all(len(point) == len(points[0]) for point in points))
    return [i for i, point in enumerate(points)
            if not any(all(a >= b for a, b in zip(other, point))
                       and any(a > b for a, b in zip(other, point))
                       for other in points)]


def distribution(values):
    probabilities = [rat(value) for value in values]
    need(probabilities and all(p >= 0 for p in probabilities))
    need(sum(probabilities) == 1, 'PRECONDITION')
    return probabilities


def expected(probabilities, utilities):
    probabilities = distribution(probabilities)
    need(len(probabilities) == len(utilities))
    return fraction(sum(p * rat(u) for p, u in zip(probabilities, utilities)))


def brier(probabilities, outcome):
    probabilities = distribution(probabilities)
    integer(outcome, 0, len(probabilities) - 1)
    return fraction(sum((p - int(i == outcome)) ** 2
                        for i, p in enumerate(probabilities)))


def regret(utilities, chosen):
    need(utilities)
    integer(chosen, 0, len(utilities) - 1)
    values = [rat(value) for value in utilities]
    return fraction(max(values) - values[chosen])


def centered(rewards):
    '''Exact mean-centered advantages; not a claim to implement full GRPO.'''
    need(rewards)
    values = [rat(value) for value in rewards]
    mean = sum(values) / len(values)
    return [fraction(value - mean) for value in values]


def lookup_text(table, key):
    need(len({row['key'] for row in table}) == len(table), 'PRECONDITION')
    return next((row['value'] for row in table if row['key'] == key), 'noop')


def observation_key(observation):
    from .admission import policy_key
    return policy_key(observation)


LIST_TEXT = {'List': 'Text'}
LIST_RAT = {'List': 'Rat'}
OPERATORS = {
    'plurality': ([LIST_TEXT, LIST_TEXT], 'Text', plurality),
    'borda': ([LIST_TEXT, {'List': LIST_TEXT}], 'Text', borda),
    'pareto': ([{'List': {'List': 'Int'}}], {'List': 'Int'}, pareto),
    'expected': ([LIST_RAT, LIST_RAT], 'Rat', expected),
    'brier': ([LIST_RAT, 'Int'], 'Rat', brier),
    'regret': ([LIST_RAT, 'Int'], 'Rat', regret),
    'centered': ([LIST_RAT], LIST_RAT, centered),
    'add': (['Int', 'Int'], 'Int', lambda a, b: integer(a + b)),
    'sub': (['Int', 'Int'], 'Int', lambda a, b: integer(a - b)),
    'eq': (['Int', 'Int'], 'Bool', lambda a, b: a == b),
    'lt': (['Int', 'Int'], 'Bool', lambda a, b: a < b),
    'contains_int': ([{'List': 'Int'}, 'Int'], 'Bool', lambda xs, x: x in xs),
    'length_int': ([{'List': 'Int'}], 'Int', len),
    'tail_int': ([{'List': 'Int'}], {'List': 'Int'}, lambda xs: xs[1:]),
    'lookup_text': ([{'List': {'Record': {'key': 'Text', 'value': 'Text'}}},
                     'Text'], 'Text', lookup_text),
    'observation_key': ([{'Record': {'position': 'Int', 'key': 'Bool',
                                     'opened': {'List': 'Int'},
                                     'visible_success': 'Bool',
                                     'level': 'Int'}}],
                        'Text', observation_key),
}
