'''Independent finite checks of Boolean semantics and graph closure.'''

from itertools import product

import prospection as p


def check_graphs():
    names = ('a', 'b', 'c')
    arcs = list(product(names, repeat=2))
    cases = 0
    for graph_mask in range(2 ** len(arcs)):
        edges = [arc for index, arc in enumerate(arcs)
                 if graph_mask & (1 << index)]
        sketches = {
            str(index): {'target': target, 'premises': [source]}
            for index, (source, target) in enumerate(edges)
        }
        for seed_mask in range(2 ** len(names)):
            seeds = {name for index, name in enumerate(names)
                     if seed_mask & (1 << index)}
            # Independent queue reachability for the unary-edge sub-profile.
            expected = set(seeds)
            queue = list(seeds)
            while queue:
                current = queue.pop()
                for source, target in edges:
                    if source == current and target not in expected:
                        expected.add(target)
                        queue.append(target)
            witnesses, ranks = p.close_graph(
                dict.fromkeys(names), sketches, dict.fromkeys(seeds, 'check'),
            )
            assert set(witnesses) == expected
            for target, witness in witnesses.items():
                if witness['kind'] == 'sketch':
                    for source in sketches[witness['ref']]['premises']:
                        assert ranks[source] < ranks[target]
            cases += 1
    return cases


def check_boolean_formulas():
    # Masks use assignments 00, 01, 10, 11; a is the low bit.
    formulas = [(['atom', 'a'], 0b1010), (['atom', 'b'], 0b1100),
                (['top'], 0b1111), (['bottom'], 0b0000)]
    cases = 0
    for left, left_mask in formulas:
        for right, right_mask in formulas:
            operations = {
                'and': left_mask & right_mask,
                'or': left_mask | right_mask,
                'implies': ((~left_mask) | right_mask) & 0b1111,
            }
            for operator, expected_mask in operations.items():
                formula = [operator, left, right]
                actual_mask = 0
                for bits in range(4):
                    assignment = {'a': bool(bits & 1), 'b': bool(bits & 2)}
                    actual_mask |= int(p.evaluate(formula, assignment)) << bits
                assert actual_mask == expected_mask
                cases += 1
    return cases


if __name__ == '__main__':
    print({
        'graph_cases': check_graphs(),
        'formula_cases': check_boolean_formulas(),
    })
