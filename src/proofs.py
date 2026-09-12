'''F2: intuitionistic propositional proof checking, separate bounded search.'''

from copy import deepcopy

from .codec import canonical, cid, fields, integer, name, need


def formula(value, depth=1):
    need(depth <= 32, 'LIMIT')
    need(type(value) is list and value)
    op = value[0]
    need(type(op) is str)
    if op in ('top', 'bot'):
        need(len(value) == 1)
    elif op == 'atom':
        need(len(value) == 2)
        name(value[1])
    else:
        need(op in ('and', 'or', 'imp') and len(value) == 3)
        formula(value[1], depth + 1)
        formula(value[2], depth + 1)
    return value


def certify(goal, term, library=None, budget=10000):
    library = {} if library is None else library
    canonical({'goal': goal, 'term': term, 'library': library})
    formula(goal)
    integer(budget, 1, 100000)
    need(type(library) is dict and len(library) <= 256)
    for key, entry in library.items():
        name(key)
        fields(entry, ('goal', 'term'))
        formula(entry['goal'])
    visits = 0
    cache = {}
    active = set()

    def infer(proof, context):
        nonlocal visits
        visits += 1
        need(visits <= budget, 'FUEL')
        need(type(proof) is list and proof)
        op = proof[0]
        need(type(op) is str)
        if op == 'var':
            need(len(proof) == 2)
            return context[integer(proof[1], 0, len(context) - 1)]
        if op == 'unit':
            need(len(proof) == 1)
            return ['top']
        if op == 'ref':
            need(len(proof) == 2)
            key = name(proof[1])
            need(key in library, 'REFERENCE')
            need(key not in active, 'CONFLICT')
            if key not in cache:
                active.add(key)
                inferred = infer(library[key]['term'], [])
                need(inferred == library[key]['goal'], 'TYPE')
                cache[key] = inferred
                active.remove(key)
            return cache[key]
        if op == 'lam':
            need(len(proof) == 3)
            arg = formula(proof[1])
            return ['imp', arg, infer(proof[2], [arg] + context)]
        if op == 'app':
            need(len(proof) == 3)
            function = infer(proof[1], context)
            argument = infer(proof[2], context)
            need(function[0] == 'imp' and function[1] == argument, 'TYPE')
            return function[2]
        if op == 'pair':
            need(len(proof) == 3)
            return ['and', infer(proof[1], context), infer(proof[2], context)]
        if op in ('fst', 'snd'):
            need(len(proof) == 2)
            pair = infer(proof[1], context)
            need(pair[0] == 'and', 'TYPE')
            return pair[1 if op == 'fst' else 2]
        if op == 'inl':
            need(len(proof) == 3)
            return ['or', infer(proof[1], context), formula(proof[2])]
        if op == 'inr':
            need(len(proof) == 3)
            return ['or', formula(proof[1]), infer(proof[2], context)]
        if op == 'case':
            need(len(proof) == 4)
            disjunction = infer(proof[1], context)
            left = infer(proof[2], context)
            right = infer(proof[3], context)
            need(disjunction[0] == 'or' and left[0] == right[0] == 'imp',
                 'TYPE')
            need(left[1] == disjunction[1] and right[1] == disjunction[2]
                 and left[2] == right[2], 'TYPE')
            return left[2]
        if op == 'absurd':
            need(len(proof) == 3)
            target = formula(proof[1])
            need(infer(proof[2], context) == ['bot'], 'TYPE')
            return target
        need(False, 'SCHEMA')

    need(infer(term, []) == goal, 'TYPE')
    return {
        'kind': 'ProofCertificate', 'profile': 'F2_ND_1',
        'environment': cid('ProofLibrary', library),
        'goal': deepcopy(goal), 'term': deepcopy(term), 'visits': visits,
    }


def check_certificate(certificate, library):
    fields(certificate, ('kind', 'profile', 'environment', 'goal', 'term',
                         'visits'))
    expected = certify(certificate['goal'], certificate['term'], library)
    need(canonical(certificate) == canonical(expected), 'INTEGRITY')
    return cid('ProofCertificate', certificate)


def search(goal, library, budget, mode='forward'):
    '''Both modes share indexed subgoals and charge one pair construction.'''
    formula(goal)
    integer(budget, 0, 10000)
    need(mode in ('forward', 'decompose'))
    need(type(library) is dict and len(library) <= 256)
    known = {}
    precheck_visits = 0
    for key in sorted(library):
        entry = library[key]
        certificate = certify(entry['goal'], ['ref', key], library)
        precheck_visits += certificate['visits']
        known[canonical(entry['goal'])] = ['ref', key]
    spent = 0

    def combine(target):
        nonlocal spent
        left = known.get(canonical(target[1]))
        right = known.get(canonical(target[2]))
        if left is None or right is None or spent >= budget:
            return None
        spent += 1
        term = ['pair', left, right]
        known[canonical(target)] = term
        return term

    def directed(target):
        key = canonical(target)
        if key in known:
            return known[key]
        if target[0] != 'and':
            return None
        if directed(target[1]) is None or directed(target[2]) is None:
            return None
        return combine(target)

    if mode == 'decompose':
        term = directed(goal)
    else:
        # A fair control admits the same nested conjunction fragment.
        ordered, seen = [], set()

        def postorder(target):
            key = canonical(target)
            if key in known or key in seen:
                return
            seen.add(key)
            if target[0] == 'and':
                postorder(target[1])
                postorder(target[2])
                ordered.append(target)

        postorder(goal)
        for target in ordered:
            combine(target)
        term = known.get(canonical(goal))
    certificate = None if term is None else certify(goal, term, library)
    return {'status': 'UNKNOWN' if term is None else 'CHECKED',
            'cost_model': 'F2_PAIR_CONSTRUCTION_2',
            'attempts': spent, 'precheck_visits': precheck_visits,
            'certificate_visits': 0 if certificate is None else (
                certificate['visits']), 'certificate': certificate}
