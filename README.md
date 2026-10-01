# AHSL 1.5

An executable reference for a harness language: Mission, parent guarantees, a separate evaluator, and checks on execution and admission. This version addresses the 1.4 audit findings: search controls, rename cost, resume from a stale snapshot, fuzzer reporting, and service-registry checks.

Python 3.11+, standard library. The durable owner profile D12 uses SQLite and POSIX fsync. Release checks were run on the Python version in §20 of `SPEC.md`. A 1.4 reproduction on Python 3.11.15 was reported by a user; it is not an extra 1.5 run on 3.11.

```bash
python3 verify.py
python3 demo.py
python3 verify_mutations.py
```

`verify.py` does not update the manifest. To check against an external anchor:

```bash
python3 verify.py --expected-manifest 029222c84efdcb9a70d9a2c21be3745ba0a19c2bf13f27d6162e9fc9409d16e5
```

`--write-manifest` and `build_fixtures.py` are for assembling a new release. They are not a provenance check. The manifest covers Python and JSON at the repository root and in `src/`, `tests/`, and `examples/`. `docs/`, `experiments/`, `history/`, and `reports/` are outside it; documents are protected by the archive hash.

For a durable agent entry point, use `DurableSession`:

```python
from src.codec import canonical, cid
from src.durable import DurableSession
from src.examples import corridor_agent

# Public demo key; the owner sets the working key.
key = b'example-key-not-a-production-secret'
owner = DurableSession.create(
    'new-session.sqlite', corridor_agent('paint'), 24, key,
    cid('Manifest', 'replace-with-the-pinned-source-manifest'), [1],
)
reply = owner.handle(canonical({
    'op': 'propose', 'program': corridor_agent(),
}))
snapshot, anchor = owner.checkpoint()
owner.close()

# Loads the current state of the trusted DB; the previous owner is revoked.
resumed = DurableSession.open('new-session.sqlite', key)
resumed.close()
```

`DurableSession.restore(path, snapshot, key, anchor)` checks the presented pair against the current DB. Old revision/digest values return STALE. Use `open` when the client lost the reply after a saved result. A rejection at the outer wire boundary does not advance the checkpoint. A pending operation blocks automatic retry with PHASE. Failure of the DB itself, an administrator rollback, or general recovery of pending work is out of scope. The full contract is §9.1.

`Session.restore` has been removed. `Session.restore_integrity` remains for offline checks of historical snapshots and does not guarantee freshness. Direct access to Python objects belongs to the trusted owner; this is not an agent sandbox.

The three improve axes are actions, VM fuel, and size after bound-name normalization. A pure rename is no longer an improvement. `max_program_bytes` still limits the actual bytes of the source program. The cost-profile version is `SUCCESS_THEN_PARETO_COST_2`.

Both search modes use the same subgoal index and one budget unit. A flat goal needs one construction; a nested goal needs three. The earlier claim that planning was cheaper is withdrawn.

**Four plans are a lifetime bound of one bootstrap.** Completing or abandoning a slot does not free it. The reference does not promise unbounded self-evolution. This limit is kept and checked separately.

Files:

- `SPEC.md` — normative rules and actual release numbers.
- `AUDIT-CLOSURE.md` — replies to the six findings and a note on services.
- `CHANGELOG.md` — compatibility and 1.5 changes.
- `src/` — execution, admission, trust, and the D12 owner.
- `protocol-schemas.json`, `encoding-vectors.json` — frozen forms and vectors.
- `reports/` — full run, demo, fuzzers, K12 walk, and targeted mutation checks.
- `history/` — non-normative documents from earlier versions.

Content IDs, snapshots, and keys belong to version 1.5. There is no automatic migration of 1.4 authorities or evidence. No LLM API, weight training, or external services were run here. Experiment package 0.3 remains a separate reproducible snapshot on its pinned 1.4 core; its earlier measurements are not rewritten as 1.5 results.
