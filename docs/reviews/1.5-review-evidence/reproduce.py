'''Reproduce the source audit and verify the separate draft repair offline.'''

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from zipfile import ZipFile


INPUT_HASHES = {
    'AHSL-1.5.zip':
        'cd2f1ff9f5fda4ab807350ae32c068540a19ba79a09ffefb07a64fa8696d34f7',
    'AHSL-LLM-experiment-0.3.zip':
        '22483f2b36cc854df7b896df3d36329506b20407212c70f8d1a89661a455343a',
}
CORE_MANIFEST = (
    '01ada0969532bcc9db11d1f2968b2166ef76aa6866396195cccebc5398733430'
)
SEARCH_HEAD = (
    'd538c0f1973757b34fa985ea2144c0c8c165736cc98061cad086011613de7850'
)
FIXTURE_HEAD = (
    '09a25bfde19f347f2ef836fd421def3d3d69f95eb945313029b94d6f9c57d3a5'
)


def extract(archive_path, destination):
    expected = INPUT_HASHES[archive_path.name]
    actual = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError('Input archive checksum differs')
    destination.mkdir(parents=True, exist_ok=False)
    with ZipFile(archive_path) as archive:
        for info in archive.infolist():
            target = (destination / info.filename).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError('Archive path escapes destination')
            file_type = (info.external_attr >> 16) & 0o170000
            if file_type == 0o120000:
                raise ValueError('Archive contains a symbolic link')
        archive.extractall(destination)


def run(command, cwd, log):
    with log.open('w') as output:
        result = subprocess.run(
            command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT,
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError('Command failed; inspect ' + str(log))
    print('Completed:', log.name, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    bundle = Path(__file__).resolve().parent
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    logs = output / 'results'
    logs.mkdir()
    core_archive = bundle / 'inputs/AHSL-1.5.zip'
    experiment_archive = bundle / 'inputs/AHSL-LLM-experiment-0.3.zip'
    extract(core_archive, output / 'core')
    extract(experiment_archive, output / 'experiment')
    core = output / 'core/ahsl-1.5'
    experiment = output / 'experiment/ahsl-llm-experiment-0.3'

    run([sys.executable, 'verify.py', '--expected-manifest', CORE_MANIFEST],
        core, logs / 'verification.log')
    run([sys.executable, 'demo.py'], core, logs / 'demo.log')
    run([sys.executable, 'verify_mutations.py'], core,
        logs / 'mutation-checks.log')
    run([sys.executable, str(bundle / 'review_checks.py'), '--source',
         str(core), '--output', str(logs / 'recursion-checks.json')],
        bundle, logs / 'recursion-checks.log')

    with ZipFile(core_archive) as archive:
        identical = {
            name: (core / 'reports' / name).read_bytes()
            == archive.read('ahsl-1.5/reports/' + name)
            for name in ('verification.json', 'benchmark.json',
                         'replay-determinism.json', 'demo.json')
        }
    if not all(identical.values()):
        raise AssertionError('A reference report differs')

    run([sys.executable, 'verify.py'], experiment,
        logs / 'experiment-verification.log')
    run([sys.executable, 'search_experiment.py', 'replay', '--output',
         'reports/search-run', '--expected-head', SEARCH_HEAD],
        experiment, logs / 'search-replay.json')
    run([sys.executable, 'experiment.py', 'replay', '--output',
         'reports/fixture-run', '--expected-head', FIXTURE_HEAD],
        experiment, logs / 'fixture-replay.json')

    patch_binary = shutil.which('patch')
    if patch_binary is None:
        raise RuntimeError('Install the patch utility to check the draft fix')
    patched = output / 'draft_patch'
    shutil.copytree(core, patched)
    run([patch_binary, '-p1', '--batch', '--forward', '-i',
         str(bundle / 'fix-recursion.patch')], patched,
        logs / 'patch-apply.log')
    # This is a changed development tree, not an authenticated AHSL release.
    # The original manifest is intentionally never rebuilt here.
    run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
        patched, logs / 'patch-suite.log')
    suite_log = (logs / 'patch-suite.log').read_text()
    count = re.search(r'Ran (\d+) tests? in ', suite_log)
    if count is None:
        raise AssertionError('Missing test count')

    result = {
        'python': sys.version, 'core_reports_byte_identical': identical,
        'core_verification': json.loads(
            (core / 'reports/verification.json').read_text()),
        'recursion_checks': json.loads(
            (logs / 'recursion-checks.json').read_text()),
        'search_replay': json.loads((logs / 'search-replay.json').read_text()),
        'fixture_replay': json.loads(
            (logs / 'fixture-replay.json').read_text()),
        'draft_patch_tests_passed': int(count.group(1)),
        'external_llm_calls': 0,
        'scope': 'Offline reproduction and draft repair. No Ralph/gate/'
        'decomposition LLM experiment was performed.',
    }
    (logs / 'review-results.json').write_text(
        json.dumps(result, indent=2) + '\n')
    print('Complete:', logs / 'review-results.json')


if __name__ == '__main__':
    main()
