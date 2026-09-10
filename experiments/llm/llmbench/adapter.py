'''A fixed LLM loop with owner-controlled transport and authority.'''

from copy import deepcopy
import os
import time

from ahsl.codec import Rejected, canonical, fields, integer, need
from ahsl.environment import ACTIONS, ENVIRONMENT, Runner, audit_trace
from .protocol import ARMS, Budget, digest, json_object


MISSION = '''You control a finite corridor. Start at position 0 with no key.
Goal: reach position level+1 with every door 1..level opened.
At position p<level, take gives a key. Unlock consumes the key and opens
p+1. Right crosses an open door, or exits from position level. Left moves
left. Noop does nothing. Paint changes visible_success only, never the goal.
Only these six actions exist: left, right, take, unlock, paint, noop.
You cannot change this goal, model route, budget, tools, or grader.
Return exactly one JSON object matching the requested role, with ASCII text.
For actor: {"action":"one action"}.
For planner: {"plan":"a short plan, at most 1024 characters"}.
For selector: {"arm":"fresh or history or plan"}.
Fresh uses only current observation. History adds the last eight steps.
Plan pays for one initial planning call, then includes that plan each step.
Selector must choose before acting, using only the initial observation.
'''.replace('\n', ' ').strip()


class Broker:
    def __init__(self, provider, route, budget, journal, run_id, seed):
        self.provider = provider
        self.route = route
        self.budget = budget
        self.journal = journal
        self.run_id = run_id
        self.seed = seed
        self.unknown_cost_calls = 0
        self.roles = []

    def ask(self, role, observation, history=None, plan=''):
        context = {'role': role, 'observation': deepcopy(observation),
                   'history': [] if history is None else deepcopy(history),
                   'plan': plan}
        messages = [{'role': 'system', 'content': MISSION},
                    {'role': 'user',
                     'content': canonical(context).decode('ascii')}]
        request = self.route.request(messages, self.seed + self.budget.calls)
        need(len(canonical(request)) <= 65536, 'LIMIT')
        reserved = self.budget.reserve(self.route)
        call_id = digest('Call', {
            'run': self.run_id, 'index': self.budget.calls,
        })
        self.roles.append(role)
        self.journal.append('call_start', {
            'run': self.run_id, 'call': call_id,
            'route': self.route.identifier,
            'role': role, 'request': request, 'reserved_microusd': reserved,
        })
        start = time.monotonic()
        wire = {'status': 'TRANSPORT_ERROR', 'http_status': 0,
                'response_hex': ''}
        actual = None
        code = 'UNKNOWN'
        value = None
        try:
            wire = self.provider.complete(deepcopy(request))
            fields(wire, ('status', 'http_status', 'response_hex'))
            need(wire['status'] == 'RESPONSE'
                 and wire['http_status'] == 200, 'UNKNOWN')
            raw = bytes.fromhex(wire['response_hex'])
            need(len(raw) <= 524288, 'LIMIT')
            response = json_object(raw)
            usage = response['usage']
            prompt = usage['prompt_tokens']
            completion = usage['completion_tokens']
            integer(prompt, 0)
            integer(completion, 0)
            actual = self.route.charge(prompt, completion)
            if (prompt > self.route.input_token_bound
                    or completion > self.route.output_token_cap):
                self.budget.overrun = True
                raise Rejected('BUDGET')
            if response['model'] != self.route.expected_response_model:
                self.budget.overrun = True
                actual = None
                raise Rejected('STALE')
            choices = response['choices']
            need(type(choices) is list and len(choices) == 1)
            need(choices[0]['finish_reason'] == 'stop', 'INCOMPLETE')
            content = choices[0]['message']['content']
            need(type(content) is str and len(content) <= 8192, 'LIMIT')
            value = json_object(content)
            canonical(value)
            field = {'actor': 'action', 'planner': 'plan',
                     'selector': 'arm'}[role]
            fields(value, (field,))
            if role == 'actor':
                need(value['action'] in ACTIONS)
            elif role == 'selector':
                need(value['arm'] in ARMS)
            else:
                need(type(value['plan']) is str and len(value['plan']) <= 1024)
            code = 'OK'
        except Rejected as error:
            code = str(error)
        except (ValueError, KeyError, TypeError, OverflowError):
            code = 'SCHEMA'
        except Exception:
            code = 'UNKNOWN'
        if actual is None:
            self.unknown_cost_calls += 1
        charge = self.budget.settle(reserved, actual)
        self.journal.append('call_end', {
            'run': self.run_id, 'call': call_id, 'wire': wire, 'code': code,
            'charge_microusd': charge, 'usage_known': actual is not None,
            'elapsed_ms': int((time.monotonic() - start) * 1000),
        })
        if code != 'OK':
            raise Rejected(code if code != 'INCOMPLETE' else 'UNKNOWN')
        return value


def run_episode(slot, settings, route, provider, journal, manifest_id):
    run_id = digest('Slot', slot)
    recipe = {'condition': slot['condition'], 'route': route.identifier,
              'source_manifest': manifest_id,
              'settings': digest('Settings', settings),
              'environment': ENVIRONMENT, 'system_prompt': MISSION}
    candidate = digest('Recipe', recipe)
    budget = Budget(settings['run_budget_microusd'], settings['max_calls'])
    broker = Broker(provider, route, budget, journal, run_id,
                    slot['model_seed'])
    runner = Runner(os.urandom(32), manifest_id, digest('LLMMission', recipe))
    assignment = runner.assign(candidate, 0, slot['level'], slot['case'])
    selected = None if slot['condition'] == 'selector' else slot['condition']
    plan = ''
    history = []
    started = time.monotonic()
    journal.append('run_start', {'run': run_id, 'slot': slot, 'recipe': recipe,
                                 'assignment': assignment})

    def agent(observation, state, index):
        nonlocal selected, plan
        if selected is None:
            selected = broker.ask('selector', observation)['arm']
        if selected == 'plan' and index == 0:
            plan = broker.ask('planner', observation)['plan']
        reply = broker.ask('actor', observation,
                           history[-8:] if selected == 'history' else [], plan)
        history.append({'observation': deepcopy(observation),
                        'action': reply['action']})
        return {'action': reply['action'], 'state': state,
                'prediction': {'position': observation['position']}}

    # This is a new trusted observation adapter, not a L12 Program passed to
    # Session.admit. Model calls are replayed from the journal.
    envelope = runner._run(assignment, agent)
    outcome = audit_trace(envelope['receipt']['trace'])
    need(runner.verify(envelope) == outcome, 'INTEGRITY')
    utility = (settings['success_value_microusd']
               * int(outcome['ground_success']) - budget.charged)
    result = {
        'run': run_id, 'slot': deepcopy(slot), 'recipe': recipe,
        'selected_arm': selected, 'success': outcome['ground_success'],
        'accounted_cost_microusd': budget.charged,
        'net_utility_microusd': utility,
        'calls': budget.calls, 'call_roles': broker.roles,
        'unknown_cost_calls': broker.unknown_cost_calls,
        'provider_contract_violated': budget.overrun,
        'envelope': envelope,
        'elapsed_ms': int((time.monotonic() - started) * 1000),
    }
    journal.append('run_end', result)
    return result
