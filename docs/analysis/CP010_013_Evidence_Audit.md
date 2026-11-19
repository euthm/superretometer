# CP-010 to CP-013 Evidence Audit

## Audit Date

2026-11-19

## Scope

Four claims in the Superretometer knowledge graph, each with 3 Evidence KOs:
- CP-010: Connector liveness (MQTT keepalive / LWT)
- CP-011: Door state reporting (state machine)
- CP-012: Elevator boarding coordination
- CP-013: Lease release and zone return

## Evidence Inventory

### Claim-Level Memory IDs

| Claim | CH ID | Memory UUID |
|-------|-------|-------------|
| CP-010 | `cp-010-claim` | `cc24d523-...` |
| CP-011 | `cp-011-claim` | `bf32637c-...` |
| CP-012 | `cp-012-claim` | `ffa11f53-...` |
| CP-013 | `cp-013-claim` | `d0bb9d5c-...` |

### Evidence Artifacts

#### Spec Evidence (Shared)

All four claims cite the same normative source:

- **File:** `rocom-standard/spec/cp-registry.md`
- **Blob:** `blob 8bb0dd8399a537b1342007d070de036c75f79116`
- **Commit:** `8e4e1a05d70655bb56aaa0fb179b5024a6219001`
- **Content:** Registry entries marking CP-010 through CP-013 as IMPLEMENTED with rocom-connectors reference
- **Status:** Committed, tracked, normative

**Limitation:** Individual spec files (`cp-010-connector-liveness.md` through `cp-013-lease-return.md`) exist on disk but are **untracked** in git. They cannot serve as blob-grounded evidence until committed.

#### Implementation Evidence (Shared)

All four claims cite the same implementation:

- **File:** `rocom-hrrm/rocom-connectors/src/topics.rs`
- **Blob:** `blob d3f36f357ecce79c47448c28cbc2f9df40294395`
- **Commit:** `a27635cbaee1796ec66f0d21cdd68305e502179e`
- **Content:** MQTT topic constructors, door/elevator/lease topic patterns
- **Status:** Committed, tracked

#### Test Evidence

- **Command:** `cargo test -p rocom-connectors`
- **Result:** 32 tests pass, 0 fail
- **Relevant tests:** `topics::tests::*` (11 tests covering door, elevator, liveness, lease topics)
- **Status:** Passes locally; no CI log or SHA'd report artifact

## Warrant Assessment

### CP-010 (Connector Liveness)

| Root | Evidence KO | Type | Independent? |
|------|-------------|------|-------------|
| 1 | Spec (cp-registry.md) | Documented decision | No — shares commit lineage with impl |
| 2 | Impl (topics.rs) | Implementation | No — same repo, same commit |
| 3 | Test (cargo test) | Validation result | Partially — test is independent code, but output not SHA'd |

**Warrant: UNWARRANTED** — 0 roots meet independent verification threshold.

### CP-011 (Door State)

Same structure as CP-010.

**Warrant: UNWARRANTED**

### CP-012 (Elevator Boarding)

Same structure as CP-010.

**Warrant: UNWARRANTED**

### CP-013 (Lease Return)

Same structure as CP-010.

**Warrant: UNWARRANTED**

## Path to Warranted

For each claim to reach `warranted` status, at least 3 independent evidence roots are needed:

1. **Commit individual spec files** to rocom-standard (currently untracked) — provides distinct blob SHAs per CP
2. **CI/CD pipeline** — GitHub Actions or equivalent with SHA'd test output
3. **External verification** — e.g., MQTT integration test against live broker, with captured output

## Evidence Lookup Bug Fix

The `list_evidence_for_ko` function in `memory_adapter.py` had an ID mismatch bug:
- After `adopt_existing_ko`, Evidence KOs' `content.claim_id` contains the Memory UUID
- Queries use the CH logical ID (e.g., `cp-010-claim`)
- Fix: resolve both IDs and compare against set

8 regression tests verify the fix. All pass.

## Conclusion

Evidence KOs are properly grounded with Git artifacts. Claims remain unwarranted because the evidence, while real, lacks the independent verification required by Superretometer warrant rules. This is a correct assessment — having blob SHAs is necessary but not sufficient for warrant.
