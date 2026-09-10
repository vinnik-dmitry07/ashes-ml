'''Explicitly freeze reviewed source; verification never refreshes this pin.'''

from ahsl.codec import canonical
from llmbench.experiment import ROOT, source_manifest


if __name__ == '__main__':
    path = ROOT / 'source-manifest.json'
    path.write_bytes(canonical(source_manifest()) + b'\n')
    print('Source manifest written. Preserve its digest outside this package.')
