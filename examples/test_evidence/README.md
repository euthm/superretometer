# Portable evidence: public reference workflow

Install `pip install -e '.[dev,evidence]'`. Run from a checkout:

```bash
python examples/test_evidence/run.py --output /tmp/ch-evidence-example-001
```

The destination must not exist. The example creates a clean synthetic Git fixture,
executes eight assertions, then uses **separate CLI processes** to record, import,
reimport, evaluate, run two negative controls and export/verify an offline bundle.
It writes `example-results.json`, explicit `profile.json`/`target.json`, a retained
archive and `bundle/`. It needs Python and Git; no live Memory, Rust, PostgreSQL,
tokens or private project IDs. These are workflow fixtures, not HRRM test results.
The positive has seven gate statuses PASS and conditional warrant; commit mismatch
blocks only test; absent validator makes test UNKNOWN. A bare InMemory instance
still has no persisted data. Restart recovery is explicit snapshot restoration.

For your project, copy the generated profile/target and edit the **declarations**
(source files, lockfiles, bounded claim, remote, falsifier, relevant tool/service
versions, exclusions and acceptance). Let capture fill observed facts. Paths in
configuration are relative to that config file, not imported receipt paths. Set
an archive path outside the tested worktree, locator and real retention/backup
policy. The filesystem target is a reference archive; it does not write to your
production Memory project. Unsupported target kinds fail explicitly.

```bash
superretometer evidence record --config profile.json -- python runner.py '{output}'
superretometer evidence verify /archive/runs/<run-id>
superretometer evidence import /archive/runs/<run-id> --target target.json
superretometer evidence evaluate <run-id> --target target.json
superretometer evidence evaluate <run-id> --target target.json --control commit_mismatch
superretometer evidence evaluate <run-id> --target target.json --control missing_validator
superretometer evidence export <evaluation-id> --target target.json --output /new/bundle
superretometer evidence verify /new/bundle
```

`record` is the only command that executes a child; it does not add a shell.
The runner writes its result file under the substituted `{output}` directory.
Use `counts-json/v1` (`fixture_runner.py` shows the complete language-neutral
protocol), `junit/v1`, or explicitly `unknown/v1`. Unknown counts never become
8/8 merely because a process exits zero. Relevant service versions in the profile
are operator-declared; list unobserved dependencies/exclusions explicitly.

Each command prints JSON. Exit 0 from verify/import is an operation result, not a
claim of passing tests. Record returns 3 for unknown acceptance and 4 for failure;
evaluate returns 4 unless the baseline is approved. Negative controls intentionally
return 4 and preserve their full reports. All retries/evaluations have new IDs.

Third parties need only the bundle directory and evidence extra to check included
bytes, source/command/test observations, graph inputs and historical gate/warrant
responses. Offline verification makes current freshness **unavailable** unless
`--repo /your/explicit/matching/checkout` is given. The archive locator is metadata;
no implicit network fetch or remote command execution occurs. Checksums do not
authenticate the producer or make runner-reported evidence independent.

Read `spec/TEST_EVIDENCE.md` for exact encoding, manifests, redaction, storage and
pre/post-observation limitations. Keep test code and small expected fixtures in
Git; archive actual bulk outputs separately. Native Memory/CI/remote archive
adapters and automatic project setup are deliberately optional future work.
