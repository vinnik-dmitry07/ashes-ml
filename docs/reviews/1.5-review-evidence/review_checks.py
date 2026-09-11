'''Reproduce the bounded-recursion failure without changing AHSL source.'''

import argparse
import json
from pathlib import Path
import sys


def tree_depth(value):
    if isinstance(value, dict):
        children = value.values()
    elif isinstance(value, list):
        children = value
    else:
        return 1
    return 1 + max((tree_depth(child) for child in children), default=0)


def run_checks(source):
    sys.path.insert(0, str(source))
    from ahsl.admission import Session
    from ahsl.api import handle
    from ahsl.codec import Rejected, canonical, cid, decode
    from ahsl.environment import check_agent
    from ahsl.examples import (
        builtin, call, choose, corridor_agent, function, lit, program, var,
    )
    from ahsl.language import check, execute
    from ahsl.obligations import IMPROVEMENT_PROFILE

    manifest = cid('Manifest', json.loads(
        (source / 'manifest.json').read_text()))
    key = b'local-review-public-fixture-key-only'

    def recursive_function(wrappers):
        body = choose(
            builtin('eq', var('n'), lit(0, 'Int')),
            lit(0, 'Int'),
            call('loop', builtin('sub', var('n'), lit(1, 'Int'))),
        )
        for index in range(wrappers):
            body = {
                'op': 'let', 'name': 'unused' + str(index),
                'value': lit(0, 'Int'), 'body': body,
            }
        return function({'n': 'Int'}, 'Int', body)

    def pure_program(wrappers, iterations=60):
        result = program(call('loop', lit(iterations, 'Int')), 'Int')
        result['functions']['loop'] = recursive_function(wrappers)
        check(result)
        return result

    def agent_program(wrappers):
        result = corridor_agent()
        result['functions']['loop'] = recursive_function(wrappers)
        body = result['functions']['main']['body']
        result['functions']['main']['body'] = {
            'op': 'let', 'name': 'discard',
            'value': call('loop', lit(60, 'Int')), 'body': body,
        }
        check_agent(result)
        return result

    def owner():
        return Session(corridor_agent('paint'), 8, key, manifest, [1])

    def send(session, request):
        return decode(handle(session, canonical(request)))

    def inspect_state(session):
        state = session.ledger.state
        return {
            'active_plan_present': session.active_plan is not None,
            'open_runs': state['open_runs'],
            'phases': [job['phase'] for job in state['jobs'].values()],
            'spent': state['spent'], 'free': state['free'],
            'generation': state['generation'],
        }

    original_limit = sys.getrecursionlimit()
    cases = []
    try:
        for host_limit, wrappers in ((1000, 12), (1000, 16), (5000, 16)):
            sys.setrecursionlimit(host_limit)
            candidate = pure_program(wrappers)
            request = {
                'op': 'run_pure', 'program': candidate,
                'arguments': [], 'fuel': 50000,
            }
            try:
                direct = {'code': 'OK', 'value': execute(
                    candidate, [], 50000)}
            except Exception as error:
                direct = {'exception': type(error).__name__}
            wire = send(owner(), request)
            cases.append({
                'kind': 'pure', 'host_limit': host_limit,
                'unused_let_wrappers': wrappers,
                'maximum_l12_call_depth': 62,
                'wire_depth': tree_depth(request),
                'wire_bytes': len(canonical(request)),
                'direct': direct, 'wire': wire,
            })

        for host_limit in (1000, 5000):
            sys.setrecursionlimit(host_limit)
            candidate = agent_program(16)
            session = owner()
            proposed = send(session, {
                'op': 'propose', 'program': candidate,
            })
            assert proposed['code'] == 'OK'
            plan = proposed['value']
            evaluated = send(session, {'op': 'evaluate', 'plan': plan})
            row = {
                'kind': 'g12', 'host_limit': host_limit,
                'program_bytes': len(canonical(candidate)),
                'maximum_l12_call_depth': 62,
                'propose_code': proposed['code'],
                'evaluate_code': evaluated['code'],
                'state_after_evaluate': inspect_state(session),
            }
            if evaluated['code'] == 'OK':
                decision = send(session, {
                    'op': 'admit', 'plan': plan,
                    'assignments': evaluated['value'],
                })
                row['release_accept'] = decision['value']['accept']
                row['cost_pairs'] = decision['value']['improvement'][
                    'cost_pairs']
            else:
                row['retry_code'] = send(session, {
                    'op': 'evaluate', 'plan': plan,
                })['code']
                session.abandon(plan)
                row['after_supervisor_abandon'] = inspect_state(session)
                recovery = send(session, {
                    'op': 'propose', 'program': corridor_agent(),
                })
                recovered = send(session, {
                    'op': 'evaluate', 'plan': recovery['value'],
                })
                decision = send(session, {
                    'op': 'admit', 'plan': recovery['value'],
                    'assignments': recovered['value'],
                })
                row['subsequent_normal_release'] = decision['value'][
                    'accept']
            cases.append(row)

        sys.setrecursionlimit(1000)
        try:
            execute(pure_program(0, 64), [], 50000)
        except Rejected as error:
            genuine_depth_limit = str(error)
        else:
            genuine_depth_limit = 'UNEXPECTED_SUCCESS'
    finally:
        sys.setrecursionlimit(original_limit)

    assert cases[0]['wire']['code'] == 'OK'
    assert cases[1]['direct']['exception'] == 'RecursionError'
    assert cases[1]['wire']['code'] == 'SCHEMA'
    assert cases[2]['wire']['value'] == {'result': 0, 'fuel_used': 2439}
    assert cases[3]['evaluate_code'] == 'SCHEMA'
    assert cases[3]['state_after_evaluate']['phases'] == ['DONE', 'RUNNING']
    assert cases[3]['retry_code'] == 'PHASE'
    assert cases[3]['subsequent_normal_release'] is True
    assert cases[4]['release_accept'] is True
    assert cases[4]['cost_pairs'][0][1]['vm_fuel'] == 9842
    assert genuine_depth_limit == 'LIMIT'

    return {
        'python': sys.version, 'original_host_limit': original_limit,
        'input_source': str(source), 'manifest_id': manifest,
        'runtime_improvement_profile': IMPROVEMENT_PROFILE,
        'spec_has_old_mission_profile':
            'improvement_profile = "SUCCESS_THEN_PARETO_COST_1"'
            in (source / 'SPEC.md').read_text(),
        'genuine_depth_limit_control': genuine_depth_limit,
        'cases': cases,
        'scope': 'No source changes, no external effects, no LLM calls. '
        'The larger host stack is a diagnostic control, not a proposed fix.',
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = run_checks(args.source.resolve())
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
