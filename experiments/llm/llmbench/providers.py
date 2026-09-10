'''Live HTTP transport and explicitly labelled deterministic fixtures.'''

import json
import os
from pathlib import Path
import subprocess
import sys

from ahsl.codec import canonical, need
from .protocol import ARMS, json_object


class HTTPProvider:
    mode = 'LIVE_HTTP'

    def __init__(self, route):
        self.route = route
        need(bool(os.environ.get(route.key_env)), 'AUTHORITY')

    def complete(self, request):
        inherited = ('PATH', 'SYSTEMROOT', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
                     'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY')
        environment = {key: os.environ[key] for key in inherited
                       if key in os.environ}
        environment[self.route.key_env] = os.environ[self.route.key_env]
        payload = {'endpoint': self.route.endpoint,
                   'key_env': self.route.key_env,
                   'timeout_seconds': self.route.timeout_seconds,
                   'request_hex': canonical(request).hex()}
        worker = Path(__file__).with_name('http_worker.py')
        try:
            result = subprocess.run(
                [sys.executable, str(worker)], input=canonical(payload),
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=environment, timeout=self.route.timeout_seconds,
                check=False)
        except subprocess.TimeoutExpired:
            return {'status': 'TIMEOUT', 'http_status': 0, 'response_hex': ''}
        if result.returncode != 0 or len(result.stdout) > 1100000:
            return {'status': 'TRANSPORT_ERROR', 'http_status': 0,
                    'response_hex': ''}
        return json_object(result.stdout)


class FixtureProvider:
    '''Protocol exercise only: this is a scripted solver, never an LLM.'''

    mode = 'SCRIPTED_FIXTURE_NOT_LLM'

    def __init__(self, route, failure=None):
        self.route = route
        self.failure = failure
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        if self.failure == 'timeout':
            return {'status': 'TIMEOUT', 'http_status': 0, 'response_hex': ''}
        context = json_object(request['messages'][-1]['content'])
        role = context['role']
        if role == 'selector':
            value = {'arm': ARMS[(context['observation']['level'] - 1) % 3]}
        elif role == 'planner':
            value = {'plan': 'Take a key, unlock the next door, move right.'}
        else:
            obs = context['observation']
            if self.failure == 'paint':
                action = 'paint'
            elif obs['position'] >= obs['level']:
                action = 'right'
            elif obs['position'] + 1 in obs['opened']:
                action = 'right'
            else:
                action = 'unlock' if obs['key'] else 'take'
            value = {'action': action}
        content = json.dumps(value)
        if self.failure == 'bad_json':
            content = 'not json'
        usage = {'prompt_tokens': 100, 'completion_tokens': 20}
        if self.failure == 'overrun':
            usage['completion_tokens'] = self.route.output_token_cap + 1
        body = {'model': self.route.expected_response_model,
                'choices': [{'message': {'content': content},
                             'finish_reason': 'stop'}], 'usage': usage}
        if self.failure == 'missing_usage':
            del body['usage']
        if self.failure == 'model_drift':
            body['model'] = 'unapproved-model'
        return {'status': 'RESPONSE', 'http_status': 200,
                'response_hex': json.dumps(body).encode().hex()}
