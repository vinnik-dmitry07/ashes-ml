'''
Reproduce the findings of the AHSL 1.5 repository audit (September 2026).

Run from anywhere with the repository checkout as ROOT:

    python3 docs/audits/1.5-repository-audit/reproduce.py --output out.json

Standard library only. Nothing inside ROOT is modified: verify.py and the
replay fixture run in temporary copies. The CPU check uses n=2048 by default
(about 3 s); pass --full for the n=4096 row (about 10 s).
'''

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.admission import Session  # noqa: E402
from src.api import handle  # noqa: E402
from src.codec import Rejected, canonical, cid, decode  # noqa: E402
from src.environment import AGENT_PARAMS, INTENT_TYPE  # noqa: E402
from src.examples import (  # noqa: E402
    builtin, call, choose, corridor_agent, function, lit, program, var)
from src.language import check  # noqa: E402
from src.obligations import DEFAULT_GUARANTEES  # noqa: E402


KEY = b'audit-key-not-a-production-secret-xx'
MANIFEST = cid('Manifest', 'audit')
README_ANCHOR = ('01ada0969532bcc9db11d1f2968b2166'
                 'ef76aa6866396195cccebc5398733430')


def wire(owner, request):
    return decode(handle(owner, canonical(request)))


def fresh(levels=(1,), baseline=None):
    return Session(baseline or corridor_agent('paint'), 24, KEY, MANIFEST,
                   list(levels))


def run_verify(directory, *arguments):
    result = subprocess.run(
        [sys.executable, 'verify.py', '--quick', *arguments],
        cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=900)
    lines = result.stdout.strip().splitlines()
    return {'returncode': result.returncode,
            'last_line': lines[-1] if lines else ''}


def reproducibility():
    '''A1-A3: verify.py in the repository layout and in the release layout.'''
    pinned = json.loads((ROOT / 'manifest.json').read_text())
    current = hashlib.sha256((ROOT / 'manifest.json').read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='ahsl-audit-') as scratch:
        tree = Path(scratch) / 'repository'
        shutil.copytree(ROOT, tree, ignore=shutil.ignore_patterns(
            '.git', '__pycache__', '.pytest_cache'))
        sys.path.insert(0, str(tree))
        import verify
        unlisted = sorted(set(verify.manifest()) - set(pinned))
        sys.path.remove(str(tree))
        repository = run_verify(tree)

        release = Path(scratch) / 'release'
        for name in list(pinned) + ['manifest.json']:
            target = release / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        with_readme_anchor = run_verify(release, '--expected-manifest',
                                        README_ANCHOR)
        with_current_anchor = run_verify(release, '--expected-manifest',
                                         current)
        replay = subprocess.run(
            [sys.executable, 'replay_fixture.py'], cwd=release, text=True,
            stdout=subprocess.PIPE, check=True).stdout.strip()
    committed = json.loads(
        (ROOT / 'reports/replay-determinism.json').read_text())
    verification = json.loads(
        (ROOT / 'reports/verification.json').read_text())
    return {
        'repository_layout': dict(repository, unlisted_files=len(unlisted),
                                  unlisted_top_level=sorted(
                                      {Path(item).parts[0]
                                       for item in unlisted})),
        'release_layout_readme_anchor': with_readme_anchor,
        'release_layout_current_anchor': with_current_anchor,
        'documented_anchor': README_ANCHOR,
        'current_manifest_sha256': current,
        'committed_verification_manifest':
            verification['manifest_sha256'],
        'committed_replay_digest': committed['0'],
        'current_replay_digest': replay,
    }


def loop_function(padding):
    body = choose(builtin('eq', var('n'), lit(0, 'Int')), lit(0, 'Int'),
                  call('loop', builtin('sub', var('n'), lit(1, 'Int'))))
    for index in range(padding):
        body = {'op': 'let', 'name': 'u%d' % index, 'value': lit(0, 'Int'),
                'body': body}
    return function({'n': 'Int'}, 'Int', body)


