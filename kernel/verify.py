'''Verify distribution hashes, golden behavior, replay and unit cases.'''

import hashlib
import json
from pathlib import Path
import unittest

from core import initial, invariants, load_json, replay, step


ROOT = Path(__file__).resolve().parent


def golden_example():
    folder = ROOT / 'examples'
    manifest = load_json((folder / 'manifest.json').read_text())
    trace = load_json((folder / 'conflict.json').read_text())
    state = initial(manifest)
    dispatched = 0
    for record in trace:
        state, _, requests = step(state, record['principal'], record['event'])
        dispatched += len(requests)
        assert invariants(state)
    actual = {
        'spent': state['spent'], 'available': state['available'],
        'version': state['cells']['x']['version'],
        'j1': state['jobs']['j1']['result']['code'],
        'j2': state['jobs']['j2']['result']['code'],
        'dispatches': dispatched,
    }
    assert actual == load_json((folder / 'expected.json').read_text())
    assert replay(manifest, state['log']) == state
    return actual


def verify_hashes():
    lock = json.loads((ROOT / 'manifest.lock.json').read_text())
    for name, expected in lock['sha256'].items():
        path = ROOT / name
        assert path.is_file(), name
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == expected, name
    return len(lock['sha256'])


def verify_embedded_source():
    document = (ROOT / 'SPEC.md').read_text(encoding='utf-8')
    appendix = document.split('## Приложение A.', maxsplit=1)[1]
    embedded = appendix.split('```python\n', maxsplit=1)[1]
    embedded = embedded.rsplit('\n```', maxsplit=1)[0]
    assert embedded == (ROOT / 'core.py').read_text().rstrip()


def main():
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    verify_embedded_source()
    summary = {
        'unit_tests': result.testsRun,
        'golden_example': golden_example(),
        'hashed_files': verify_hashes(),
        'tlc_rerun': False,
        'scope': 'No production adapter or implementation proof checked.',
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
