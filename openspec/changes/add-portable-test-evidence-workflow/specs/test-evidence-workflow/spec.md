# Test evidence workflow — proposed delta

## ADDED Requirements

### Requirement: Automatic execution evidence capture
The system SHALL record observed execution and code state without manually asserted PASS defaults.
#### Scenario: Successful scoped run
- **GIVEN** a clean fixture checkout and a test profile requiring eight executed tests with no failures/skips
- **WHEN** the runner executes the eight tests successfully
- **THEN** the receipt contains measured identity, pre/post state, counts, exit code and artifact hashes, without editing KO metadata by hand.
#### Scenario: Failed, unexecuted or incomplete run
- **WHEN** a command fails, times out, cannot start, reports required skips, or no trustworthy parser result is available
- **THEN** actual outcomes are preserved and no unsupported complete-test approval is emitted.

### Requirement: Reproducible code-state binding
The system SHALL distinguish commit identity, worktree state and path-scoped freshness.
#### Scenario: Dirty checkout
- **WHEN** a tracked or relevant untracked input changes
- **THEN** the captured state is dirty with a recorded diff, and the existing policy's worktree limitation is preserved.
#### Scenario: Source path missing or source drift
- **WHEN** a declared source file is absent, changes, or its path/content manifest mismatches
- **THEN** freshness verification cannot pass and reports the precise unavailable/mismatch reason.
#### Scenario: Capture mutates code
- **WHEN** pre/post source or dependency state differs
- **THEN** the receipt records the change and cannot represent the run as a clean test of the original commit.

### Requirement: Typed, versioned and honest evidence
The system SHALL separate measured facts, declared scope, falsifiers, policy verdicts and trust origin.
#### Scenario: Unsupported schema or digest algorithm
- **WHEN** a receipt uses an unknown required version/algorithm
- **THEN** import/verification rejects or explicitly reports unsupported; it never guesses a compatible PASS.
#### Scenario: Metadata-only legacy claim
- **GIVEN** an existing claim without a receipt
- **WHEN** it is evaluated through the old API
- **THEN** existing semantics remain explicit and no execution receipt, independent source or past artifact is fabricated.
#### Scenario: Parser cannot count tests
- **WHEN** the runner knows exit code but cannot establish test counts
- **THEN** counts remain unknown, and a claim requiring eight executed tests is not approved from exit 0 alone.

### Requirement: Proposal-backed durable import
The system SHALL preserve import identity, evidence direction and replayable mappings through public contracts.
#### Scenario: Reimport same receipt
- **WHEN** the same verified receipt is imported twice into the same configured target
- **THEN** the existing mapping/IDs are returned and no duplicate carrying evidence/edges are created.
#### Scenario: Same run ID with different content
- **WHEN** a run identity is reused with changed content
- **THEN** the conflict is explicit and historical evidence is preserved.
#### Scenario: Restart or partial backend write
- **WHEN** a new process loads a receipt import or resumes an interrupted import
- **THEN** persisted mappings and readback establish its real state; incomplete graph writes are not reported as accepted evidence.

### Requirement: Discriminating implementation controls
The workflow SHALL evaluate the existing seven gates with explicit, scoped inputs.
#### Scenario: Positive control
- **GIVEN** complete measured evidence for the scoped fixture claim
- **WHEN** imported and evaluated
- **THEN** all seven required implementation gates pass and the computed design_bearing is true; warrant is reported independently.
#### Scenario: Isolated commit mismatch
- **GIVEN** an explicit test-only copy of the positive control's claim/provenance, retaining the original immutable execution receipt
- **WHEN** only the commit binding is made inconsistent (tested_commit differs from claim commit)
- **THEN** test is BLOCK for SHA mismatch, design_bearing is false, and unrelated gates keep their baseline results. The mutation is recorded as a negative-control input, never as a genuine new execution receipt.
#### Scenario: Missing validator evidence
- **GIVEN** the same positive baseline
- **WHEN** only the required validator binding is removed
- **THEN** test is UNKNOWN under the existing policy and design_bearing is false.
#### Scenario: Artifact byte tampering
- **WHEN** a bundled result or gate-response file is modified without its recorded digest changing
- **THEN** integrity verification rejects it before it can be presented as verified receipt evidence.

### Requirement: Portable historical export
The workflow SHALL preserve evaluations and support third-party inspection without the producer's Memory session.
#### Scenario: Offline bundle verification
- **WHEN** a reviewer receives the complete bundle without producer credentials or a Memory connection
- **THEN** they can inspect scope/provenance, verify included bytes and identify exactly which tests/evaluations occurred and which were not run.
#### Scenario: New evaluation
- **WHEN** source state or policy version changes and evidence is re-evaluated
- **THEN** a new identified snapshot is appended; the previous snapshot remains unchanged.
#### Scenario: Archive expiry or missing checkout
- **WHEN** required external evidence or mapped source is unavailable
- **THEN** the report identifies the missing material and does not claim current verification from a historical PASS.
#### Scenario: Unsafe archive member or secret
- **WHEN** a bundle attempts path traversal or export contains configured sensitive fields
- **THEN** unsafe access/export is rejected or explicitly transformed/redacted with provenance; no silent credential disclosure occurs.
