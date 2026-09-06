'''AHSL 1.0 finite propositional reference profile.

This is a deterministic, budgeted registry of conditional derivations.
Its certificates concern formulas under a pinned finite theory. They do
not certify Python implementations, physical facts, or learned models.
'''

from copy import deepcopy
import hashlib
import json
import re


MAX_NAT = 2 ** 31 - 1
MAX_ATOMS = 8
MAX_FORMULA_NODES = 64
MAX_PREMISES = 16
MAX_EVENTS = 4096
NAME = re.compile(r'[A-Za-z][A-Za-z0-9_.-]{0,127}')
REFERENCE = re.compile(r'h[0-9a-f]{64}')
FIELDS = {
    'declare': {'formula'},
    'sketch': {'target', 'premises'},
    'certify': {'claim'},
    'disprove': {'claim'},
    'note': {'claim', 'tag', 'payload_hash'},
}


class Rejected(Exception):
    '''A specified protocol rejection, without partial semantic mutation.'''


def require(condition, code='BAD_SCHEMA'):
    if not condition:
        raise Rejected(code)


def fields(value, expected):
    require(type(value) is dict and set(value) == set(expected))


def identifier(value):
    require(type(value) is str and NAME.fullmatch(value) is not None)


def reference(value):
    require(type(value) is str and REFERENCE.fullmatch(value) is not None)


def natural(value):
    require(type(value) is int and 0 <= value <= MAX_NAT)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False,
    ).encode('utf-8')


def content_id(value):
    return 'h' + hashlib.sha256(canonical(value)).hexdigest()


def validate_formula(formula, atoms, depth=0):
    require(type(formula) is list and formula and depth < 32)
    operator = formula[0]
    require(type(operator) is str)
    if operator in ('top', 'bottom'):
        require(len(formula) == 1)
        return 1
    if operator == 'atom':
        require(len(formula) == 2)
        require(type(formula[1]) is str and formula[1] in atoms)
        return 1
    arity = {'not': 1, 'and': 2, 'or': 2, 'implies': 2}
    require(operator in arity and len(formula) == arity[operator] + 1)
    count = 1 + sum(
        validate_formula(child, atoms, depth + 1) for child in formula[1:]
    )
    require(count <= MAX_FORMULA_NODES)
    return count


def evaluate(formula, assignment):
    operator = formula[0]
    if operator == 'top':
        return True
    if operator == 'bottom':
        return False
    if operator == 'atom':
        return assignment[formula[1]]
    if operator == 'not':
        return not evaluate(formula[1], assignment)
    left = evaluate(formula[1], assignment)
    right = evaluate(formula[2], assignment)
    if operator == 'and':
        return left and right
    if operator == 'or':
        return left or right
    return not left or right


def scope_models(scope):
    atoms = scope['atoms']
    models = []
    for bits in range(2 ** len(atoms)):
        assignment = {
            atom: bool(bits & (1 << index))
            for index, atom in enumerate(atoms)
        }
        if all(evaluate(item, assignment) for item in scope['assumptions']):
            models.append(assignment)
    return models


def initial(scope, budget):
    fields(scope, {'environment', 'definitions', 'atoms', 'assumptions'})
    reference(scope['environment'])
    reference(scope['definitions'])
    atoms = scope['atoms']
    require(type(atoms) is list and len(atoms) <= MAX_ATOMS)
    for atom in atoms:
        identifier(atom)
    require(atoms == sorted(set(atoms)))
    assumptions = scope['assumptions']
    require(type(assumptions) is list and len(assumptions) <= 16)
    for formula in assumptions:
        validate_formula(formula, atoms)
    require(scope_models(scope), 'INCONSISTENT_SCOPE')
    natural(budget)
    return {
        'scope': deepcopy(scope), 'scope_id': content_id(scope),
        'claims': {}, 'sketches': {}, 'certificates': {},
        'refutations': {}, 'notes': {}, 'witnesses': {}, 'ranks': {},
        'budget': budget, 'available': budget, 'spent': 0,
        'seen': {}, 'log': [],
    }


def validate_event(event, atoms):
    require(type(event) is dict)
    kind = event.get('kind')
    require(type(kind) is str and kind in FIELDS)
    fields(event, {'id', 'kind'} | FIELDS[kind])
    identifier(event['id'])
    if kind == 'declare':
        validate_formula(event['formula'], atoms)
    elif kind == 'sketch':
        reference(event['target'])
        premises = event['premises']
        require(type(premises) is list and len(premises) <= MAX_PREMISES)
        for item in premises:
            reference(item)
        require(premises == sorted(set(premises)))
    else:
        reference(event['claim'])
        if kind == 'note':
            tags = ('hypothesis', 'report', 'counterexample_hint')
            require(event['tag'] in tags)
            reference(event['payload_hash'])


def tariff(state, event):
    models = len(scope_models(state['scope']))
    if event['kind'] == 'sketch':
        return 1 + models * (1 + len(event['premises']))
    if event['kind'] in ('certify', 'disprove'):
        return 1 + models
    return 1


