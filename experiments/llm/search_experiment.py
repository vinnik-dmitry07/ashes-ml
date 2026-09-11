'''Run or replay the complete offline search evaluation protocol.'''

import argparse
import json
from pathlib import Path

from llmbench.search_study import replay_search_study, run_search_study


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('run')
    run.add_argument('--config', type=Path, required=True)
    run.add_argument('--output', type=Path, required=True)
    replay = commands.add_parser('replay')
    replay.add_argument('--output', type=Path, required=True)
    replay.add_argument('--expected-head', required=True)
    args = parser.parse_args()
    if args.command == 'run':
        config = json.loads(args.config.read_text())
        result = run_search_study(config, args.output)
    else:
        result = replay_search_study(args.output, args.expected_head)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
