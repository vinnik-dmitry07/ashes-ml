'''Recheck the historical attestation defect and current external anchoring.'''

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


WORKSPACE = Path(sys.argv[1]).resolve()
EXPECTED = '22d69a3e5bb34944ff2168577bd74405346cd8fb2825169b8b9c43a810d11430'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(root, *arguments):
    result = subprocess.run(
        [sys.executable, 'verify.py', *arguments], cwd=root,
        capture_output=True, text=True, timeout=50,
    )
    return {'exit': result.returncode, 'stdout': result.stdout,
            'stderr': result.stderr}


def rehash_old(root):
    path = root / 'manifest.lock.json'
    lock = json.loads(path.read_text())
    lock['sha256'] = {name: sha(root / name) for name in lock['sha256']}
    path.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + '\n')


def inspect_old(root):
    path = root / 'manifest.lock.json'
    lock = json.loads(path.read_text())
    return all(sha(root / name) == expected
               for name, expected in lock['sha256'].items())


with tempfile.TemporaryDirectory() as temporary:
    temporary = Path(temporary)
    old = temporary / 'old'
    new = temporary / 'new'
    for source, target in ((WORKSPACE / 'ahsl-1.0', old),
                           (WORKSPACE / 'ahsl-1.3', new)):
        shutil.copytree(source, target,
                        ignore=shutil.ignore_patterns('__pycache__'))
    report = {'old_locks_initially_valid': [
        inspect_old(old), inspect_old(old / 'runtime_0_6'),
        inspect_old(old / 'runtime_0_6' / 'kernel'),
    ]}
    assert all(report['old_locks_initially_valid'])
    evidence = old / 'runtime_0_6' / 'evidence.py'
    source = evidence.read_text()
    target = "core.require(0 < spec['n'] <= 512)"
    assert source.count(target) == 1
    evidence.write_text(source.replace(target, target.replace('512', '4096')))
    rehash_old(old / 'runtime_0_6')
    rehash_old(old)
    old_result = execute(old)
    report['old_execution'] = old_result
    assert old_result['exit'] == 0, old_result
    old_report = json.loads((old / 'verification.json').read_text())
    report['old_mutation'] = {
        'change': 'sample bound 512 -> 4096; both local locks rebuilt',
        'total_unit_tests': old_report['total_unit_tests'],
        'runtime_profile_unchanged': old_report['runtime_profile_unchanged'],
        'failures': old_report['failures'], 'errors': old_report['errors'],
    }
    assert old_report['runtime_profile_unchanged'] is True
    assert sha(new / 'manifest.json') == EXPECTED
    clean = execute(new, '--quick', '--expected-manifest', EXPECTED)
    assert clean['exit'] == 0, clean
    report['current_clean'] = json.loads(clean['stdout'])
    obligations = new / 'ahsl' / 'obligations.py'
    original = obligations.read_text()
    target = "'max_actions': 64,"
    assert original.count(target) == 1
    obligations.write_text(original.replace(target, "'max_actions': 63,"))
    report['current_changed_source'] = execute(
        new, '--quick', '--expected-manifest', EXPECTED)
    assert report['current_changed_source']['exit'] != 0
    manifest = new / 'manifest.json'
    data = json.loads(manifest.read_text())
    data = {name: sha(new / name) for name in data}
    manifest.write_text(json.dumps(data, sort_keys=True, indent=2) + '\n')
    report['current_changed_source_and_lock'] = execute(
        new, '--quick', '--expected-manifest', EXPECTED)
    assert report['current_changed_source_and_lock']['exit'] != 0
    assert 'External manifest anchor mismatch' in (
        report['current_changed_source_and_lock']['stderr'])
    print(json.dumps(report, indent=2))
