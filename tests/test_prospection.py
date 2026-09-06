'''Counterexamples for conditional proof composition and evidence handling.'''

from copy import deepcopy
import unittest

import prospection as p


def scope(assumptions=None):
    return {
        'environment': p.content_id({'environment': 'demo-v1'}),
        'definitions': p.content_id({'definitions': 'propositional-demo'}),
        'atoms': ['a', 'b'], 'assumptions': assumptions or [],
    }


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.state = p.initial(scope(), 100000)
        self.serial = 0

    def send(self, kind, **payload):
        self.serial += 1
        event = dict(id=f'e{self.serial}', kind=kind, **payload)
        self.state, answer = p.step(self.state, event)
        return answer

    def claim(self, formula):
        return self.send('declare', formula=formula)['claim']

    def sketch(self, target, *premises):
        return self.send('sketch', target=target, premises=sorted(premises))

    def test_open_is_not_false(self):
        claim = self.claim(['atom', 'a'])
        for kind in ('certify', 'disprove'):
            answer = self.send(kind, claim=claim)
            self.assertEqual(answer['code'], 'NOT_ESTABLISHED')
        self.assertEqual(p.status(self.state, claim), 'OPEN')

    def test_checked_composition_precedes_closed_leaves(self):
        a = self.claim(['or', ['atom', 'a'], ['not', ['atom', 'a']]])
        b = self.claim(['implies', ['atom', 'b'], ['atom', 'b']])
        root = self.claim(['and', self.state['claims'][a]['formula'],
                           self.state['claims'][b]['formula']])
        self.assertEqual(self.sketch(root, a, b)['code'], 'SKETCH_ACCEPTED')
        self.assertEqual(p.status(self.state, root), 'CONDITIONAL')
        self.send('certify', claim=a)
        self.assertEqual(p.status(self.state, root), 'CONDITIONAL')
        self.send('certify', claim=b)
        self.assertEqual(p.status(self.state, root), 'VERIFIED')

    def test_or_routes_preserve_alternatives(self):
        root = self.claim(['top'])
        unknown = self.claim(['atom', 'a'])
        solved = self.claim(['implies', ['atom', 'b'], ['atom', 'b']])
        self.sketch(root, unknown)
        self.sketch(root, solved)
        self.send('certify', claim=solved)
        self.assertEqual(p.status(self.state, root), 'VERIFIED')
        self.assertEqual(len(self.state['sketches']), 2)
        self.assertEqual(p.status(self.state, unknown), 'OPEN')

    def test_cycle_does_not_prove_itself(self):
        a = self.claim(['atom', 'a'])
        equivalent = self.claim(['and', ['atom', 'a'], ['top']])
        self.sketch(a, equivalent)
        self.sketch(equivalent, a)
        self.assertEqual(self.state['witnesses'], {})
        self.assertEqual(p.status(self.state, a), 'CONDITIONAL')

    def test_self_dependency_does_not_close(self):
        claim = self.claim(['atom', 'a'])
        self.sketch(claim, claim)
        self.assertEqual(self.state['witnesses'], {})

    def test_false_implication_rejected(self):
        a = self.claim(['atom', 'a'])
        b = self.claim(['atom', 'b'])
        self.assertEqual(self.sketch(b, a)['code'], 'BAD_IMPLICATION')
        self.assertEqual(self.state['sketches'], {})

    def test_incompatible_premises_do_not_vacuously_close_goal(self):
        a = self.claim(['atom', 'a'])
        not_a = self.claim(['not', ['atom', 'a']])
        b = self.claim(['atom', 'b'])
        self.assertEqual(self.sketch(b, a, not_a)['code'], 'VACUOUS_SKETCH')

    def test_inconsistent_scope_is_rejected(self):
        with self.assertRaisesRegex(p.Rejected, 'INCONSISTENT_SCOPE'):
            p.initial(scope([['bottom']]), 100)

    def test_empirical_report_cannot_certify(self):
        claim = self.claim(['atom', 'a'])
        self.send('note', claim=claim, tag='report',
                  payload_hash=p.content_id({'successes': 1000000}))
        self.assertEqual(p.status(self.state, claim), 'OPEN')
        self.assertEqual(self.state['certificates'], {})

    def test_false_is_refuted_only_after_check(self):
        claim = self.claim(['bottom'])
        self.assertEqual(p.status(self.state, claim), 'OPEN')
        self.assertEqual(self.send('disprove', claim=claim)['code'], 'CHECKED')
        self.assertEqual(p.status(self.state, claim), 'REFUTED')

    def test_empty_premise_requires_valid_goal(self):
        unknown = self.claim(['atom', 'a'])
        self.assertEqual(self.sketch(unknown)['code'], 'BAD_IMPLICATION')
        true = self.claim(['top'])
        self.sketch(true)
        self.assertEqual(p.status(self.state, true), 'VERIFIED')

    def test_scope_identity_pins_environment_and_definitions(self):
        claim = self.claim(['top'])
        for field in ('environment', 'definitions'):
            changed = scope()
            changed[field] = p.content_id({'new': field})
            other = p.initial(changed, 100)
            other, answer = p.step(other, {
                'id': 'x', 'kind': 'certify', 'claim': claim,
            })
            self.assertEqual(answer['code'], 'UNKNOWN_CLAIM')

    def test_reference_and_input_are_immutable(self):
        formula = ['atom', 'a']
        old = deepcopy(self.state)
        claim = self.claim(formula)
        formula[1] = 'b'
        self.assertEqual(self.state['claims'][claim]['formula'], ['atom', 'a'])
        self.assertEqual(old['claims'], {})

    def test_duplicate_event_never_charges_twice(self):
        event = {'id': 'once', 'kind': 'declare', 'formula': ['top']}
        state, answer = p.step(self.state, event)
        repeated, again = p.step(state, event)
        self.assertEqual(again, answer)
        self.assertEqual(repeated, state)
        changed, conflict = p.step(state, dict(event, formula=['bottom']))
        self.assertEqual(conflict['code'], 'ID_CONFLICT')
        self.assertEqual(changed, state)

    def test_failed_check_still_consumes_budget(self):
        claim = self.claim(['atom', 'a'])
        spent = self.state['spent']
        self.send('certify', claim=claim)
        self.assertEqual(self.state['spent'] - spent, 5)
        self.assertEqual(self.state['available'] + self.state['spent'], 100000)

    def test_budget_exhaustion_has_no_partial_mutation(self):
        self.state = p.initial(scope(), 1)
        claim = self.claim(['atom', 'a'])
        answer = self.send('certify', claim=claim)
        self.assertEqual(answer['code'], 'BUDGET_EXHAUSTED')
        self.assertEqual(self.state['spent'], 1)
        self.assertEqual(p.status(self.state, claim), 'OPEN')

    def test_forged_certificate_field_is_rejected(self):
        claim = self.claim(['atom', 'a'])
        state, answer = p.step(self.state, {
            'id': 'forged', 'kind': 'certify', 'claim': claim,
            'verified': True,
        })
        self.assertEqual(answer['code'], 'BAD_SCHEMA')
        self.assertEqual(state, self.state)

    def test_formula_bounds_and_unknown_atoms(self):
        for formula in (['atom', 'unknown'], ['top', True], ['mystery']):
            answer = self.send('declare', formula=formula)
            self.assertEqual(answer['code'], 'BAD_SCHEMA')

    def test_witness_rank_strictly_increases(self):
        root = self.claim(['top'])
        child = self.claim(['or', ['atom', 'a'], ['not', ['atom', 'a']]])
        self.sketch(root, child)
        self.send('certify', claim=child)
        ranks = self.state['ranks']
        self.assertGreater(ranks[root], ranks[child])


if __name__ == '__main__':
    unittest.main()
