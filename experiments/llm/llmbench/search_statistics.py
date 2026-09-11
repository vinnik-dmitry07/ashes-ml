'''Report whole-search variability, discovery cost, and paired comparisons.'''

from statistics import mean

from ahsl.codec import rat
from .search_protocol import METHODS, SEARCH_METHODS
from .statistics import bounded_mean_interval, tail_interval, tail_mean


def summarize_search(plan, records):
    config = plan['config']
    count = config['repetitions']
    horizon = config['deployment_horizon']
    value = config['success_value_units']
    holdout_budget = config['holdout_tasks'] * 81
    lower = -81 - (config['search_budget_units'] + holdout_budget) / horizon
    ledgers = {(fold, method): {'search': 0, 'holdout': 0, 'proposals': 0}
               for fold in range(count) for method in METHODS}
    pending, tested, selected = {}, {}, {}
    violated = False
    for record in records:
        kind, event = record['kind'], record['value']
        if kind == 'proposal_start':
            ledger = ledgers[event['fold'], event['method']]
            ledger['search'] += event['charged_units']
            ledger['proposals'] += 1
        elif kind == 'evaluation_start':
            key = (event['fold'], event['method'], event['phase'],
                   event['index'])
            pending[key] = event['reserved_units']
            ledgers[key[:2]][event['phase']] += event['reserved_units']
        elif kind == 'evaluation_end':
            key = (event['fold'], event['method'], event['phase'],
                   event['index'])
            result = event['result']
            ledgers[key[:2]][event['phase']] += (result['units']
                                                 - pending.pop(key))
            violated |= result['contract_violated']
            if event['phase'] == 'holdout':
                tested[key[:2]] = result
        elif kind == 'selection_frozen':
            selected[event['fold'], event['method']] = event
    requested = count * len(METHODS)
    complete = (bool(records) and records[-1]['kind'] == 'study_end'
                and len(tested) == requested and not pending)
    inference = complete and not violated and count >= 2
    runs = []
    for (fold, method), ledger in ledgers.items():
        result = tested.get((fold, method))
        successes = sum(row['success'] for row in result['rows']) if (
            result is not None) else 0
        failure_rate = 1 - successes / config['holdout_tasks']
        bad_search = failure_rate > rat(config['failure_threshold'])
        units = result['units'] if result is not None else holdout_budget
        execution = units / config['holdout_tasks']
        discovery = ledger['search'] + ledger['holdout']
        utility = (value * (1 - failure_rate) - execution
                   - discovery / horizon) if result is not None else lower
        runs.append({'fold': fold, 'method': method,
                     'completed': result is not None,
                     'selected': selected.get((fold, method), {}).get('id'),
                     'search_units': ledger['search'],
                     'measurement_units': ledger['holdout'],
                     'discovery_units': discovery,
                     'mean_execution_units': execution,
                     'successes': successes,
                     'test_cases': config['holdout_tasks'],
                     'failure_rate': failure_rate, 'bad_search': bad_search,
                     'net_value_units': utility})
    aggregates = {}
    for method in METHODS:
        rows = [row for row in runs if row['method'] == method]
        utilities = [row['net_value_units'] for row in rows]
        failures = [int(row['bad_search']) for row in rows]
        aggregates[method] = {
            'completed': sum(row['completed'] for row in rows),
            'requested': count,
            'mean_search_units': mean(row['search_units'] for row in rows),
            'mean_discovery_units': mean(
                row['discovery_units'] for row in rows),
            'mean_failure_rate': mean(row['failure_rate'] for row in rows),
            'bad_search_rate': mean(failures),
            'mean_net_value_units': mean(utilities),
            'lower_10_percent_mean': tail_mean(utilities),
        }
    comparisons = {}
    if inference:
        alpha = 0.05 / 9
        by_key = {(row['fold'], row['method']): row for row in runs}
        chosen = [by_key[fold, 'hill_climb'] for fold in range(count)]
        chosen_values = [row['net_value_units'] for row in chosen]
        for baseline in ('fixed', 'seed_fixed', 'independent'):
            other = [by_key[fold, baseline] for fold in range(count)]
            other_values = [row['net_value_units'] for row in other]
            gains = [a - b for a, b in zip(chosen_values, other_values)]
            risk = [int(a['bad_search']) - int(b['bad_search'])
                    for a, b in zip(chosen, other)]
            tail_a = tail_interval(chosen_values, lower, value, alpha / 2)
            tail_b = tail_interval(other_values, lower, value, alpha / 2)
            comparisons[baseline] = {
                'mean_net_gain': mean(gains),
                'simultaneous_mean_gain_interval': bounded_mean_interval(
                    gains, lower - value, value - lower, alpha),
                'bad_search_rate_difference': mean(risk),
                'simultaneous_bad_search_difference_interval':
                bounded_mean_interval(risk, -1, 1, alpha),
                'lower_10_percent_gain': (tail_mean(chosen_values)
                                          - tail_mean(other_values)),
                'simultaneous_lower_10_percent_gain_interval': [
                    tail_a[0] - tail_b[1], tail_a[1] - tail_b[0]],
            }
    ledger = {'search_units': sum(row['search'] for row in ledgers.values()),
              'measurement_units': sum(row['holdout']
                                       for row in ledgers.values()),
              'pending_evaluations': len(pending),
              'pending_reserved_units': sum(pending.values()),
              'proposal_attempts': sum(row['proposals']
                                       for row in ledgers.values())}
    return {
        'status': 'PROVIDER_CONTRACT_VIOLATION' if violated else (
            'COMPLETE' if complete else 'INCOMPLETE'),
        'mode': 'SCRIPTED_SEARCH_FIXTURE_NOT_LLM',
        'quality_evidence_from_llm': False, 'external_llm_api_calls': 0,
        'source_manifest': plan['source_manifest'],
        'requested_pipeline_runs': requested,
        'completed_pipeline_runs': len(tested),
        'requested_optimization_runs': count * len(SEARCH_METHODS),
        'completed_optimization_runs': sum(
            key[1] in SEARCH_METHODS for key in tested),
        'repetitions_per_method': count,
        'inference_available': inference, 'runs': runs, 'methods': aggregates,
        'comparisons': comparisons, 'ledger': ledger,
        'unit': 'Declared fixture work units: 1 proposal + 1 validation; '
        '1 per episode + model calls + checked transitions. Not USD or FLOPs.',
        'sampling': 'Paired methods within each randomized level split. '
        'The whole search is the uncertainty unit; within-run tasks are '
        'not independent search repetitions. Public 12-level fixture only.',
        'uncertainty': 'Hoeffding and DKW, conditional on independent outer '
        'repetitions from the specified fixture sampling. Nine comparisons '
        'use Bonferroni; incomplete studies disable inference.',
        'utility': 'success_value * holdout_success_rate - mean_execution '
        '- (search + holdout_measurement) / preregistered_deployment_horizon',
    }
