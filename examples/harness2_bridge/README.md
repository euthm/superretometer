# Optional offline Harness2 receipt bridge

This non-normative example imports a **saved external test receipt** through
ConsumerAPI proposals and evaluates the existing ImplementationGatePolicy.
It does not run Harness2, optimize a harness, or call a model. It requires only
Python and the existing cognitive_harness package; no additional dependency is
added. Harness2 remains a separate optional external producer.

## Try the synthetic example

From the repository root, with an output directory that does not already exist:

```sh
PYTHONPATH=. python3 examples/harness2_bridge/demo.py --output /tmp/h2-receipt-demo
python3 -m pytest tests/ -v
```

The demo executes two small Python candidates on three synthetic ledger cases
and records actual outputs. A hardcoded answer passes only the original case
(1/3, test BLOCK); the signed-sum program passes all three (3/3, test PASS).
These predetermined programs demonstrate the receipt boundary, not model
improvement or benchmark performance. The example repository and all-`a` commit
are **synthetic metadata**, not an observed Git checkout or trusted provenance.
Neither candidate is adopted or design-bearing.

## Import a receipt

```sh
PYTHONPATH=. python3 examples/harness2_bridge/bridge.py <receipt.json> \
  --receipt-sha256 <caller-pinned-sha256> \
  --repo <expected-workflow-repository> --commit <full-workflow-sha>
```

The format `h2-ch-offline-v1` is **this example's exchange contract**, not a
claim that upstream Harness2 emits it. A trusted external runner must export
the receipt. In a future integration that runner may wrap Harness2. The demo
shows the receipt/result fields and persists caller inputs separately.

The receipt contains `run_id`, workflow repository/commit, and relative
`candidate`, `oracle` and `result` paths with SHA-256 values. The result binds
the same run ID and candidate/oracle digests and records `tested_commit`,
`exit_code`, `command` and UTC `timestamp`. Missing exit code remains UNKNOWN;
nonzero exit and tested revision mismatch produce a test BLOCK. Modified or
missing bytes, scope mismatch, path traversal and symlinks are rejected before
the proposals are submitted.

Candidate bytes are identified independently of the workflow commit. The
importer does **not** assert that the generated candidate was committed at that
SHA. It never executes a recorded command or imports candidate code. Do not use
this example as a filesystem sandbox against concurrently hostile processes.

## What the result means

- CLI exit 0 means **import completed**, including a reported failing test. It
  is not ALLOW, an adoption decision, or a guarantee of correctness. Rejected
  input exits 2. Inspect `gates.test` and the entire gate report separately.
- Warrant is computed by the existing CH engine and is not overwritten from
  the test outcome. A warrant label does not supersede a failing test gate.
- Git worktree and source freshness are unobserved here and remain UNKNOWN.
  `adoption_allowed` is always false. No CH core, gate, spec, canonical state,
  MCP behavior or execution authority is changed.
- Hashes establish byte integrity against **caller-provided trust inputs**.
  They do not authenticate the runner, establish independent evidence roots or
  prove the truth of a consistently forged and repinned report. Secure runner
  identity and complete runtime verification remain external responsibilities.
- The public ConsumerAPI/proposal pipeline creates evidence and claim KOs,
  attaches a falsifiable validator and reads them back. The output includes
  graph and proposal records. Every import creates a fresh in-memory graph;
  fresh-process replay reconstructs gate statuses with new IDs. This is not
  exactly-once processing, persistent storage or a live MCP installation.

All committed fixtures are synthetic. The example has no private project,
Memory, StrategyServer, Julia or model-provider requirement. A live Harness2
execution, its version constraints, network isolation, budgets and independent
acceptance remain outside this import-only example.