def close_graph(claims, sketches, certificates):
    '''Least closure; return one acyclic witness for each closed claim.'''
    witnesses = {
        claim: {'kind': 'certificate', 'ref': certificate}
        for claim, certificate in sorted(certificates.items())
    }
    ranks = dict.fromkeys(witnesses, 0)
    changed = True
    while changed:
        changed = False
        for sketch_id, sketch in sorted(sketches.items()):
            target = sketch['target']
            if target in witnesses:
                continue
            if all(item in witnesses for item in sketch['premises']):
                require(target in claims, 'CORRUPT_STATE')
                witnesses[target] = {'kind': 'sketch', 'ref': sketch_id}
                ranks[target] = 1 + max(
                    (ranks[item] for item in sketch['premises']), default=0,
                )
                changed = True
    return witnesses, ranks


def apply_event(state, event):
    kind = event['kind']
    scope_id = state['scope_id']
    if kind == 'declare':
        claim = {'scope': scope_id, 'formula': event['formula']}
        claim_id = content_id(claim)
        state['claims'][claim_id] = deepcopy(claim)
        return {'code': 'DECLARED', 'claim': claim_id}
    if kind == 'sketch':
        needed = [event['target']] + event['premises']
        require(
            all(item in state['claims'] for item in needed), 'UNKNOWN_CLAIM',
        )
        target = state['claims'][event['target']]['formula']
        premises = [
            state['claims'][item]['formula'] for item in event['premises']
        ]
        compatible = [
            model for model in scope_models(state['scope'])
            if all(evaluate(item, model) for item in premises)
        ]
        require(compatible, 'VACUOUS_SKETCH')
        require(
            all(evaluate(target, model) for model in compatible),
            'BAD_IMPLICATION',
        )
        sketch = {
            'scope': scope_id, 'target': event['target'],
            'premises': event['premises'],
        }
        sketch_id = content_id(sketch)
        state['sketches'][sketch_id] = deepcopy(sketch)
        return {'code': 'SKETCH_ACCEPTED', 'sketch': sketch_id}
    require(event['claim'] in state['claims'], 'UNKNOWN_CLAIM')
    if kind == 'note':
        note = {key: event[key] for key in ('claim', 'tag', 'payload_hash')}
        note_id = content_id(note)
        state['notes'][note_id] = deepcopy(note)
        return {'code': 'NOTE_RECORDED', 'note': note_id}
    formula = state['claims'][event['claim']]['formula']
    models = scope_models(state['scope'])
    results = [evaluate(formula, model) for model in models]
    if kind == 'certify':
        require(all(results), 'NOT_ESTABLISHED')
        target = state['certificates']
    else:
        require(not any(results), 'NOT_ESTABLISHED')
        target = state['refutations']
    certificate = {
        'checker': 'bool-exhaustive-1', 'scope': scope_id,
        'claim': event['claim'], 'kind': kind,
    }
    certificate_id = content_id(certificate)
    target[event['claim']] = certificate_id
    return {'code': 'CHECKED', 'certificate': certificate_id}


def status(state, claim):
    require(claim in state['claims'], 'UNKNOWN_CLAIM')
    if claim in state['witnesses']:
        return 'VERIFIED'
    if claim in state['refutations']:
        return 'REFUTED'
    if any(item['target'] == claim for item in state['sketches'].values()):
        return 'CONDITIONAL'
    return 'OPEN'


def step(state, event):
    '''Pure transition over a valid state produced by initial/step.

Rejected well-formed operations retain their cost and event identity.
This profile has no provider, publication, execution, or authority API.
'''
    try:
        validate_event(event, state['scope']['atoms'])
    except (Rejected, TypeError, ValueError, RecursionError):
        return deepcopy(state), {'code': 'BAD_SCHEMA'}
    event_id = event['id']
    digest = content_id(event)
    if event_id in state['seen']:
        previous = state['seen'][event_id]
        if previous['event_hash'] != digest:
            return deepcopy(state), {'code': 'ID_CONFLICT'}
        return deepcopy(state), deepcopy(previous['answer'])
    if len(state['seen']) >= MAX_EVENTS:
        return deepcopy(state), {'code': 'EVENT_LIMIT'}
    updated = deepcopy(state)
    cost = tariff(state, event)
    if cost > state['available']:
        answer = {'code': 'BUDGET_EXHAUSTED'}
        charged = 0
    else:
        charged = cost
        updated['available'] -= cost
        updated['spent'] += cost
        charged_state = deepcopy(updated)
        try:
            answer = apply_event(updated, event)
            updated['witnesses'], updated['ranks'] = close_graph(
                updated['claims'], updated['sketches'],
                updated['certificates'],
            )
        except Rejected as error:
            updated = charged_state
            answer = {'code': str(error)}
    updated['seen'][event_id] = {
        'event_hash': digest, 'answer': deepcopy(answer),
    }
    updated['log'].append({
        'id': event_id, 'event_hash': digest, 'answer': deepcopy(answer),
        'charged': charged,
    })
    return updated, answer
