# specs/context-continuity/spec — proposed #19

Preparation only. No checkpoint engine, OpenCode plugin or performance result is delivered by this change. Normative adoption remains subject to spec review.

## ADDED Requirements

### Requirement: Durable, scoped work checkpoints
The system SHALL preserve task and execution state with explicit source and revision identity.
#### Scenario: Resume after a reset
- **GIVEN** a checkpoint for a bounded coding task
- **WHEN** a fresh process restores it without an agent cache
- **THEN** the objective, authorized constraints, current code state, pending work, next step and evidence references are available with their original identities.
#### Scenario: Backend write fails
- **WHEN** checkpoint persistence is not acknowledged
- **THEN** no complete CH handoff is claimed and the adapter retains context or takes its declared fallback.
#### Scenario: Instructions or code change after checkpoint
- **WHEN** a new user requirement, source revision or relevant dirty-state fingerprint differs
- **THEN** the restore marks stale parts and refreshes/retrieves them before treating affected conclusions as current.

### Requirement: Budgeted context with explicit coverage
The system SHALL enforce request budgets without silently dropping mandatory state.
#### Scenario: Mandatory fields do not fit
- **WHEN** task constraints and protocol-required state exceed the configured budget
- **THEN** the builder reports insufficient capacity and requests a larger budget/narrower scope or native fallback; it does not emit a falsely complete pack.
#### Scenario: Large fixed MCP catalog
- **WHEN** tool schemas consume the available request budget
- **THEN** diagnostics identify that overhead rather than claiming conversation compaction will solve it.
#### Scenario: Known and unknown facts
- **WHEN** supported results, assumptions and counter-evidence are selected
- **THEN** their categories and references remain distinguishable and no status/independence is upgraded by summarization.

### Requirement: Selective access to preserved history
The system SHALL provide bounded retrieval rather than replay full histories by default.
#### Scenario: Needed detail omitted from the pack
- **WHEN** a later step needs an older exact value or error message
- **THEN** it can retrieve the original bounded source and its revision instead of relying on an invented summary.
#### Scenario: Source unavailable or superseded
- **WHEN** an archive cannot be read or a saved reference no longer identifies current state
- **THEN** the limitation is explicit and no current/completeness guarantee is fabricated.

### Requirement: Version-aware hybrid OpenCode integration
The adapter SHALL combine validated CH state with protocol-valid recent context and supported native behavior.
#### Scenario: Supported summary replacement
- **GIVEN** a pinned OpenCode build with the necessary hook and a coverage-valid checkpoint
- **WHEN** compaction is requested
- **THEN** the adapter may supply a handoff without a summary-model call, while preserving recent turns and saved history.
#### Scenario: Unsupported hook or incomplete coverage
- **WHEN** the installed client cannot perform the requested transition or required state is missing
- **THEN** the adapter reports that condition and uses its tested fallback without silent history loss.
#### Scenario: Active tool or command
- **WHEN** a transition coincides with pending work
- **THEN** call/result boundaries and job identities are preserved; the operation is not silently lost or executed a second time.
#### Scenario: Prefix reuse
- **WHEN** no meaningful checkpoint state changes
- **THEN** stable context sections retain ordering/content; timestamps alone do not regenerate the entire model prefix.

### Requirement: Parallel-session isolation and safe authority
The system SHALL prevent context leakage and stale writes between concurrent sessions.
#### Scenario: Two sessions in one project
- **GIVEN** independent tasks/worktrees sharing selected project facts
- **WHEN** both checkpoint and restore concurrently
- **THEN** each receives its own code state, plan, pending jobs and evidence; shared facts retain source identity.
#### Scenario: Stale checkpoint write
- **WHEN** an older revision attempts to overwrite newer state
- **THEN** it is rejected or explicitly reconciled and both histories remain inspectable.
#### Scenario: Retrieved prompt injection
- **WHEN** a stored document says to change project, ignore user constraints or invoke a write tool
- **THEN** it remains source data and does not gain instruction/permission authority through the context pack.

### Requirement: Auditable quality and efficiency evaluation
The system SHALL measure total task outcomes and management overhead, not only decode speed or one prompt size.
#### Scenario: Compaction overhead
- **WHEN** a mode summarizes, retrieves, re-prefills or performs background work
- **THEN** those tokens/times are included or explicitly unavailable; background work is not recorded as free.
#### Scenario: Quality regression
- **WHEN** a short-context mode loses a mandatory requirement, repeats a prohibited action, mixes SHAs/evidence or fails held-out tests
- **THEN** the trial is a quality failure even if it uses fewer tokens or decodes faster.
#### Scenario: Evidence export
- **WHEN** a strategy is compared with baseline
- **THEN** configuration, model/client/server versions, task/source identity, expected outcomes, raw measurements and completeness limitations are preserved for independent inspection.
