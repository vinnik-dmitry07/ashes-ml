'''Run or replay the experiment; live mode requires a pinned route.'''

import argparse
import json
from pathlib import Path

from llmbench.experiment import replay_campaign, run_campaign


def main():
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest='command', required=True)
    run = subcommands.add_parser('run')
    run.add_argument('--config', type=Path, required=True)
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--live', action='store_true')
    replay = subcommands.add_parser('replay')
    replay.add_argument('--output', type=Path, required=True)
    replay.add_argument('--expected-head', required=True)
    args = parser.parse_args()
    if args.command == 'run':
        config = json.loads(args.config.read_text())
        result = run_campaign(config, args.output, args.live)
    else:
        result = replay_campaign(args.output, args.expected_head)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
