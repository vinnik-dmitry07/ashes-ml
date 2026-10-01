'''
Reproducible verification with dynamic counts and complete source
closure.
'''

import argparse
from collections import deque
from copy import deepcopy
from fractions import Fraction
import hashlib
import io
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parent
RELEASE_DIRS = ('src', 'tests', 'examples')


def source_files():
    '''Release sources only: top level plus src, tests, and examples.'''
    candidates = list(ROOT.glob('*'))
    for name in RELEASE_DIRS:
        if (ROOT / name).is_dir():
            candidates.extend((ROOT / name).rglob('*'))
    return sorted(path for path in candidates
                  if path.is_file() and path.suffix in ('.py', '.json')
                  and path.name != 'manifest.json')


def manifest():
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(
        path.read_bytes()).hexdigest() for path in source_files()}


def model_check():
    from src.codec import Rejected, canonical, cid
    from src.kernel import initial, invariant, step
    a, b = cid('ModelCandidate', 'A'), cid('ModelCandidate', 'B')

    def project(state):
        result = deepcopy(state)
        del result['sequence']
        return canonical(result)

    start = initial(3, a)
    queue = deque([(start, 0)])
    seen = {project(start)}
    transitions = rejected = recovered = depth_max = 0
    while queue:
        state, depth = queue.popleft()
        depth_max = max(depth_max, depth)
        invariant(state)
        events = [('agent', {'op': 'close_run'})]
        if state['open_runs'] == 0:
            events.append(('agent', {'op': 'start_run'}))
        if state['generation'] < 2:
            for target in (a, b):
                for principal, op in (('admitter', 'publish'),
                                      ('supervisor', 'rollback'),
                                      ('agent', 'publish')):
                    events.append(
                        (principal,
                         {'op': op, 'candidate': target,
                          'generation': state['generation']}))
        for job in ('j0', 'j1'):
            for upper in (1, 2):
                events.append(('agent', {'op': 'reserve', 'job': job,
                                         'upper': upper}))
            for principal, op in (
                ('executor', 'dispatch'),
                ('executor', 'unknown'),
                ('executor', 'fence'),
                ('supervisor', 'seal'),
                ('supervisor', 'cancel'),
                    ('agent', 'seal')):
                events.append((principal, {'op': op, 'job': job}))
            for actual in (0, 1, 2):
                events.append(('executor', {'op': 'complete', 'job': job,
                                            'actual': actual, 'receipt': a}))
        for principal, event in events:
            try:
                new, output = step(state, principal, event)
            except Rejected:
                rejected += 1
                continue
            transitions += 1
            key = project(new)
            if key not in seen:
                seen.add(key)
                queue.append((new, depth + 1))
        # Explicit recovery path for every reachable state with unknown work.
        if any(job['phase'] == 'UNKNOWN' for job in state['jobs'].values()):
            current = deepcopy(state)
            for job, item in list(current['jobs'].items()):
                if item['phase'] == 'RESERVED':
                    current, _ = step(
                        current, 'supervisor', {
                            'op': 'cancel', 'job': job})
                elif item['phase'] in ('RUNNING', 'UNKNOWN'):
                    current, _ = step(
                        current, 'executor', {
                            'op': 'fence', 'job': job})
                    current, _ = step(
                        current, 'supervisor', {
                            'op': 'seal', 'job': job})
            assert all(job['phase'] in ('DONE', 'SEALED', 'CANCELLED')
                       for job in current['jobs'].values())
            recovered += 1
    return {
        'scope': ('2 jobs, total=3, upper in {1,2}, '
                  'generation<=2, open_runs<=1'),
        'projection': 'erase sequence; implementation step used directly',
        'states': len(seen),
        'accepted_transitions': transitions,
        'rejected_transitions': rejected,
        'maximum_bfs_depth': depth_max,
        'unknown_states_with_recovery_path': recovered,
        'general_liveness_proved': False}


