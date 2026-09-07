'''
Run the actual observation, admission, condensation and formalization
chain.
'''

import json
from pathlib import Path

from ahsl.admission import Session, formalize
from ahsl.codec import cid
from ahsl.examples import corridor_agent
from ahsl.proofs import search
from ahsl.schema import validate_schema


def run(manifest):
    root_key = b'demo-key-only-never-use-in-a-service'
    owner = Session(corridor_agent('paint'), 48,
                    root_key, manifest)
    plan = owner.prepare(corridor_agent(), list(range(1, 13)))
    receipts = owner.evaluate(plan)
    decision = owner.admit(plan, receipts)
    admissions = []
    for receipt in receipts:
        trace = receipt['receipt']['trace']
        if trace['candidate'] == cid('Program', corridor_agent()):
            admissions.append(owner.admit_training(receipt))
    owner.ledger.apply('agent', {'op': 'start_run'})
    before = owner.ledger.state['generation']
    local = owner.condense(list(owner.dataset))
    assert owner.ledger.state['generation'] == before
    owner.ledger.apply('agent', {'op': 'close_run'})
    compiled = formalize(local)
    compiled_plan = owner.prepare(compiled, list(range(1, 13)), mode='retain')
    compiled_receipts = owner.evaluate(compiled_plan)
    compiled_decision = owner.admit(compiled_plan, compiled_receipts)
    assert compiled_decision['accept']
    successes = [child for parent, child in compiled_decision['pairs']]
    snapshot = owner.snapshot()
    restored = Session.restore(snapshot, root_key,
                               cid('SessionSnapshot', snapshot))
    assert restored.snapshot() == snapshot
    for value, schema in (
        (decision, 'ReleaseDecision'),
        (compiled_decision, 'ReleaseDecision'),
        (local, 'LocalPolicy'),
            (snapshot, 'SessionSnapshot')):
        validate_schema(value, schema)
    for value in admissions:
        validate_schema(value, 'TrainingAdmission')
    library = {}
    for key in ('A', 'B', 'C', 'D'):
        atom = ['atom', key]
        library[key] = {'goal': ['imp', atom, atom],
                        'term': ['lam', atom, ['var', 0]]}
    goal = ['and', library['C']['goal'], library['D']['goal']]
    return {
        'release': decision, 'admitted_training_trajectories': len(admissions),
        'local_policy_entries': len(local['table']),
        'compiled_policy_successes': successes,
        'compiled_policy_release': compiled_decision,
        'ledger_spent_execution_tickets': owner.ledger.state['spent'],
        'compiled_validation_runs_including_parent': len(compiled_receipts),
        'snapshot_restored': True,
        'search': {mode: search(goal, library, 1, mode)
                   for mode in ('forward', 'decompose')},
        'example_exploit': receipts[0], 'example_success': receipts[1],
    }


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / 'manifest.json').read_text())
    result = run(cid('Manifest', manifest))
    (root / 'reports').mkdir(exist_ok=True)
    (root / 'reports' / 'demo.json').write_text(
        json.dumps(result, indent=2) + '\n')
    excluded = ('example_exploit', 'example_success', 'search')
    summary = {key: value for key, value in result.items()
               if key not in excluded}
    print(json.dumps(summary, indent=2))
