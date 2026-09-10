'''Run the local trust, fault, budget, and uncertainty experiments.'''

import argparse
import json

from llmbench.offline import run_offline


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    arguments = parser.parse_args()
    print(json.dumps(run_offline(arguments.output), indent=2))