def benchmark():
    from src.codec import cid
    from src.environment import Runner
    from src.examples import corridor_agent
    runner = Runner(b'benchmark-key-not-a-production-secret',
                    cid('Manifest', manifest()))
    rows = []
    for level in range(1, 13):
        for method in ('solver', 'paint', 'fault_schedule'):
            outcomes, costs = [], []
            for repetition in range(5):
                correct = method == 'solver' or (
                    method == 'fault_schedule' and repetition != 2)
                style = 'solver' if correct else 'paint'
                item = corridor_agent(style)
                assignment = runner.assign(
                    cid('Program', item), 0, level, repetition)
                envelope = runner.run(assignment, item)
                result = runner.verify(envelope)
                outcomes.append(result['ground_success'])
                costs.append(result['steps'])
            mean = Fraction(sum(outcomes), len(outcomes))
            rows.append({'level': level, 'method': method,
                         'minimum_solution_actions': 3 * level + 1,
                         'successes': sum(outcomes), 'runs': len(outcomes),
                         'pass_all_5': all(outcomes),
                         'empirical_variance': str(mean * (1 - mean)),
                         'actions': costs, 'maximum_actions': max(costs)})
    return {
        'kind': 'finite deterministic stress fixture',
        'fault_schedule': ('one complete paint run among five; '
                           'not an LLM estimate'),
        'rows': rows}


def adversarial_wire():
    from src.admission import Session
    from src.api import handle
    from src.codec import ERRORS, canonical, cid, decode
    from src.examples import corridor_agent
    rng = random.Random(74123)
    session = Session(corridor_agent('paint'),
                      24, b'wire-test-key-not-production-keyxx',
                      cid('Manifest', manifest()))
    atoms = [None, 0, True, '', [], {}, ['op'], {'op': 'publish'}]
    counts = {}
    for _ in range(2000):
        value = rng.choice(atoms)
        for _ in range(rng.randrange(4)):
            value = rng.choice(
                [{'op': value},
                 {'op': 'evaluate', 'plan': value},
                 {'op': 'propose', 'program': value},
                 [value]])
        result = decode(handle(session, canonical(value)))
        assert result['code'] in ERRORS | {'OK'}
        counts[result['code']] = counts.get(result['code'], 0) + 1
    return {'requests': sum(counts.values()), 'outcomes': counts,
            'outer_admitted': session.requests_used,
            'outer_rejected': sum(counts.values()) - session.requests_used,
            'schema_rejections': counts.get('SCHEMA', 0),
            'ok': counts.get('OK', 0)}


