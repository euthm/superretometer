# Design and delivery boundary

### design.md — Responsibilities and trust boundary

| Layer | Responsibility |
| --- | --- |
| Project runner | Own domain assertions, expected cases, environment/service setup and teardown. |
| Capture SDK / CLI | Observe the actual command, code state, execution and artifacts; emit a receipt. |
| Core verification/orchestration | Validate receipt/bundle contracts, import through proposals, expose incomplete work, invoke existing policies. |
| Existing analyzers | Compute gates and warrant; remain read-only and separate from storage. |
| Storage/archive adapters | Persist KOs, mappings, bundles and locators; do not compute warrant or invent evidence. |

Public implementation must work with InMemoryStorage and a filesystem archive, with no private project IDs, home paths, accounts, tokens, database conventions or Memory/StrategyServer dependency.

**Trust model:** receipt verification establishes format validity, byte integrity and observable bindings within a stated trust boundary. A checksum is not an authenticity proof. A locally produced receipt is runner-reported evidence, not independent certification. Preserve the explicit N-IMPL-SELFCONSISTENCY boundary. Report capture/verification origin; never manufacture independence or promote truth categories to obtain PASS.

#### Receipt contract — required observations

| Group | Minimum content |
| --- | --- |
| Identity | Schema version, unique run ID, timezone-aware start/end timestamps, producer/runner identity and version. |
| Code | Sanitized canonical remote; full Git object ID and object format; optional branch; measured pre/post worktree state; complete diff fingerprint when dirty; source paths/digests and digest-algorithm versions. |
| Dependencies/environment | Relevant lockfile digests, observed submodule pins/initialization state, tool versions, OS/architecture and relevant service/image versions; explicit exclusions. |
| Execution | Argument vector, working-directory mapping, actual child exit code, timeout/signal outcome, parser identity/version. Commands execute only on explicit operator invocation. |
| Test observations | Discovered/executed/passed/failed/skipped counts when supported, otherwise unknown; selected test IDs and operator-declared acceptance constraints where applicable. |
| Artifacts | Relative name, role, byte length, SHA-256 and explicit local/archive locator; original logs, structured result, optional JUnit/coverage. |
| Claim/validation | Bounded claim scope, requested repository/commit binding, falsifier declaration, origin of declarations versus measured observations. |
| Capture completeness | Complete/incomplete/not-run state and explicit reasons; missing information never becomes a clean worktree, exit 0 or zero skipped tests. |

All status fields are typed. Distinguish execution failure, inability to execute, policy BLOCK and policy UNKNOWN. Failed, interrupted, blocked and skipped runs are retained. A nonzero domain result cannot be converted to success by a shell pipe or a successful report-writing step.

**Worktree and freshness:** capture code state before and after execution; output lives outside the tested worktree. Record staged, unstaged and relevant untracked changes, source-path coverage and dependency changes. Dirty state remains dirty. Document the limits of pre/post observation.

Use one shared, versioned digest implementation across capture and verification. Preserve the meaning of existing legacy `blob_digest` values; do not silently replace their algorithm. A receipt additionally binds each normalized path to its size and SHA-256 in an unambiguous manifest. Missing declared files, ambiguous paths and digest mismatches cannot yield verified freshness. New digest semantics/migrations require explicit specification and conformance changes.

**Separation of records:**
- Finalized execution receipt is immutable by content identity; each retry is a new run.
- Evaluation snapshots are separate: receipt hash, KO/input identities or exported graph snapshot, policy/package commit/version, evaluation timestamp, raw gates, warrant and observed verification context.
- Re-evaluation creates a new snapshot; never overwrite the original verdict.
- A documentation commit may follow a tested code commit; retain both identities.
- Exact byte encodings/canonicalization, manifest coverage and hash exclusions must be specified in the schemas/contract so no field hashes itself or creates a receipt/evaluation cycle.

**Import:** target backend/project and local repository mappings come from explicit operator configuration, not receipt-controlled paths. Validate first; orchestrate proposals and read back claim, evidence, validators and relations using public storage methods. Preserve CH IDs separately from backend UUIDs. Persist import mappings keyed by target and receipt identity. Reimport must not duplicate entities/edges; conflicting content or incomplete prior writes are explicit. If an adapter cannot provide the needed identity/concurrency capability, report unsupported/incomplete rather than pretending idempotency.

**Offline review:** bundle verification checks archive bytes and recorded snapshots without a live Memory service. Re-evaluating freshness requires an explicitly mapped, matching checkout or sufficient versioned source evidence. Missing code/backend access yields an explicit unevaluated/UNKNOWN result; it must not turn a historical gate snapshot into a new current PASS.

#### Proposed public surface

Names below are proposed, not existing commands:
- `superretometer evidence record --config <profile> -- <argv...>`
- `superretometer evidence verify <bundle-or-receipt>`
- `superretometer evidence import <receipt> --target <configured-target>`
- `superretometer evidence evaluate <import-reference>`
- `superretometer evidence export <evaluation-reference> --output <path>`

Offer equivalent Python APIs. Preserve existing CLI/MCP compatibility. MCP may expose verification, proposal-backed import, evaluation and export; **do not expose arbitrary command execution through imported documents/receipts or implicit MCP evaluation**. Recording a new test run remains an explicitly invoked runner operation.

Commands emit machine-readable status and operation-specific exit codes. An end-to-end approval command, if provided, exits successfully only when the domain acceptance requirements, receipt integrity checks and required implementation gates pass. Keep the child's original exit code separately. `design_bearing` remains the computed policy field; do not redefine it or equate it with WARRANTED, production approval or independent verification.

#### Storage and third-party bundle

Proposed bundle:
- `README.md`: claim, scope, limitations and reproduction instructions.
- `run.json`: execution receipt.
- `test-results.json` and/or `test-results.xml`: actual machine-readable results.
- `evaluations/<evaluation-id>/gates.json` and `warrant.json`: original responses.
- `graph.json`: necessary scoped claim/evidence/validator/relation snapshots and import mappings, not a whole private KB dump.
- `logs/` and referenced artifacts.
- `SHA256SUMS`: unambiguous coverage of included files, excluding the manifest itself; optional detached signature later.

The bundle must include everything needed to interpret and integrity-check its selected evidence. If external files remain, enumerate them and report offline completeness accurately.

Keep test code, small fixtures, expected/golden results, runner config and a compact evidence index in Git. Store bulk actual outputs as per-run artifacts in the configured archive. Do not overwrite expected results with actual outputs to pass a test. Require an explicit retention policy and durable locator/checksum for third-party records; a temporary CI URL alone is not a durable archive.

A release-level signature/attestation is an optional later extension. It authenticates an issuer/binding, not correctness of a test or independent review. Do not require signing every routine test run.

Redact credentials before persistence. Preserve whether an artifact was transformed/redacted, its derivation and the hash of the exported bytes; never silently call a redacted copy the original raw log. Imported archive paths must not escape the chosen directory; do not trust remote absolute paths or follow unsafe symlinks.


## Reference implementation boundary

The first public implementation provides the complete CLI/SDK path with a POSIX-locked portable filesystem target and explicit restoration into InMemoryStorage. Native Memory/remote archive/CI project profiles are optional future adapters; other configured backends fail explicitly. No MCP execution tool is added. See spec/TEST_EVIDENCE.md for exact byte contracts, evidence trust, parser limits and compatibility. Evaluation snapshots export the exact bounded graph. The example intentionally runs no HRRM application tests.
