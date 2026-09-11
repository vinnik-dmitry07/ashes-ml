'''Repeat whole searches, freeze every choice, then open committed holdouts.'''

from copy import deepcopy
import json
from pathlib import Path
import time

from ahsl.codec import Rejected, canonical, need
from .experiment import ROOT, check_sources
from .protocol import Journal, digest, read_journal
from .search_protocol import (
    FIXED, METHODS, SEARCH_METHODS, SEARCH_SEED, best, candidate_id,
    make_search_plan,
    measure, proposal_packet, propose, reserve_evaluation,
    validate_candidate, validate_plan, validate_reveal,
)
from .search_statistics import summarize_search


class Events:
    def __init__(self, journal=None):
        self.journal = journal
        self.records = []

    def emit(self, kind, value):
        record = {'kind': kind, 'value': deepcopy(value)}
        canonical(record)
        if self.journal is not None:
            self.journal.append(kind, value)
        self.records.append(record)


def evaluate(plan, fold, method, candidate, levels, index, phase, events):
    reserve = reserve_evaluation(candidate, len(levels))
    binding = {'fold': fold['fold'], 'method': method,
               'index': index, 'phase': phase}
    events.emit('evaluation_start', dict(
        binding, candidate=candidate, id=candidate_id(candidate),
        reserved_units=reserve))
    result = measure(plan, fold, candidate, levels, index, phase)
    events.emit('evaluation_end', dict(binding, result=result))
    return result


def search_one(plan, fold, method, events, proposer):
    config = plan['config']
    spent, proposals = 0, 0
    history = []
    reason = 'PROPOSAL_LIMIT' if method in SEARCH_METHODS else 'FIXED'
    if method in SEARCH_METHODS:
        for index in range(config['max_proposals']):
            if spent + 2 > config['search_budget_units']:
                reason = 'BUDGET'
                break
            packet = proposal_packet(plan, fold, method, index, history)
            events.emit('proposal_start', {
                'fold': fold['fold'], 'method': method, 'index': index,
                'packet': packet, 'charged_units': 2,
            })
            spent += 2
            proposals += 1
            rejection = None
            try:
                candidate = validate_candidate(proposer(deepcopy(packet)))
            except Rejected as error:
                candidate, rejection = None, str(error)
            except Exception:
                candidate, rejection = None, 'PROPOSER_ERROR'
            events.emit('proposal_end', {
                'fold': fold['fold'], 'method': method, 'index': index,
                'candidate': candidate, 'rejection': rejection,
            })
            if candidate is None:
                continue
            reserve = reserve_evaluation(candidate, config['search_tasks'])
            if spent + reserve > config['search_budget_units']:
                reason = 'RESERVE_DOES_NOT_FIT'
                break
            result = evaluate(plan, fold, method, candidate,
                              fold['training_levels'], index, 'search', events)
            spent += result['units']
            history.append(result)
            if result['contract_violated']:
                reason = 'PROVIDER_CONTRACT_VIOLATION'
                break
    chosen = FIXED if method == 'fixed' else (
        best(history)['candidate'] if history else SEARCH_SEED)
    frozen = {'fold': fold['fold'], 'method': method,
              'candidate': deepcopy(chosen), 'id': candidate_id(chosen),
              'search_units': spent, 'evaluations': len(history),
              'proposals': proposals, 'stop_reason': reason,
              'fallback': method in SEARCH_METHODS and not history}
    events.emit('selection_frozen', frozen)
    return frozen


def search_all(plan, events, proposer=propose):
    validate_plan(plan)
    events.emit('study_start', {'plan': digest('SearchPlan', plan)})
    frozen = []
    for fold in plan['folds']:
        for method in METHODS:
            frozen.append(search_one(plan, fold, method, events, proposer))
    identifier = digest('FrozenSelections', frozen)
    events.emit('all_selections_frozen', {'id': identifier,
                                          'count': len(frozen)})
    return frozen, identifier


