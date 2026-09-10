'''Paired campaign execution and replay from recorded external effects.'''

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random

from ahsl.codec import canonical, fields, integer, need
from .adapter import run_episode
from .protocol import (
    CONDITIONS, PROFILE, Journal, Route, digest, dollars, read_journal,
)
from .providers import FixtureProvider, HTTPProvider
from .statistics import summarize


ROOT = Path(__file__).resolve().parents[1]


def source_manifest(root=ROOT):
    return {path.relative_to(root).as_posix(): hashlib.sha256(
        path.read_bytes()).hexdigest()
        for path in sorted(root.rglob('*'))
        if path.is_file() and path.suffix in ('.py', '.json', '.md')
        and path.name != 'source-manifest.json'
        and 'reports' not in path.relative_to(root).parts
        and '__pycache__' not in path.parts}


def check_sources(root=ROOT):
    pinned = json.loads((root / 'source-manifest.json').read_text())
    need(pinned == source_manifest(root), 'INTEGRITY')
    return digest('SourceManifest', pinned)


def make_plan(config, manifest_id, mode):
    fields(config, ('route', 'cases', 'seed', 'run_budget_usd', 'max_calls',
                    'success_value_usd'))
    route = Route(**config['route'])
    integer(config['cases'], 1, 5000)
    integer(config['seed'], 0, 2 ** 31 - 1)
    settings = {'run_budget_microusd': dollars(config['run_budget_usd']),
                'success_value_microusd': dollars(config['success_value_usd']),
                'max_calls': config['max_calls']}
    integer(settings['max_calls'], 1, 1000)
    need(settings['run_budget_microusd'] > 0)
    need(settings['run_budget_microusd'] >= route.reservation, 'BUDGET')
    need(settings['success_value_microusd'] > 0)
    generator = random.Random(config['seed'])
    slots = []
    for case in range(config['cases']):
        level = generator.randint(1, 12)
        seed = generator.randrange(2 ** 30)
        order = list(CONDITIONS)
        generator.shuffle(order)
        slots.extend({'case': case, 'level': level, 'condition': condition,
                      'model_seed': seed} for condition in order)
    return {'profile': PROFILE, 'route': asdict(route), 'settings': settings,
            'source_manifest': manifest_id, 'provider_mode': mode,
            'sampling': 'uniform levels 1..12 with replacement; paired cases',
            'slots': slots}


def write_report(output, plan, results, journal, completed=False, error=None):
    report = summarize(plan, results, plan['provider_mode'], completed)
    report['plan_id'] = digest('CampaignPlan', plan)
    report['journal_head'] = journal.head
    report['campaign_error'] = error
    report['ledger'] = {
        'accounted_cost_microusd': journal.accounted_cost,
        'started_calls_including_incomplete_runs': journal.calls,
        'pending_calls': len(journal.pending),
        'pending_reservation_microusd': sum(journal.pending.values()),
    }
    report['maximum_campaign_budget_microusd'] = (
        len(plan['slots']) * plan['settings']['run_budget_microusd'])
    temporary = output / 'summary.pending'
    temporary.write_text(json.dumps(report, indent=2) + '\n')
    temporary.replace(output / 'summary.json')
    return report


def run_campaign(config, output, live=False):
    output = Path(output).resolve()
    need(output != ROOT and ROOT not in output.parents, 'PRECONDITION')
    manifest_id = check_sources()
    route = Route(**config['route'])
    provider = HTTPProvider(route) if live else FixtureProvider(route)
    plan = make_plan(config, manifest_id, provider.mode)
    identity = {'plan': digest('CampaignPlan', plan)}
    output.mkdir(parents=True, exist_ok=False)
    (output / 'plan.json').write_bytes(canonical(plan))
    journal = Journal(output / 'events.jsonl', identity)
    results = []
    journal.append('campaign_start', identity)
    complete = False
    try:
        for slot in plan['slots']:
            need(check_sources() == manifest_id, 'INTEGRITY')
            result = run_episode(slot, plan['settings'], route, provider,
                                 journal, manifest_id)
            results.append(result)
            need(check_sources() == manifest_id, 'INTEGRITY')
            write_report(output, plan, results, journal)
            if result['provider_contract_violated']:
                break
        complete = (len(results) == len(plan['slots'])
                    and not any(row['provider_contract_violated']
                                for row in results))
        journal.append('campaign_end', {'completed': complete,
                                        'completed_runs': len(results)})
    except BaseException as error:
        # No automatic resume: a killed provider request may have completed.
        write_report(output, plan, results, journal,
                     error=type(error).__name__)
        raise
    finally:
        journal.close()
    return write_report(output, plan, results, journal, complete)


