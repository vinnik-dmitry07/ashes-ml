'''Executable trust scenarios and synthetic checks, with no model API.'''

import itertools
import json
import math
from pathlib import Path
from statistics import mean

from ahsl.codec import Rejected, cid
from ahsl.environment import (
    ENVIRONMENT, Runner, audit_trace, scripted, solution,
)
from .adapter import run_episode
from .evidence_views import BehaviorArchive, TrustedMemory
from .experiment import MemoryJournal, ROOT, check_sources, make_plan
from .protocol import CONDITIONS, Route, digest
from .providers import FixtureProvider
from .statistics import bounded_mean_interval, quantile_interval, tail_interval
from .trust import EvidenceLedger


FIXTURE_KEY = b'public-offline-fixture-key-not-production-authority'


def trace_input(level=1, actions=None):
    runner = Runner(FIXTURE_KEY, check_sources())
    assignment = runner.assign('b' * 64, 0, level, 0)
    trace = runner._run(assignment, scripted(
        solution(level) if actions is None else actions))['receipt']['trace']
    outcome = audit_trace(trace)
    return trace, {'kind': 'TraceConsistency', 'trace': outcome['trace'],
                   'ground_success': outcome['ground_success']}, {
                       'environment': ENVIRONMENT}


def trust_scenario(output):
    path = output / 'trust-events.jsonl'
    ledger = EvidenceLedger(path, FIXTURE_KEY, check_sources())
    owner = ledger.owner_handle
    trace_checker = ledger.register(owner, 'G12_TRACE_1',
                                    {'max_steps': 64, 'require_goal': False})
    bundle_checker = ledger.register(owner, 'EVIDENCE_BUNDLE_1', {})
    first = ledger.submit(trace_checker, *trace_input(2))['receipt']
    duplicate = ledger.submit(trace_checker, *trace_input(2))['receipt']
    child = ledger.bundle(bundle_checker, [first])['receipt']
    memory, archive = TrustedMemory(ledger), BehaviorArchive(ledger)
    memory.add(child)
    archive.add(first)
    cached = memory.prepare(ENVIRONMENT)
    dataset = memory.dataset([child], ENVIRONMENT)
    before = {'retrieval': len(memory.read(ENVIRONMENT)),
              'archive_cells': len(archive.cells()),
              'dataset_rows': len(memory.validate_dataset(dataset))}
    ledger.change_trust(owner, 'receipt', first, 'QUARANTINED',
                        {'code': 'owner_investigation', 'evidence': []})
    codes = {}
    for name, action in (
            ('cached_context', lambda: memory.consume(cached)),
            ('dataset', lambda: memory.validate_dataset(dataset)),
            ('duplicate_submission', lambda: ledger.submit(
                trace_checker, *trace_input(2)))):
        try:
            action()
            codes[name] = 'UNEXPECTED_ACCEPT'
        except Rejected as error:
            codes[name] = str(error)
    after = {'retrieval': len(memory.read(ENVIRONMENT)),
             'archive_cells': len(archive.cells()),
             'dependent_status': ledger.status(child),
             'duplicate_status': ledger.status(duplicate), 'blocked': codes}
    new = ledger.revalidate(owner, first, trace_checker)['receipt']
    rebuilt = ledger.bundle(bundle_checker, [new])['receipt']
    repaired_dataset = memory.dataset([rebuilt], ENVIRONMENT)
    # A stricter replacement cannot inherit an old decision by name alone.
    paint = ledger.submit(trace_checker, *trace_input(actions=['paint']))
    strict = ledger.register(owner, 'G12_TRACE_1',
                             {'max_steps': 64, 'require_goal': True})
    strict_result = ledger.revalidate(owner, paint['receipt'], strict)
    ledger.change_trust(owner, 'checker', trace_checker, 'REVOKED',
                        {'code': 'replace_protocol', 'evidence': []})
    replacement = ledger.revalidate(owner, new, strict)['receipt']
    renewal = ledger.bundle(bundle_checker, [replacement])['receipt']
    final_dataset = memory.dataset([renewal], ENVIRONMENT)
    memory.export_dataset(final_dataset, output / 'dataset.json')
    report = {
        'mode': 'LOCAL_TRUST_SCENARIO_NOT_LLM',
        'before': before, 'after': after,
        'old_receipt_still_quarantined': ledger.status(first)['status'],
        'revalidated_receipt_has_new_id': new != first,
        'repaired_rows_before_checker_retirement':
        len(repaired_dataset['body']['rows']),
        'stricter_checker_rejects_paint': strict_result,
        'replacement_checker_dataset_rows': len(final_dataset['body']['rows']),
        'exported_dataset': {'path': 'dataset.json', 'id': final_dataset['id'],
                             'rows': len(final_dataset['body']['rows'])},
        'identity': ledger.identity, 'journal_head': ledger.head,
        'public_fixture_key': FIXTURE_KEY.decode('ascii'),
    }
    ledger.close()
    replayed = EvidenceLedger.replay(path, FIXTURE_KEY, report['identity'],
                                     report['journal_head'])
    report['replay'] = {key: value for key, value in replayed.items()
                        if key != 'state'}
    assert before == {'retrieval': 1, 'archive_cells': 1, 'dataset_rows': 1}
    assert after['retrieval'] == after['archive_cells'] == 0
    assert set(codes.values()) == {'STALE'}
    assert strict_result['status'] == 'REJECTED'
    return report