def evaluate_holdout(plan, reveal, frozen, frozen_id, events):
    need(events.records and events.records[-1] == {
        'kind': 'all_selections_frozen',
        'value': {'id': frozen_id, 'count': len(frozen)},
    }, 'PHASE')
    need(digest('FrozenSelections', frozen) == frozen_id, 'INTEGRITY')
    need(len(frozen) == len(plan['folds']) * len(METHODS), 'INTEGRITY')
    validate_reveal(plan, reveal)
    events.emit('holdout_opened', {'reveal': reveal,
                                   'frozen_selections': frozen_id})
    for entry in frozen:
        candidate = entry['candidate']
        need(candidate_id(candidate) == entry['id'], 'INTEGRITY')
        fold = plan['folds'][entry['fold']]
        evaluate(plan, fold, entry['method'], candidate,
                 reveal['holdout_levels'][entry['fold']],
                 100 + METHODS.index(entry['method']), 'holdout', events)
    events.emit('study_end', {'folds': len(plan['folds']),
                              'evaluated_selections': len(frozen)})


def run_search_study(config, output):
    output = Path(output).resolve()
    need(output != ROOT and ROOT not in output.parents, 'PRECONDITION')
    source = check_sources()
    plan, reveal = make_search_plan(config, source)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'plan.json').write_bytes(canonical(plan))
    identity = {'study': digest('SearchPlan', plan)}
    journal = Journal(output / 'events.jsonl', identity)
    events = Events(journal)
    started = time.monotonic()
    error = None
    try:
        frozen, identifier = search_all(plan, events)
        need(check_sources() == source, 'INTEGRITY')
        evaluate_holdout(plan, reveal, frozen, identifier, events)
        need(check_sources() == source, 'INTEGRITY')
    except BaseException as failure:
        error = type(failure).__name__
        raise
    finally:
        journal.close()
        report = summarize_search(plan, events.records)
        report.update({'journal_head': journal.head,
                       'plan_id': identity['study'], 'error': error,
                       'elapsed_seconds': time.monotonic() - started})
        if error is not None:
            report['status'] = 'INCOMPLETE'
            report['inference_available'] = False
            report['comparisons'] = {}
        (output / 'summary.json').write_text(json.dumps(report, indent=2)
                                             + '\n')
    return report


def replay_search_study(output, expected_head):
    output = Path(output)
    source = check_sources()
    plan = json.loads((output / 'plan.json').read_text())
    validate_plan(plan)
    need(plan['source_manifest'] == source, 'INTEGRITY')
    identity = {'study': digest('SearchPlan', plan)}
    supplied = read_journal(output / 'events.jsonl', identity, expected_head)
    records = [{'kind': row['kind'], 'value': row['value']}
               for row in supplied]
    expected = Events()
    frozen, identifier = search_all(plan, expected)
    search_count = len(expected.records)
    prefix = min(len(records), search_count)
    need(records[:prefix] == expected.records[:prefix], 'INTEGRITY')
    if len(records) > search_count:
        reveal_event = records[search_count]
        need(reveal_event['kind'] == 'holdout_opened', 'PHASE')
        evaluate_holdout(plan, reveal_event['value']['reveal'],
                         frozen, identifier, expected)
        need(records == expected.records[:len(records)], 'INTEGRITY')
    need(check_sources() == source, 'INTEGRITY')
    report = summarize_search(plan, records)
    return {'status': report['status'], 'events': len(records),
            'requested_pipeline_runs': report['requested_pipeline_runs'],
            'completed_pipeline_runs': report['completed_pipeline_runs'],
            'requested_optimization_runs':
            report['requested_optimization_runs'],
            'journal_head': expected_head,
            'summary_digest': digest('SearchSummaryJSON', json.dumps({
                'status': report['status'], 'runs': report['runs'],
                'ledger': report['ledger'],
            }, sort_keys=True, separators=(',', ':'), allow_nan=False))}
