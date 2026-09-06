'''Interpret a manifest and a finite ordered event trace using AHSL-Core.'''

import argparse
import json
from pathlib import Path

from core import fields, initial, invariants, load_json, require, step


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('manifest', type=Path)
    parser.add_argument('trace', type=Path)
    args = parser.parse_args()
    state = initial(load_json(args.manifest.read_text(encoding='utf-8')))
    records = load_json(args.trace.read_text(encoding='utf-8'))
    require(type(records) is list)
    responses = []
    for record in records:
        fields(record, ('principal', 'event'))
        state, result, requests = step(
            state, record['principal'], record['event']
        )
        assert invariants(state)
        responses.append({'result': result, 'requests': requests})
    print(json.dumps(
        {'responses': responses, 'state': state},
        ensure_ascii=False, indent=2, sort_keys=True,
    ))


if __name__ == '__main__':
    main()
