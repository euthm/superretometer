# Required CH evidence before merge

This is a CI adapter around #18, not a new warrant algorithm or an automatic H2
adoption loop. H2 may propose a candidate on a branch; a human reviews the PR.
`CH evidence` accepts only the bounded regression claim recorded in its bundle.
It does not certify that software is bug-free or authorize a deployment.

## What runs

1. Ordinary `CI` runs on the PR. A failed CI cannot lead to a successful guard.
2. `CH merge guard` starts from the **default-branch workflow**, after CI completes.
   Its evaluator, pinned control requirements and policy come from the same
   reviewed control commit (`github.sha`), not from the candidate PR.
3. A separate ephemeral capture job checks out the exact candidate head SHA,
   without persisted Git credentials, secrets, shared caches or write permission.
   It runs the reviewed argv and uses #18 to retain stdout, stderr, structured
   results and pre/post code observations. All tracked regular files are covered,
   by default, including tests, runner, policy and configuration. An explicitly
   reviewed bounded policy can select a smaller acceptance scope. Submodules use #18 pins;
   symlink sources are explicitly unsupported.
4. A fresh verifier job installs only the reviewed evaluator. Candidate code and
   downloaded receipts are **data**, never installed or executed in that job.
   Verification binds the expected repository and full commit, clean pre/post
   state, complete source coverage, reviewed command and acceptance requirements.
5. The policy requires a positive execution floor, named existing regression
   tests, zero failures and only explicitly named optional skips. A required
   regression can never be waived using the optional-skip list. New tests may be
   added without changing the policy; removing/renaming a protected baseline test
   needs an explicit reviewed policy update on main.
6. The verifier imports the receipt, evaluates all seven existing implementation
   gates, and runs isolated `commit_mismatch` and `missing_validator` controls.
   It exports and verifies a bundle with the unmodified raw warrant. Missing or
   unknown results reject the merge claim. Expected negative controls are not
   described as successful application tests.
7. Only the verifier job has `checks: write`. It publishes `CH evidence` on the
   **candidate head SHA**, not the default-branch workflow SHA. A newer PR commit
   needs a new result. Skipped capture, failed CI, absent artifacts or unsupported
   fork PRs cannot publish a successful guard. Failure before publication leaves
   a missing check, which must also block merge under the required-check rule.

The initial profile covers the public offline suite, not a live Memory/Strategy
session or full live H2 integration. The seven known optional integration skips
are named in `.github/ch-merge-policy.json`. CI artifacts retain the receipt and
export for 30 days. Copy required audit evidence to durable storage before expiry;
the workflow does not promise permanent retention.

## Activate enforcement (repository administrator)

Adding a workflow alone does **not** make its result mandatory. This setup is
not enforced until the repository settings have been applied and verified.

1. Review and merge the bootstrap PR. Default-branch `workflow_run` code cannot
   establish its own trusted status before that initial merge. Do not waive an
   already-enabled guard for later candidate changes.
2. Open a small follow-up PR, let CI and `CH merge guard` run, and inspect its
   `CH evidence` check, receipt, positive gates and both negative controls.
3. In Settings → Rules / Branches, protect `main`: require PRs, review by code
   owners, dismissal of stale approvals / approval of the latest change, and
   required status checks. Require `CH evidence` (GitHub Actions as expected app)
   plus all existing CI matrix jobs. Require branches up to date and prevent
   direct/force pushes, deletion and bypass, including H2's bot and administrators.
   A merge queue needs additional `merge_group` integration; this workflow does
   not claim to support one.
4. `.github/CODEOWNERS` names the actual current maintainer rather than the old
   `@maintainers` placeholder. A PR authored by that same user cannot receive
   their own approval. Add a real second eligible maintainer, or have H2 propose
   through a distinct bot identity and let the human owner review. Do not invent
   reviewer accounts or grant the bot administrative access.
5. Exercise the boundary with disposable PRs: a failed test, omitted required
   test, unexpected skip and new commit after a previous success must each be
   nonmergeable. Keep their check URLs as activation evidence. GitHub settings,
   reviewer independence and these live negative controls remain administrator
   verification steps; a local test run cannot prove them.

The connected GitHub integration returned 403 for branch-protection inspection
during preparation. No branch rules were silently changed, and this document is
not evidence that enforcement has been enabled.

## Local use and another project

The language-independent adapter is `scripts/ch_merge_guard.py`. Install the
reviewed Superretometer checkout with the `evidence` extra. Keep its code/policy
separate from the tested repository and use an explicit full expected commit.

```sh
python /reviewed/ch/scripts/ch_merge_guard.py capture \
  --policy /reviewed/policy.json --repo /candidate \
  --expected-commit "$TEST_SHA" --expected-remote "$REPOSITORY_URL" \
  --output /new/capture

# Run in a fresh process/job, using reviewed control code and policy:
python /reviewed/ch/scripts/ch_merge_guard.py check \
  --policy /reviewed/policy.json --repo /candidate \
  --expected-commit "$TEST_SHA" --expected-remote "$REPOSITORY_URL" \
  --receipt /new/capture/receipt --output /new/verification
```

Policy v1 declares an exact argv, JUnit or `counts-json/v1` result path, required
test IDs, minimum executed count, allowed optional JUnit skips, tracked lockfiles,
timeout and bounded scope. No shell is introduced. `{repo}` and `{output}` use
the existing recorder substitutions. Rust/Go runners can emit the same structured
protocol; this PR does not change HRRM, its acceptance scope or production.
Other projects must review their own command, dependencies, tests and controls;
copying Superretometer's Python test list is not project acceptance.

