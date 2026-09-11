'''Owner-pinned routing, exact monetary accounting, and durable event logs.'''

from copy import deepcopy
from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
from urllib.parse import urlsplit

from ahsl.codec import canonical, fields, integer, need


PROFILE = 'AHSL_LLM_EXPERIMENT_0_3'
CONDITIONS = ('fresh', 'history', 'plan', 'selector')
ARMS = CONDITIONS[:3]


def digest(kind, value):
    prefix = (PROFILE + '/' + kind + '\0').encode('ascii')
    return hashlib.sha256(prefix + canonical(value)).hexdigest()


def dollars(value):
    need(type(value) is str, 'SCHEMA')
    result = Fraction(value) * 1000000
    need(result.denominator == 1 and result >= 0, 'SCHEMA')
    return int(result)


def json_object(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'SCHEMA')
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique)
    need(type(value) is dict, 'SCHEMA')
    return value


@dataclass(frozen=True)
class Route:
    endpoint: str
    model: str
    expected_response_model: str
    key_env: str
    input_usd_per_million: str
    output_usd_per_million: str
    input_token_bound: int
    output_token_cap: int
    timeout_seconds: int
    temperature: object = None
    reasoning_effort: object = None
    use_seed: bool = False

    def __post_init__(self):
        address = urlsplit(self.endpoint)
        need(address.scheme == 'https' and address.hostname
             and not address.username and not address.password
             and not address.query and not address.fragment, 'AUTHORITY')
        for text in (self.model, self.expected_response_model, self.key_env):
            need(type(text) is str and text and len(text) <= 200)
        need(self.key_env.replace('_', '').isalnum(), 'SCHEMA')
        dollars(self.input_usd_per_million)
        dollars(self.output_usd_per_million)
        integer(self.input_token_bound, 1, 1000000)
        integer(self.output_token_cap, 1, 32768)
        integer(self.timeout_seconds, 1, 600)
        need(self.temperature is None or type(self.temperature) is int
             and 0 <= self.temperature <= 2)
        need(self.reasoning_effort in (None, 'low', 'medium', 'high'))
        need(type(self.use_seed) is bool)
        canonical(asdict(self))

    @property
    def identifier(self):
        return digest('Route', asdict(self))

    def charge(self, prompt, completion):
        integer(prompt, 0)
        integer(completion, 0)
        amount = (prompt * dollars(self.input_usd_per_million)
                  + completion * dollars(self.output_usd_per_million))
        return math.ceil(Fraction(amount, 1000000))

    @property
    def reservation(self):
        return self.charge(self.input_token_bound, self.output_token_cap)

    def request(self, messages, seed):
        result = {'model': self.model, 'messages': deepcopy(messages),
                  'max_completion_tokens': self.output_token_cap,
                  'response_format': {'type': 'json_object'},
                  'stream': False, 'n': 1}
        if self.temperature is not None:
            result['temperature'] = self.temperature
        if self.reasoning_effort is not None:
            result['reasoning_effort'] = self.reasoning_effort
        if self.use_seed:
            result['seed'] = seed
        return result


class Budget:
    def __init__(self, total, max_calls):
        integer(total, 1)
        integer(max_calls, 1, 1000)
        self.total = total
        self.max_calls = max_calls
        self.charged = 0
        self.calls = 0
        self.overrun = False

    def reserve(self, route):
        need(not self.overrun, 'BUDGET')
        need(self.calls < self.max_calls, 'BUDGET')
        need(self.charged + route.reservation <= self.total, 'BUDGET')
        self.calls += 1
        self.charged += route.reservation
        return route.reservation

    def settle(self, reserved, actual=None):
        if actual is not None:
            integer(actual, 0)
            if actual > reserved:
                self.overrun = True
            self.charged += actual - reserved
        # Missing usage burns the reservation: it is never a free retry.
        return reserved if actual is None else actual


class Journal:
    def __init__(self, path, identity):
        self.path = Path(path)
        self.head = digest('JournalStart', identity)
        self.index = 0
        self.stream = self.path.open('xb')
        self.accounted_cost = 0
        self.calls = 0
        self.pending = {}

    def append(self, kind, value):
        record = {'index': self.index, 'kind': kind, 'value': deepcopy(value),
                  'previous': self.head}
        new_head = digest('Event', record)
        self.stream.write(canonical(record) + b'\n')
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.head = new_head
        self.index += 1
        if kind == 'call_start':
            self.calls += 1
            self.pending[value['call']] = value['reserved_microusd']
            self.accounted_cost += value['reserved_microusd']
        elif kind == 'call_end':
            self.accounted_cost += (value['charge_microusd']
                                    - self.pending.pop(value['call']))
        return new_head

    def close(self):
        self.stream.close()


def read_journal(path, identity, expected_head):
    head = digest('JournalStart', identity)
    records = []
    with Path(path).open('rb') as stream:
        for index, line in enumerate(stream):
            need(line.endswith(b'\n'), 'INTEGRITY')
            raw = line[:-1]
            record = json_object(raw)
            need(canonical(record) == raw, 'INTEGRITY')
            fields(record, ('index', 'kind', 'value', 'previous'))
            need(record['index'] == index and record['previous'] == head,
                 'INTEGRITY')
            head = digest('Event', record)
            records.append(record)
    need(head == expected_head, 'INTEGRITY')
    return records
