'''Check source pins and exercise the extension without a model API.'''

import json
from pathlib import Path
import sys
import unittest

from llmbench.experiment import check_sources


if __name__ == '__main__':
    identifier = check_sources()
    root = Path(__file__).resolve().parent
    suite = unittest.defaultTestLoader.discover(str(root / 'tests'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    check_sources()
    print(json.dumps({'source_manifest': identifier,
                      'tests_run': result.testsRun,
                      'success': result.wasSuccessful(),
                      'live_llm_evaluation': 'NOT_RUN'}))
    sys.exit(0 if result.wasSuccessful() else 1)