def budget_sweep():
    config = json.loads((ROOT / 'configs/fixture.json').read_text())
    route = Route(**config['route'])
    settings = make_plan(config, check_sources(),
                         FixtureProvider.mode)['settings']
    rows = []
    episodes = 0
    for cap in (4, 10, 20, 40, 64):
        by_condition = {}
        for condition in CONDITIONS:
            results = []
            for level in range(1, 13):
                slot = {'case': level - 1, 'level': level,
                        'condition': condition, 'model_seed': 1000 + level}
                result = run_episode(
                    slot, dict(settings, max_calls=cap), route,
                    FixtureProvider(route), MemoryJournal(), check_sources())
                results.append(result)
                episodes += 1
            by_condition[condition] = {
                'successes': sum(row['success'] for row in results),
                'runs': len(results),
                'mean_calls': mean(row['calls'] for row in results),
                'mean_utility_microusd': mean(
                    row['net_utility_microusd'] for row in results),
                'total_cost_microusd': sum(
                    row['accounted_cost_microusd'] for row in results),
            }
        rows.append({'max_calls': cap, 'conditions': by_condition})
    faults = []
    for failure in ('timeout', 'missing_usage', 'bad_json', 'model_drift',
                    'overrun', 'paint'):
        for condition in CONDITIONS:
            slot = {'case': 0, 'level': 3, 'condition': condition,
                    'model_seed': 1000}
            result = run_episode(slot, settings, route,
                                 FixtureProvider(route, failure),
                                 MemoryJournal(), check_sources())
            faults.append({'failure': failure, 'condition': condition,
                           'success': result['success'],
                           'calls': result['calls'],
                           'cost_microusd': result['accounted_cost_microusd'],
                           'contract_violated':
                           result['provider_contract_violated']})
            episodes += 1
    return {'mode': 'EXHAUSTIVE_SCRIPTED_G12_NOT_LLM', 'episodes': episodes,
            'sampling': 'all 12 levels per condition and call cap; '
            'exact finite deterministic fixture, not an IID LLM sample',
            'budget_sweep': rows, 'faults': faults}


