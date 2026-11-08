# add-portable-test-evidence-workflow

Status: PROPOSED; additive spec review required before merge. Implements #18.

### proposal.md — Why / What / Impact

**Why:** Evidence should be collected by a runner, not reconstructed by an agent after execution. A successful domain test, valid artifact integrity, implementation-gate acceptance and epistemic warrant are distinct results.

**What:**
1. A versioned, runner-independent TestRunReceipt contract.
2. A local execution/capture SDK with a reference CLI.
3. Receipt integrity verification and explicit import through the proposal pipeline.
4. Gate/warrant evaluation snapshots tied to exact inputs and policy versions.
5. A portable, checksummed evidence bundle and storage interface.

**In scope:** command-based test runners for any project/language; local filesystem bundles; the public InMemory reference; optional persistent-adapter integration; CI-compatible noninteractive operation.

**Out of scope:** a new orchestration harness, remote shell service, project-specific test logic, automatic merge/deploy, replacing Memory, generic artifact hosting, changing independence defaults or warrant truth categories, mandatory cloud signing/attestation.

The first reference example mirrors the successful/negative database-test workflow using public, controlled fixtures. A real Rust/PostgreSQL pilot is an optional integration profile, not a dependency of the public conformance suite.