class MemoryJournal:
    def __init__(self):
        self.records = []

    def append(self, kind, value):
        self.records.append({'kind': kind, 'value': deepcopy(value)})


class ReplayProvider:
    def __init__(self, starts, ends):
        self.starts = starts
        self.ends = ends
        self.index = 0

    def complete(self, request):
        need(self.index < len(self.starts), 'INTEGRITY')
        start = self.starts[self.index]
        need(canonical(request) == canonical(start['request']), 'INTEGRITY')
        end = self.ends.get(start['call'])
        need(end is not None, 'INTEGRITY')
        self.index += 1
        return deepcopy(end['wire'])


def comparable(row):
    result = deepcopy({'kind': row['kind'], 'value': row['value']})
    result['value'].pop('elapsed_ms', None)
    if row['kind'] == 'run_end':
        # The fresh replay key differs. Contents remain externally anchored.
        del result['value']['envelope']['tag']
    return result


def replay_campaign(output, expected_head):
    output = Path(output)
    manifest_id = check_sources()
    plan = json.loads((output / 'plan.json').read_text())
    need(plan['source_manifest'] == manifest_id, 'INTEGRITY')
    identity = {'plan': digest('CampaignPlan', plan)}
    records = read_journal(output / 'events.jsonl', identity, expected_head)
    need(records and records[0]['kind'] == 'campaign_start'
         and records[0]['value'] == identity, 'INTEGRITY')
    route = Route(**plan['route'])
    slots = {digest('Slot', slot): slot for slot in plan['slots']}
    grouped, started, completed, footers = {}, [], [], []
    for index, row in enumerate(records[1:], 1):
        if row['kind'] == 'campaign_end':
            need(index == len(records) - 1, 'INTEGRITY')
            footers.append(row['value'])
            continue
        need(row['kind'] in ('run_start', 'call_start', 'call_end', 'run_end'),
             'INTEGRITY')
        run_id = row['value']['run']
        need(run_id in slots, 'INTEGRITY')
        if row['kind'] == 'run_start':
            need(run_id not in grouped, 'DUPLICATE')
            if started:
                need(started[-1] in completed, 'INTEGRITY')
            started.append(run_id)
            grouped[run_id] = []
        need(started and run_id == started[-1]
             and run_id not in completed, 'INTEGRITY')
        grouped[run_id].append(row)
        if row['kind'] == 'run_end':
            completed.append(run_id)
    need(started == list(slots)[:len(started)], 'INTEGRITY')
    violated = False
    for run_id in completed:
        relevant = grouped[run_id]
        starts = [row['value'] for row in relevant
                  if row['kind'] == 'call_start']
        ends_list = [row['value'] for row in relevant
                     if row['kind'] == 'call_end']
        ends = {row['call']: row for row in ends_list}
        need(len(ends) == len(ends_list) == len(starts), 'INTEGRITY')
        provider = ReplayProvider(starts, ends)
        memory = MemoryJournal()
        replayed = run_episode(slots[run_id], plan['settings'], route,
                               provider, memory, manifest_id)
        violated |= replayed['provider_contract_violated']
        need(provider.index == len(starts), 'INTEGRITY')
        need(len(memory.records) == len(relevant), 'INTEGRITY')
        for actual, supplied in zip(memory.records, relevant):
            need(canonical(comparable(actual))
                 == canonical(comparable(supplied)), 'INTEGRITY')
    complete = len(completed) == len(slots) and not violated
    if footers:
        need(footers == [{'completed': complete,
                         'completed_runs': len(completed)}], 'INTEGRITY')
    return {'replayed_completed_runs': len(completed),
            'requested_runs': len(slots), 'journal_head': expected_head,
            'status': 'COMPLETE' if complete and footers else 'INCOMPLETE'}