def recursion():
    '''B1: legal depth-62 program exhausts the Python stack.'''
    rows = {}
    for padding in (12, 16):
        item = program(call('loop', lit(60, 'Int')), 'Int')
        item['functions']['loop'] = loop_function(padding)
        rows['run_pure_lets_%d' % padding] = wire(fresh(), {
            'op': 'run_pure', 'program': item, 'arguments': [],
            'fuel': 50000})['code']
    solver = corridor_agent()
    body = {'op': 'let', 'name': 'ignored', 'value': call(
        'loop', lit(60, 'Int')), 'body': solver['functions']['main']['body']}
    candidate = {'entry': 'main', 'functions': {
        'main': function(AGENT_PARAMS, {'Option': INTENT_TYPE}, body),
        'loop': loop_function(16)}}
    owner = fresh()
    plan = wire(owner, {'op': 'propose', 'program': candidate})['value']
    rows['evaluate'] = wire(owner, {'op': 'evaluate', 'plan': plan})['code']
    state = owner.ledger.state
    rows['jobs_after'] = {key: job['phase']
                          for key, job in state['jobs'].items()}
    rows['open_runs_after'] = state['open_runs']
    rows['retry'] = wire(owner, {'op': 'evaluate', 'plan': plan})['code']
    rows['propose_other'] = wire(owner, {
        'op': 'propose', 'program': corridor_agent()})['code']
    return rows


def fenced_reevaluation():
    '''B2: evaluate dispatches a fenced assignment, then rejects PHASE.'''
    owner = fresh()
    first = wire(owner, {'op': 'propose', 'program': corridor_agent()})
    # Supervisor abandons an in-flight plan (for example after a timeout).
    owner.ledger.apply('agent', {'op': 'start_run'})
    owner.active_plan = first['value']
    owner.abandon(first['value'])
    second = wire(owner, {'op': 'propose', 'program': corridor_agent()})
    reevaluated = wire(owner, {'op': 'evaluate', 'plan': first['value']})
    state = owner.ledger.state
    return {
        'propose_second': second['code'],
        'reevaluate_abandoned': reevaluated['code'],
        'jobs_after': {key: job['phase']
                       for key, job in state['jobs'].items()},
        'open_runs_after': state['open_runs'],
        'free_after': state['free'],
        'evaluate_second': wire(owner, {
            'op': 'evaluate', 'plan': second['value']})['code'],
        'admit_second': wire(owner, {
            'op': 'admit', 'plan': second['value'],
            'assignments': []})['code'],
    }


def fuel_versus_cpu(full):
    '''B3: one builtin call is one fuel unit whatever its input size.'''
    pairs = {'List': {'List': 'Int'}}
    rows = []
    for n in (512, 1024, 2048) + ((4096,) if full else ()):
        item = program(builtin('length_int', builtin(
            'pareto', lit([[0]] * n, pairs))), 'Int')
        request = {'op': 'run_pure', 'program': item, 'arguments': [],
                   'fuel': 10}
        start = time.perf_counter()
        reply = wire(fresh(), request)
        rows.append({'points': n, 'request_bytes': len(canonical(request)),
                     'code': reply['code'],
                     'fuel_used': reply['value']['fuel_used'],
                     'seconds': round(time.perf_counter() - start, 2)})
    leaf = builtin('length_int', builtin('pareto', var('p')))
    recurse = call('f', builtin('sub', var('d'), lit(1, 'Int')), var('p'))
    body = choose(builtin('eq', var('d'), lit(0, 'Int')), leaf,
                  builtin('add', recurse, recurse))
    tree = []
    for depth in (0, 2):
        item = program(call('f', lit(depth, 'Int'),
                            lit([[0]] * 1024, pairs)), 'Int')
        item['functions']['f'] = function({'d': 'Int', 'p': pairs}, 'Int',
                                          body)
        start = time.perf_counter()
        reply = wire(fresh(), {'op': 'run_pure', 'program': item,
                               'arguments': [], 'fuel': 100000})
        tree.append({'pareto_calls': 2 ** depth,
                     'fuel_used': reply['value']['fuel_used'],
                     'seconds': round(time.perf_counter() - start, 2)})
    return {'single_call': rows, 'repeated_calls_n1024': tree}


