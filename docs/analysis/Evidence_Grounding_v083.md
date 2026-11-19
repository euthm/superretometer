# Evidence Grounding v0.8.3

## Scope

Ground the 12 Evidence KOs for CP-010 through CP-013 with real Git blob SHAs, commit SHAs, and file paths. Fix the `list_evidence_for_ko` ID-resolution bug in the Memory adapter.

## Changes

### Evidence Lookup Fix — `memory_adapter.py`

**Problem:** `list_evidence_for_ko` failed to match Evidence KOs to their Claims after `adopt_existing_ko` because:
- `content.claim_id` stores the Memory UUID (physical entity ID)
- `claim.id` is the CH logical ID (e.g., `cp-010-claim`)
- The equality check `ev["claim_id"] == claim.id` always fails

**Fix:**
1. `get_evidence` now prefers the graph edge's CH ID over content-level `claim_id`
2. `list_evidence_for_ko` resolves both CH ID and Memory UUID via `_resolve_ch_id()`, then matches against the set `{ch_id, memory_uuid}`

**Tests:** 8 regression tests in `test_evidence_lookup_fix.py` covering:
- Evidence lookup by CH ID after adoption
- Evidence lookup by Memory UUID
- Graph edge preference over content
- Fallback chain: edge → content → empty string
- No duplicate evidence
- Mixed Memory/CH lookup consistency
- Cache invalidation

### Evidence Grounding — CP-010 to CP-013

Each of the 4 claims has 3 evidence items (spec, impl, test), all grounded with Git artifacts:

| Evidence | Artifact | Blob SHA | Commit | Path |
|----------|----------|----------|--------|------|
| CP-010 spec | cp-registry.md | `8bb0dd83` | `8e4e1a0` | rocom-standard/spec/cp-registry.md |
| CP-010 impl | topics.rs | `d3f36f35` | `a27635cb` | rocom-hrrm/rocom-connectors/src/topics.rs |
| CP-010 test | cargo test | — | `a27635cb` | 32 tests pass (topics module) |
| CP-011 spec | cp-registry.md | `8bb0dd83` | `8e4e1a0` | same |
| CP-011 impl | topics.rs | `d3f36f35` | `a27635cb` | same |
| CP-011 test | cargo test | — | `a27635cb` | same |
| CP-012 spec | cp-registry.md | `8bb0dd83` | `8e4e1a0` | same |
| CP-012 impl | topics.rs | `d3f36f35` | `a27635cb` | same |
| CP-012 test | cargo test | — | `a27635cb` | same |
| CP-013 spec | cp-registry.md | `8bb0dd83` | `8e4e1a0` | same |
| CP-013 impl | topics.rs | `d3f36f35` | `a27635cb` | same |
| CP-013 test | cargo test | — | `a27635cb` | same |

### Warrant Status

All 4 claims remain **unwarranted** after grounding. This is correct: having evidence KOs with blob SHAs does not constitute independent verification. The three independent-roots requirement for `warranted` status is not met because:

1. The spec evidence and implementation evidence share the same commit provenance lineage (both from the same development effort)
2. Test evidence (cargo test output) is not independently captured — no CI log, no SHA'd report artifact
3. Individual spec files (cp-010.md through cp-013.md) are untracked in rocom-standard; only cp-registry.md provides committed normative evidence

## Limitations

- Individual spec files exist on disk but are not tracked in git — cannot produce blob SHAs for them
- No CI/CD pipeline output to serve as independent test verification
- rocom-server has compilation errors in integration tests — only rocom-connectors library tests are viable evidence
- `enumeration_complete` is NOT set to `True` — the evidence set may be incomplete

## Verification

- Evidence lookup regression tests: 8/8 pass
- rocom-connectors tests: 32/32 pass
- Scoped enumeration: 16/16 KOs present, 0 missing, 0 review required
