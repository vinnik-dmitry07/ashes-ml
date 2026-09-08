# AHSL 1.3 independent audit reproduction

Python 3.11 or newer. Standard library only. Tested with Python 3.12.14.

The `ahsl-1.3/` directory contains the unchanged files from the supplied
AHSL 1.3 archive. The `evidence/` directory contains independently obtained
reports. `AUDIT.md` explains the findings in Russian.

From this directory, run:

```bash
python3 ahsl-1.3/verify.py --expected-manifest 22d69a3e5bb34944ff2168577bd74405346cd8fb2825169b8b9c43a810d11430
python3 ahsl-1.3/demo.py
python3 reproduce.py --package ahsl-1.3 --output reproduced-results.json
```

The first two commands write generated reports beneath `ahsl-1.3/reports/`.
They do not rewrite the manifest. Do not use `--write-manifest` to verify
the supplied release.

The independent script checks ten named scenarios. Its successful exit means
that the observations match the audit, including reproduction of two defects:

- `D1_trim_alias_changes_literal`: a literal value changes after trimming.
- `D2_valid_proposal_breaks_snapshot_encoding`: a valid proposal makes the
  session snapshot exceed the canonical encoding depth limit.

This is not a test suite whose successful exit means that AHSL is defect-free.
The source-tampering checks run in temporary copies that are removed afterward.
No external model, network call or nonstandard package is needed.

Original uploaded archive SHA-256:

```text
85928587c9c333472c9d9fa2749cdc1c55c0b874f4be7b0d0e89c3cd39c70178
```

The expected manifest hash comes from the supplied package and was not
independently authenticated against a publisher. It demonstrates detection of
changes relative to that pinned value, not authentication of its own origin.