def checker_totality():
    '''C1: malformed names escape check() as TypeError, not Rejected.'''
    cases = {
        'var_name_list': program({'op': 'var', 'name': []}, 'Int'),
        'call_name_dict': program({'op': 'call', 'name': {}, 'args': []},
                                  'Int'),
        'get_field_list': program({'op': 'get', 'record': {
            'op': 'record', 'fields': {'a': lit(1, 'Int')}}, 'field': []},
            'Int'),
        'entry_list': {'entry': [], 'functions': {
            'main': function({}, 'Int', lit(1, 'Int'))}},
    }
    rows = {}
    for label, item in cases.items():
        try:
            check(item)
            rows[label] = 'accepted'
        except Rejected as error:
            rows[label] = 'Rejected:' + str(error)
        except Exception as error:  # the finding is that this branch runs
            rows[label] = 'raw:' + type(error).__name__
        rows[label + '_wire'] = wire(fresh(), {
            'op': 'run_pure', 'program': item, 'arguments': [],
            'fuel': 10})['code']
    return rows


def retain_then_improve():
    '''C2: parent-relative improve after a retain regression.'''
    solver = corridor_agent()
    padded = corridor_agent()
    padded['functions']['main']['body'] = {
        'op': 'let', 'name': 'pad', 'value': lit('x' * 2000, 'Text'),
        'body': padded['functions']['main']['body']}
    owner = fresh((1, 2, 3), solver)
    rows = []
    for item, mode in ((padded, 'retain'), (solver, 'improve')):
        plan = wire(owner, {'op': 'propose_contracted', 'program': item,
                            'guarantees': DEFAULT_GUARANTEES,
                            'mode': mode})['value']
        ids = wire(owner, {'op': 'evaluate', 'plan': plan})['value']
        decision = wire(owner, {'op': 'admit', 'plan': plan,
                                'assignments': ids})['value']
        cost = decision['improvement']['cost_pairs'][0]
        rows.append({'mode': mode, 'accept': decision['accept'],
                     'cost_strict': decision['improvement']['cost_strict'],
                     'parent_program_bytes': cost[0]['program_bytes'],
                     'child_program_bytes': cost[1]['program_bytes']})
    return {'releases': rows,
            'active_is_original': owner.ledger.state['active']
            == cid('Program', solver),
            'generation': owner.ledger.state['generation'],
            'lifetime_plans_left': 4 - len(owner.plans)}


def documentation():
    '''C3: the profile identifier in SPEC.md section 12.1.'''
    lines = [number for number, line in enumerate(
        (ROOT / 'SPEC.md').read_text().splitlines(), 1)
        if 'SUCCESS_THEN_PARETO_COST_1' in line]
    return {'spec_lines_with_cost_1': lines}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output')
    parser.add_argument('--full', action='store_true')
    arguments = parser.parse_args()
    report = {
        'python': sys.version.split()[0],
        'A_reproducibility': reproducibility(),
        'B1_recursion': recursion(),
        'B2_fenced_reevaluation': fenced_reevaluation(),
        'B3_fuel_versus_cpu': fuel_versus_cpu(arguments.full),
        'C1_checker_totality': checker_totality(),
        'C2_retain_then_improve': retain_then_improve(),
        'C3_documentation': documentation(),
    }
    text = json.dumps(report, indent=2) + '\n'
    if arguments.output:
        Path(arguments.output).write_text(text)
    print(text, end='')


if __name__ == '__main__':
    main()
