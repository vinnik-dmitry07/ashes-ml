'''Remove protections in isolated copies; require behavioral test failure.'''

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
MUTATIONS = (
    ('equal_principals', 'src/obligations.py',
     '    need(observer != evaluator, \'AUTHORITY\')\n', '',
     'test_equal_principals_are_rejected_by_low_level_mission'),
    ('raw_name_bytes', 'src/witness.py',
     '\'program_bytes\': program_cost_bytes(program)',
     '\'program_bytes\': len(canonical(program))',
     'test_alpha_rename_cannot_be_a_cost_improvement'),
    ('unfenced_owner', 'src/durable.py',
     '        need(row[:2] == (self._revision, self._digest), '
     '\'STALE\')\n', '',
     'test_restore_claim_is_single_use_even_when_blob_has_not_changed'),
)


def run():
    rows = []
    with tempfile.TemporaryDirectory(prefix='ahsl15-mutants-') as directory:
        for label, file, old, new, test in MUTATIONS:
            target = Path(directory) / label
            shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns(
                '__pycache__', 'reports', 'history'))
            path = target / file
            original = path.read_text()
            assert original.count(old) == 1
            path.write_text(original.replace(old, new, 1))
            result = subprocess.run([
                sys.executable, '-m', 'unittest', 'discover', '-s', 'tests',
                '-p', 'test_release_15.py', '-k', test, '-v',
            ], cwd=target, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=30, text=True)
            single_test = re.search(r'Ran 1 test in ', result.stdout)
            caught = (result.returncode == 1 and single_test is not None
                      and 'FAILED (failures=1)' in result.stdout)
            rows.append({'mutation': label, 'test': test, 'caught': caught,
                         'returncode': result.returncode,
                         'output': result.stdout})
            assert caught, result.stdout
    return {'mutations': rows, 'caught': sum(row['caught'] for row in rows),
            'attempted': len(rows),
            'mechanism': 'Targeted behavioral test failures; manifest '
            'verification was not invoked in the mutated copies.'}


if __name__ == '__main__':
    result = run()
    (ROOT / 'reports').mkdir(exist_ok=True)
    (ROOT / 'reports/mutation-checks.json').write_text(
        json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items()
                      if key != 'mutations'}, indent=2))
