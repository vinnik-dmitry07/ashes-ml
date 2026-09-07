'''An honest zero/zero counterexample, with actual old VM executions.'''

from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys


WORKSPACE = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(WORKSPACE / 'ahsl-1.0' / 'runtime_0_6'))

evidence = importlib.import_module('evidence')
scenario = importlib.import_module('examples.scenario')
fixture, value = scenario.fixture, scenario.value
system = importlib.import_module('system')


policy, registry, parent = fixture()
parent['program']['entry'] = 'finish'
parent['program']['nodes'] = {
    'finish': {'op': 'halt', 'value': {'register': 'x'}},
}
child = deepcopy(parent)
child['program']['fuel'] += 1


def measured_output(configuration, x):
    state = system.initial(policy, registry, configuration)
    state, result, _ = system.step(state, 'agent', {
        'id': 'start', 'kind': 'start_run', 'run': 'r',
        'args': {'x': value(x)},
    })
    assert result['code'] == 'OK', result
    state, _, requests = system.step(state, 'agent', {
        'id': 'drive', 'kind': 'drive', 'run': 'r',
    })
    assert requests == []
    assert state['runs']['r']['vm']['status'] == 'halted'
    result = state['runs']['r']['vm']['result']['value']
    assert result >= x  # Actual fixed interface postcondition is satisfied.
    assert system.invariants(state)
    return result


rows = []
raw = []
# The frozen evaluation task is to return x + 1. Both programs return x.
# All sampled tasks fail, regardless of x; the paired outcomes are constant.
for x in range(128):
    p = measured_output(parent, x)
    c = measured_output(child, x)
    rows.append({'id': f'sample{x}', 'parent': p == x + 1,
                 'candidate': c == x + 1})
    raw.append({'x': x, 'target': x + 1, 'parent': p, 'candidate': c})
report = {'strata': {'composition': rows}, 'violations': 0}
evidence.validate_protocol(policy)
evidence.validate_report(report)
verdict = evidence.assess(policy, 1, 'retain', report)
assert verdict['accepted']
state = system.initial(policy, registry, parent)
protocol = [
    ('agent', {'id': 'p', 'kind': 'propose', 'proposal': 'p',
               'configuration': child}),
    ('agent', {'id': 't', 'kind': 'start_trial', 'trial': 't',
               'proposal': 'p', 'claim': 'retain'}),
    ('provider', {'id': 'a', 'kind': 'assessment', 'trial': 't', 'charge': 6,
                  'outcome': {'kind': 'report', 'report': report}}),
    ('agent', {'id': 'release', 'kind': 'publish', 'trial': 't'}),
]
codes = []
for principal, event in protocol:
    state, answer, _ = system.step(state, principal, event)
    codes.append(answer['code'])
assert codes == ['OK', 'OK', 'SETTLED', 'OK'], codes
output = {
    'profile': 'AHSL 1.0 with its embedded R06',
    'frozen_task': 'output == x + 1',
    'fixed_interface_postcondition': 'output >= x',
    'actual_vm_executions': 256,
    'parent_successes': sum(row['parent'] for row in rows),
    'candidate_successes': sum(row['candidate'] for row in rows),
    'cases': len(rows), 'interface_violations': 0,
    'honest_report': report, 'actual_outputs': raw,
    'verdict': verdict, 'protocol_codes': codes,
    'generation_after_publish': state['generation'],
    'scope': ('Controlled fixed task, not a stochastic benchmark or a claim '
              'of violating the R06 relative-retention specification.'),
}
print(json.dumps(output, indent=2))
