'''Verify this release without changing the lock or running live providers.'''

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

from examples.scenario import demonstration


ROOT = Path(__file__).resolve().parent


def main():
    lock = json.loads((ROOT / 'manifest.lock.json').read_text())
    for name, expected in lock['sha256'].items():
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit('Hash mismatch: ' + name)
    subprocess.run([sys.executable, 'verify.py'], cwd=ROOT / 'kernel', check=True)
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    demo = demonstration()
    assert demo['generation'] == 1 and demo['spent'] == 6
    assert demo['available'] == 94
    (ROOT / 'examples' / 'release.json').write_text(
        json.dumps(demo, indent=2, ensure_ascii=False) + '\n', encoding='utf-8',
    )
    report = {
        'version': '0.6', 'kernel_tests': 27, 'profile_tests': result.testsRun,
        'failures': len(result.failures), 'errors': len(result.errors),
        'hashed_files': len(lock['sha256']), 'synthetic_release_example': 'pass',
        'statistical_boundary_checks': 'exact enumeration for n = 1..14',
        'tlc_rerun': False, 'mechanized_general_proof': False,
        'production_adapter_tested': False, 'live_learning_benchmark_run': False,
    }
    (ROOT / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
