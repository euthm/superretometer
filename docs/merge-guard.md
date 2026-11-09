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
   including tests, runner, policy and configuration. Submodules use #18 pins;
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
