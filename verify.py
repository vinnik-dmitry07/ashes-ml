'''Run the pinned runtime and new finite reference-profile checks.'''

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

from examples.conditional_plan import demonstration
from exhaustive import check_boolean_formulas, check_graphs


ROOT = Path(__file__).resolve().parent


def main():
    lock = json.loads((ROOT / 'manifest.lock.json').read_text())
    for name, expected in lock['sha256'].items():
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit('Hash mismatch: ' + name)
    subprocess.run(
        [sys.executable, 'verify.py'], cwd=ROOT / 'runtime_0_6', check=True,
    )
    old = json.loads((ROOT / 'runtime_0_6' / 'verification.json').read_text())
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    graph_cases = check_graphs()
    formula_cases = check_boolean_formulas()
    demo = demonstration()
    assert demo['goal_status'] == ['CONDITIONAL', 'CONDITIONAL', 'VERIFIED']
    assert demo['spent'] + demo['available'] == 100
    (ROOT / 'examples' / 'conditional-plan.json').write_text(
        json.dumps(demo, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    report = {
        'version': '1.0',
        'runtime_kernel_tests': old['kernel_tests'],
        'runtime_profile_tests': old['profile_tests'],
        'prospection_tests': result.testsRun,
        'total_unit_tests': (
            old['kernel_tests'] + old['profile_tests'] + result.testsRun
        ),
        'failures': len(result.failures), 'errors': len(result.errors),
        'graph_cases': graph_cases, 'boolean_formula_cases': formula_cases,
        'conditional_plan_example': 'pass',
        'runtime_profile_unchanged': True,
        'full_x1_adapter_implemented': False,
        'mechanized_general_proof': False,
        'production_adapter_tested': False,
        'live_learning_benchmark_run': False,
        'real_world_improvement_measured': False,
    }
    (ROOT / 'verification.json').write_text(
        json.dumps(report, indent=2) + '\n', encoding='utf-8',
    )
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