def trust_model_check(output):
    '''Check all status combinations of two leaves and one bundle.'''
    cases = 0
    queries = 0
    statuses = ('ACTIVE', 'QUARANTINED', 'REVOKED')
    directory = output / 'trust-model'
    directory.mkdir()
    for combination in itertools.product(statuses, repeat=5):
        ledger = EvidenceLedger(directory / (str(cases) + '.jsonl'),
                                FIXTURE_KEY, check_sources())
        owner = ledger.owner_handle
        proof = ledger.register(owner, 'F2_PROOF_1', {'fuel': 100})
        bundler = ledger.register(owner, 'EVIDENCE_BUNDLE_1', {})
        roots = []
        for atom in ('P', 'Q'):
            goal = ['imp', ['atom', atom], ['atom', atom]]
            artifact = {'goal': goal, 'library': {},
                        'term': ['lam', ['atom', atom], ['var', 0]]}
            result = ledger.submit(proof, artifact, {
                'kind': 'Proposition', 'goal': digest('Formula', goal),
            }, {'library': cid('ProofLibrary', {})})
            roots.append(result['receipt'])
        roots.append(ledger.bundle(bundler, roots)['receipt'])
        targets = [('receipt', key) for key in roots]
        targets.extend([('checker', proof), ('checker', bundler)])
        for (kind, identifier), status in zip(targets, combination):
            if status != 'ACTIVE':
                ledger.change_trust(owner, kind, identifier, status,
                                    {'code': 'bounded_exploration',
                                     'evidence': []})
        # Independently stated Boolean eligibility for this exact topology.
        a, b, c, p, q = (value == 'ACTIVE' for value in combination)
        expected = [a and p, b and p, a and b and c and p and q]
        scope = ledger.receipt(roots[0])['scope']
        for identifier, eligible in zip(roots, expected):
            assert bool(ledger.select([identifier], scope)) == eligible
            queries += 1
            for purpose in ('retrieval', 'training', 'publish'):
                try:
                    ledger.authorize([identifier], scope, purpose)
                    allowed = True
                except Rejected:
                    allowed = False
                assert allowed == eligible
                queries += 1
        ledger.close()
        cases += 1
    return {'configurations': cases, 'consumer_queries': queries,
            'mismatches': 0,
            'scope': '2 distinct proof leaves, 1 bundle, 2 checkers; '
            '3 lifecycle states per object, every combination',
            'general_theorem': False}


def statistics_calibration():
    rows = []
    for n in (5, 20, 100):
        for probability in (0.0, 0.1, 0.5, 0.9, 0.95, 1.0):
            coverage = {'mean': 0.0, 'q10': 0.0, 'lower_cvar': 0.0}
            truth = {'mean': probability,
                     'q10': 0 if probability <= 0.9 else 1,
                     'lower_cvar': max(0.0, (probability - 0.9) / 0.1)}
            for successes in range(n + 1):
                mass = (math.comb(n, successes) * probability ** successes
                        * (1 - probability) ** (n - successes))
                if mass == 0:
                    continue
                values = [0] * (n - successes) + [1] * successes
                intervals = {
                    'mean': bounded_mean_interval(values, 0, 1),
                    'q10': quantile_interval(values, 0.1, 0, 1),
                    'lower_cvar': tail_interval(values, 0, 1),
                }
                for metric, interval in intervals.items():
                    if (interval[0] - 1e-12 <= truth[metric]
                            <= interval[1] + 1e-12):
                        coverage[metric] += mass
            assert min(coverage.values()) >= 0.95 - 1e-10
            rows.append({'n': n, 'bernoulli_p': probability,
                         'exact_coverage': coverage})
    # Sufficient worst-case n for confidence radius, not a power guarantee.
    planning = []
    alpha = 0.05 / 9
    for radius in (0.1, 0.05, 0.01):
        mean_n = math.ceil(2 * math.log(2 / alpha) / radius ** 2)
        tail_n = math.ceil(2 * math.log(4 / alpha) / (0.1 * radius) ** 2)
        planning.append({'desired_difference_half_width': radius,
                         'paired_mean_sufficient_n': mean_n,
                         'lower_cvar_sufficient_n': tail_n})
    return {'mode': 'EXACT_BINOMIAL_ENUMERATION_NOT_LLM',
            'individual_interval_coverage': rows,
            'planning': planning, 'planning_utility_support_width': 1,
            'planning_warning': 'Worst-case concentration bounds; '
            'not empirical power estimates. Wider utility support scales n '
            'quadratically. Real LLM variance, dependence, and costs unknown.'}


def run_offline(output):
    output = Path(output).resolve()
    need_outside = output != ROOT and ROOT not in output.parents
    if not need_outside:
        raise ValueError('Output must be outside the source snapshot')
    source = check_sources()
    output.mkdir(parents=True, exist_ok=False)
    report = {'source_manifest': source,
              'trust': trust_scenario(output),
              'trust_model': trust_model_check(output),
              'execution': budget_sweep(),
              'statistics': statistics_calibration(),
              'llm_api_calls': 0, 'llm_quality_evidence': False}
    assert check_sources() == source
    (output / 'offline-report.json').write_text(json.dumps(report, indent=2)
                                                + '\n')
    return report
