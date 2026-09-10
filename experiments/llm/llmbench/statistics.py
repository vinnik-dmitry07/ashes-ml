'''Bounded estimates with explicit sampling assumptions and wide intervals.'''

import math
from statistics import mean

from ahsl.codec import need
from .protocol import CONDITIONS, digest


def quantile(values, probability, lower, upper):
    if probability <= 0:
        return lower
    if probability > 1:
        return upper
    return sorted(values)[max(0, math.ceil(len(values) * probability) - 1)]


def tail_mean(values, fraction=0.1):
    values = sorted(values)
    mass = len(values) * fraction
    count = int(mass)
    total = sum(values[:count])
    if count < len(values):
        total += (mass - count) * values[count]
    return total / mass


def dkw_epsilon(count, alpha=0.05):
    return math.sqrt(math.log(2 / alpha) / (2 * count))


def bounded_mean_interval(values, lower, upper, alpha=0.05):
    radius = (upper - lower) * dkw_epsilon(len(values), alpha)
    center = mean(values)
    return [max(lower, center - radius), min(upper, center + radius)]


def quantile_interval(values, probability, lower, upper, alpha=0.05):
    epsilon = dkw_epsilon(len(values), alpha)
    return [quantile(values, probability - epsilon, lower, upper),
            quantile(values, probability + epsilon, lower, upper)]


def tail_interval(values, lower, upper, alpha=0.05, fraction=0.1):
    # CVaR_lower = sup_t [t - E[(t-X)+] / fraction]. A DKW bound eps
    # bounds the expectation error by (upper-lower)*eps uniformly in t.
    radius = (upper - lower) * dkw_epsilon(len(values), alpha) / fraction
    center = tail_mean(values, fraction)
    return [max(lower, center - radius), min(upper, center + radius)]


def summarize(plan, results, mode, completed=True):
    by_run = {row['run']: row for row in results}
    need(len(by_run) == len(results), 'DUPLICATE')
    slots = plan['slots']
    need(set(by_run) <= {digest('Slot', slot) for slot in slots}, 'INTEGRITY')
    budget = plan['settings']['run_budget_microusd']
    value = plan['settings']['success_value_microusd']
    lower, upper = -budget, value
    missing = len(slots) - len(results)
    violated = any(row['provider_contract_violated'] for row in results)
    valid = completed and not missing and not violated
    rows = {}
    for condition in CONDITIONS:
        selected = []
        done = []
        for slot in slots:
            if slot['condition'] != condition:
                continue
            result = by_run.get(digest('Slot', slot))
            if result is not None:
                done.append(result)
            # Missing requested runs remain in the denominator and disable
            # inference. Their utility is conservatively imputed.
            selected.append(result if result is not None else {
                'success': False, 'net_utility_microusd': lower,
            })
        utilities = [item['net_utility_microusd'] for item in selected]
        failures = [int(not item['success']) for item in selected]
        elapsed = [item['elapsed_ms'] for item in done]
        rows[condition] = {
            'requested': len(selected), 'completed': len(done),
            'successes': len(selected) - sum(failures),
            'failure_rate': mean(failures),
            'mean_net_utility_microusd': mean(utilities),
            'q10_net_utility_microusd': quantile(utilities, 0.1, lower, upper),
            'worst_10_percent_mean_microusd': tail_mean(utilities),
            'mean_95_interval': bounded_mean_interval(utilities, lower, upper)
            if valid else None,
            'failure_95_interval': bounded_mean_interval(failures, 0, 1)
            if valid else None,
            'q10_95_dkw_interval': quantile_interval(
                utilities, 0.1, lower, upper) if valid else None,
            'worst_10_percent_95_dkw_interval': tail_interval(
                utilities, lower, upper) if valid else None,
            'accounted_cost_completed_runs_microusd': sum(
                item['accounted_cost_microusd'] for item in done),
            'calls_completed_runs_including_selection_and_planning': sum(
                item['calls'] for item in done),
            'unknown_cost_calls_completed_runs': sum(
                item['unknown_cost_calls'] for item in done),
            'mean_elapsed_ms_completed_runs': mean(elapsed) if done else None,
            'q95_elapsed_ms_completed_runs': quantile(
                elapsed, 0.95, 0, max(elapsed)) if done else None,
        }
    comparisons = {}
    if valid:
        cases = sorted({slot['case'] for slot in slots})
        paired = {(row['slot']['case'], row['slot']['condition']): row
                  for row in results}
        # Three baselines x three metrics: Bonferroni family-wise 95%.
        alpha = 0.05 / 9
        for baseline in CONDITIONS[:3]:
            gains, failure_differences = [], []
            chosen_values, fixed_values = [], []
            for case in cases:
                selector = paired[case, 'selector']
                fixed = paired[case, baseline]
                chosen_values.append(selector['net_utility_microusd'])
                fixed_values.append(fixed['net_utility_microusd'])
                gains.append(chosen_values[-1] - fixed_values[-1])
                failure_differences.append(int(not selector['success'])
                                           - int(not fixed['success']))
            span = upper - lower
            chosen_tail = tail_interval(
                chosen_values, lower, upper, alpha / 2)
            fixed_tail = tail_interval(
                fixed_values, lower, upper, alpha / 2)
            comparisons[baseline] = {
                'mean_gain_microusd': mean(gains),
                'simultaneous_mean_gain_interval': bounded_mean_interval(
                    gains, -span, span, alpha),
                'failure_rate_difference': mean(failure_differences),
                'simultaneous_failure_difference_interval':
                bounded_mean_interval(failure_differences, -1, 1, alpha),
                'worst_10_percent_gain_microusd': (
                    tail_mean(chosen_values) - tail_mean(fixed_values)),
                'simultaneous_worst_10_percent_gain_interval': [
                    chosen_tail[0] - fixed_tail[1],
                    chosen_tail[1] - fixed_tail[0]],
            }
    status = 'COMPLETE' if valid else 'INCOMPLETE'
    if violated:
        status = 'PROVIDER_CONTRACT_VIOLATION'
    return {
        'status': status,
        'provider_mode': mode,
        'quality_evidence_from_llm': mode == 'LIVE_HTTP' and valid,
        'sampling_assumptions': 'Independent cases from the pinned uniform '
        'level distribution; stationary provider; no adaptive test feedback. '
        'Pairing is by case. Shared seeds do not prove identical randomness.',
        'intervals': 'Hoeffding for means and risks; DKW for q10 and lower '
        'CVaR. Nine simultaneous comparison intervals use Bonferroni. '
        'Sampling-conditional, not deployment guarantees. No automatic '
        'publication or certificate of selector superiority.',
        'missing_requested_runs': missing,
        'provider_contract_violated': violated,
        'conditions': rows, 'selector_minus_baseline': comparisons,
    }
