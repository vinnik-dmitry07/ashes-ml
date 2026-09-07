'''
Release-time generation; verification reads frozen fixtures without
rewriting.
'''

import json
from pathlib import Path

from ahsl.codec import canonical, cid
from ahsl.examples import (
    corridor_agent, council, group_relative_controller, islands,
    recursive_context,
)
from ahsl.schema import SCHEMAS


def main():
    root = Path(__file__).resolve().parent
    examples = {'react': corridor_agent(), 'council': council(),
                'islands': islands(), 'recursive_context': recursive_context(),
                'group_relative_controller': group_relative_controller()}
    for key, value in examples.items():
        (root / 'examples' / (key + '.json')).write_bytes(canonical(value))
    (root / 'protocol-schemas.json').write_text(
        json.dumps(SCHEMAS, sort_keys=True, indent=2) + '\n')
    cases = []
    for value in (None, True, -9223372036854775807, 'quote"\\',
                  {'b': [1, 2], 'a': {'num': -2, 'den': 3}}):
        cases.append({'value': value, 'bytes_hex': canonical(value).hex(),
                      'id': cid('EncodingFixture', value)})
    (root / 'encoding-vectors.json').write_text(
        json.dumps(cases, sort_keys=True, indent=2) + '\n')


if __name__ == '__main__':
    main()