Capture/check return nonzero on rejection. `check` returns zero only after
baseline approval, correct negative controls and final bundle verification.
An empty report or a zero command exit with no observed tests cannot pass.

## Large repositories

Observation reuses one NUL-delimited Git index snapshot for tracked membership;
Git process count does not grow with the source count. Every declared file is
still hashed; full coverage selects all tracked regular files. This
removes subprocess fan-out, not filesystem/hash/JSON costs; benchmark actual
large repositories before claiming throughput. A timeout or missing receipt is
BLOCKED evidence, not permission to substitute a manual passing count.

Measure filenames with NUL delimiters (not bytes or filesystem entries):

```sh
git rev-parse --show-toplevel
git ls-files -z | python3 -c 'import sys; print(sys.stdin.buffer.read().count(b"\0"))'
```

A sparse/smaller checkout does not automatically redefine the tested source set.
Do not remove tracked files, weaken coverage, or reuse old receipts to force a
pass. A deliberately narrower acceptance scope needs a separately reviewed
contract and policy.

## HA / resource preflight

The merge adapter applies operational budgets before hashing a large selected
source set or parsing an oversized incoming receipt. It does **not** narrow
coverage, waive tests, cache away freshness observations, or change gate/warrant
semantics to meet a budget. Full coverage remains the default. A budget rejection
requires a reviewed policy decision, not a manual passing count.

Default limits (operational choices, not measured performance guarantees):

| Field | Default | Boundary |
|---|---:|---|
| `max_source_files` | 10,000 | Selected sources, and sources declared in an incoming receipt |
| `max_receipt_bytes` | 16,777,216 | `run.json` bytes before check parses it; finalized receipt size after record |
| `operation_timeout_seconds` | 900 | CLI worker lifetime: startup, preflight, record/verify, controls and export |

Policies may explicitly override any of these keys in an optional
`resource_limits` mapping. Unknown keys, booleans, zero/negative/nonfinite values,
and fractional file/byte counts reject. Raising a limit is a reviewed resource
decision and does not imply bounded coverage. Limits are enforced independently
by the verifier and policy changes invalidate the capture policy binding.

```json
"resource_limits": {
  "max_source_files": 10000,
  "max_receipt_bytes": 16777216,
  "operation_timeout_seconds": 900
}
```

Before expensive work, inspect scope without running tests or producing approval:

```sh
python /reviewed/ch/scripts/ch_merge_guard.py capture \
  --policy /reviewed/policy.json --repo /candidate \
  --expected-commit "$TEST_SHA" --expected-remote "$REPOSITORY_URL" \
  --output /new/capture --preflight
```

Successful preflight exits 0 with `status: preflight`, **`approved: false`**,
repository/commit, coverage mode, selected source count and effective limits.
Check preflight additionally reports receipt bytes and declared source count.
It does not establish passing tests, byte integrity or gate acceptance, and
creates no output directory. Existing output paths reject before expensive
verification; use a new path rather than deleting audit evidence.

Full/bounded source selection, runner and in-worktree policy minimum sets retain
their existing requirements. Bounded policies require all three fields:
`coverage_mode: bounded`, `source_paths`, and a nonblank `coverage_rationale`.
The script, operational runtime and policy have separate identities recorded in
receipt tool observations and compared during check. A metadata hash is not
producer authentication.

CLI diagnostics are NDJSON on **stderr** (`ch-progress`): preflight, record,
receipt verification, import, each named control, export and final verification.
Five-second supervision heartbeats identify an active worker; they are not
claims of progress or proof that the worker is healthy. **stdout remains one
final JSON document**, so existing machine readers can keep parsing it.

The POSIX CLI supervises an isolated process group. On deadline, Ctrl-C or SIGTERM it
kills the worker group and returns nonzero with `approved: false`; buffered
worker output cannot publish premature approval. Partial artifacts are retained
without being promoted to finalized evidence. Process reap/OS scheduling can add
cleanup latency. Unsupported hosts reject rather than silently omit supervision.
Direct Python `capture`/`check` API calls enforce count/size limits but require
their caller to supervise wall time. Other #18 CLI commands are unchanged.
The existing `timeout_seconds` still bounds the test command, not the complete
adapter operation. An outer CI job deadline should allow worker cleanup.

This is not a complete memory/CPU/network quota: source selection still examines
the Git index, Git/worktree/submodule checks remain, and receipt byte limits do
not limit every log or exported artifact. Container/runner quotas remain external.

### Learning case: oversized full coverage

The operator reported a full capture of 570,510 files with a 243.06 MB receipt
for ten application tests. Bounded re-capture selected seven reviewed paths;
the project's own audit bundle binds the exact candidate and ten executed tests.
The operator measured approximately 10 s capture and 8 s check; these timings
were not independently reproduced by this change. This is an operational lesson
and regression fixture, not a claimed automatic H2 run or a new application approval.
Historical application evidence and its pinned guard revision remain unchanged.

## Trust boundary and H2

The recorder is not an independent observer. Malicious candidate/test code can
fabricate apparently plausible test output or manipulate its ephemeral capture
runner; hashes do not authenticate a producer. Separate verification prevents
candidate code from being run with the check-publishing credential, but does
not turn reported observations into mathematical proof. Infrastructure and
protected reviewer credentials remain trusted.

Changes to tests, evaluator, policy, workflows, dependencies or CODEOWNERS require
independent human review. H2 cannot grant itself bypass, loosen the acceptance
policy for its current PR or treat a dependent runner as independent evidence.
No automatic merge, live Memory import, deployment or nightly scheduler is added.

Measure H2's accepted improvements, regressions caught and developer time saved
before expanding automation. Routine coding stays on a branch; this control is
at the merge boundary, not a checkpoint required after every edit.
