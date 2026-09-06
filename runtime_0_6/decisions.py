'''Deterministic library algorithms, with no authority to publish releases.'''

from kernel import core


def plurality(candidates, ballots, quorum):
    core.names(candidates)
    core.require(bool(candidates) and type(ballots) is dict)
    core.nat(quorum)
    scores = dict.fromkeys(candidates, 0)
    for voter, choice in ballots.items():
        core.identifier(voter)
        core.require(choice is None or (type(choice) is str and choice in scores))
        if choice is not None:
            scores[choice] += 1
    if sum(scores.values()) < quorum or sum(scores.values()) == 0:
        return {'winner': None, 'scores': scores, 'code': 'NO_QUORUM'}
    winner = min(scores, key=lambda name: (-scores[name], name))
    return {'winner': winner, 'scores': scores, 'code': 'OK'}


def borda(candidates, ballots, quorum):
    core.names(candidates)
    core.require(bool(candidates) and type(ballots) is dict)
    core.nat(quorum)
    scores = dict.fromkeys(candidates, 0)
    valid = 0
    for voter, ranking in ballots.items():
        core.identifier(voter)
        if ranking is None:
            continue
        core.names(ranking)
        core.require(set(ranking) == set(candidates))
        valid += 1
        for rank, name in enumerate(ranking):
            scores[name] += len(candidates) - rank - 1
    if valid < quorum or valid == 0:
        return {'winner': None, 'scores': scores, 'code': 'NO_QUORUM'}
    winner = min(scores, key=lambda name: (-scores[name], name))
    return {'winner': winner, 'scores': scores, 'code': 'OK'}


def pareto(points, directions):
    core.require(type(points) is dict and type(directions) is list and directions)
    core.require(all(item in ('min', 'max') for item in directions))
    for name, point in points.items():
        core.identifier(name)
        core.require(type(point) is list and len(point) == len(directions))
        for value in point:
            core.nat(value)

    def dominates(left, right):
        weak = all(
            a <= b if direction == 'min' else a >= b
            for a, b, direction in zip(left, right, directions)
        )
        strict = any(a != b for a, b in zip(left, right))
        return weak and strict

    return sorted(
        name for name, point in points.items()
        if not any(dominates(other, point) for other in points.values())
    )