def structured_wire():
    '''Mutate valid request trees, retaining successful dispatch controls.'''
    from src.admission import Session
    from src.api import handle
    from src.codec import ERRORS, canonical, cid, decode
    from src.examples import builtin, corridor_agent, lit, program
    rng = random.Random(15074123)
    counts, origins = {}, {'seed': 0, 'mutation': 0}
    admitted = 0

    def send(owner, request, origin):
        nonlocal admitted
        before = owner.requests_used
        result = decode(handle(owner, canonical(request)))
        admitted += owner.requests_used - before
        need_code = result['code'] in ERRORS | {'OK'}
        assert need_code
        counts[result['code']] = counts.get(result['code'], 0) + 1
        origins[origin] += 1
        return result

    for _ in range(8):
        owner = Session(corridor_agent('paint'), 24,
                        b'structured-wire-public-fixture-key',
                        cid('Manifest', manifest()), [1])
        candidate = corridor_agent()
        first = send(owner, {'op': 'propose', 'program': candidate}, 'seed')
        assert first['code'] == 'OK'
        plan = first['value']
        evaluated = send(owner, {'op': 'evaluate', 'plan': plan}, 'seed')
        assert evaluated['code'] == 'OK'
        assignments = evaluated['value']
        receipt = owner.runner.receipts[assignments[1]]
        accepted = send(owner, {'op': 'admit', 'plan': plan,
                                'assignments': assignments}, 'seed')
        assert accepted['code'] == 'OK' and accepted['value']['accept']
        trained = send(owner, {'op': 'train', 'envelope': receipt}, 'seed')
        assert trained['code'] == 'OK'
        templates = [
            {'op': 'propose', 'program': corridor_agent('noop')},
            {'op': 'evaluate', 'plan': plan},
            {'op': 'read_receipt', 'assignment': assignments[1]},
            {'op': 'admit', 'plan': plan, 'assignments': assignments},
            {'op': 'train', 'envelope': receipt},
            {'op': 'condense', 'assignments': [assignments[1]]},
            {'op': 'check_proof', 'goal': ['top'], 'term': ['unit'],
             'library': {}},
            {'op': 'run_pure', 'program': program(lit(1, 'Int'), 'Int'),
             'arguments': [], 'fuel': 10},
        ]
        for _ in range(92):
            request = deepcopy(rng.choice(templates))
            mutation = rng.randrange(8)
            origin = 'seed' if mutation == 0 else 'mutation'
            if mutation == 1:
                request['extra'] = 1
            elif mutation == 2:
                del request[rng.choice(sorted(request))]
            elif mutation == 3:
                request[rng.choice(sorted(request))] = None
            elif mutation == 4:
                request = {'op': 'run_pure', 'arguments': [], 'fuel': 10,
                           'program': program(lit(1, 'Int'), 'Bool')}
            elif mutation == 5:
                request = {'op': 'evaluate', 'plan': cid('Unknown', 'plan')}
            elif mutation == 6:
                forged = deepcopy(receipt)
                forged['tag'] = '0' * 64
                request = {'op': 'train', 'envelope': forged}
            elif mutation == 7:
                request = {
                    'op': 'run_pure', 'arguments': [], 'fuel': 1,
                    'program': program(builtin('add', lit(1, 'Int'),
                                               lit(2, 'Int')), 'Int'),
                }
            send(owner, request, origin)
    return {'requests': sum(counts.values()), 'outcomes': counts,
            'origins': origins, 'outer_admitted': admitted,
            'ok': counts.get('OK', 0),
            'covered_error_codes': len(set(counts) - {'OK'}),
            'alphabet_size': len(ERRORS),
            'scope': '8 independent sessions; valid lifecycle seeds and '
            'bounded request-tree mutations, not exhaustive wire coverage'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--write-manifest', action='store_true')
    parser.add_argument('--expected-manifest')
    parser.add_argument('--quick', action='store_true')
    args = parser.parse_args()
    manifest_path = ROOT / 'manifest.json'
    if args.write_manifest:
        manifest_path.write_text(
            json.dumps(
                manifest(),
                sort_keys=True,
                indent=2) + '\n')
    pinned = json.loads(manifest_path.read_text())
    if pinned != manifest():
        raise SystemExit(
            'Manifest differs: changed, missing, or unlisted source')
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if args.expected_manifest and args.expected_manifest != digest:
        raise SystemExit('External manifest anchor mismatch')
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
    if not result.wasSuccessful():
        print(stream.getvalue())
        raise SystemExit(1)
    report = {'profile': 'AHSL-1.5', 'status': 'EXECUTABLE_REFERENCE',
              'tests_run': result.testsRun, 'failures': len(result.failures),
              'errors': len(result.errors), 'manifest_sha256': digest,
              'files_checked': len(pinned), 'wire_fuzz': adversarial_wire(),
              'structured_wire_fuzz': structured_wire()}
    reports = ROOT / 'reports'
    reports.mkdir(exist_ok=True)
    if not args.quick:
        report['bounded_implementation_exploration'] = model_check()
        (reports / 'benchmark.json').write_text(json.dumps(benchmark(),
                                                           indent=2) + '\n')
        digests = {}
        for seed in ('0', '5', '12345'):
            environment = dict(os.environ, PYTHONHASHSEED=seed)
            digests[seed] = subprocess.check_output(
                [sys.executable, str(ROOT / 'replay_fixture.py')],
                env=environment, text=True).strip()
        assert len(set(digests.values())) == 1
        (reports / 'replay-determinism.json').write_text(
            json.dumps(digests, indent=2) + '\n')
        report['session_replay_hashseeds'] = list(digests)
    (reports / 'verification.json').write_text(json.dumps(report,
                                                          indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
