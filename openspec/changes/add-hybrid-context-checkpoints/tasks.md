# Issue #19 tasks and current delivery

## Preparation (this PR)

- [x] Preserve issue proposal/design/scenarios as review artifacts.
- [x] Define A–E comparisons, total-request budgets and paired acceptance proposals.
- [x] Define twelve functional/negative controls and fixed-oracle requirements.
- [x] Add nonintrusive version/environment probe with honest unknown measurements.
- [x] Test preparation tooling without model calls or client setting changes.
- [x] Reuse #18 evidence contract as prerequisite, without duplicating its runner.

## Implementation (not delivered here)

- [ ] Review proposed `spec/CONTEXT_CONTINUITY.md` and versioned checkpoint/pack
      schemas before normative adoption; preserve warrant/permission semantics.
- [ ] Implement scoped checkpoint identity, source/steering provenance, durable
      acknowledgement, exact retrieval and revision/CAS conflict controls.
- [ ] Build deterministic budgeted packs with explicit coverage/omissions, stable
      prefixes and capacity failure for mandatory-state overflow.
- [ ] Add explicit checkpoint restore in fresh processes, source drift validation,
      archive/source failure and active-command/call-boundary handling.
- [ ] Implement executable tests for every scenario/control, including wrong SHA,
      unsafe source instructions, failed approach, stale updates and isolation.
- [ ] Pin and verify the actual installed OpenCode version and matching plugin SDK.
- [ ] Implement one supported adapter with native fallback; no automatic client
      migration/upgrade and no unconditional summary bypass.
- [ ] Collect fixed-overhead/tokenizer/server-slot facts on the target machine.
- [ ] Review/freeze pilot criteria before trials, then run A/B/C with #18 receipts.
- [ ] Only after single-session quality passes, verify device/slot capacity and
      run D/E in separate worktrees with complete cost accounting.
- [ ] Export reproducible outcomes including negative/inconclusive results and
      limitations; do not report throughput or complete memory before measuring.

Normative source remains `spec/`. These review artifacts do not initialize an
OpenSpec CLI or install a plugin. Remote merge/deployment of #18 is independent
of the user's already reported local fast-forward; verify each separately.
