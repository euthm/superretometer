# Harness Test Findings — 2026-11-07

**Run:** `3b9712e5-e400-4a8a-a7b9-0662f7161865`  
**Project:** Tech Happens (`229d3378-5eda-42ab-9bfa-133f6360cd34`)  
**Superretometer:** v0.7.0, MemoryAdapter, persistent_graph  
**Memory Server:** v0.90.1, commit a29f8ec

---

## Finding 1: `create_evidence` stores evidence but warrant does not see it

### Evidence lifecycle trace

1. `submit_proposal(type=create_evidence, evidence_claim_id=X, evidence_observation=Y)`  
   → Returns `proposal_id`, state `pending`

2. `execute_proposal(proposal_id)`  
   → Calls `MemoryAdapter.add_evidence()` at `memory_adapter.py:1106`

3. `add_evidence()` does three things:
   a. Stores evidence dict in-memory (`self._evidence[evidence_id]`)
   b. Creates a Memory `Concept` object with `ch_ko_type=evidence`
   c. Calls `_create_edge(evidence_id, claim_id, RelationType.SUPPORTS)` — **always SUPPORTS**
   d. Appends `evidence_id` to claim's `evidence_ids` property

4. Warrant analyzer (`warrant_analyzer.py:71-228`) traverses the justification graph via:
   - `_collect_justification_path()` → BFS through `JUSTIFICATION_INBOUND` relations (SUPPORTS, VALIDATES)
   - Uses `storage.get_incoming_relations(ko_id, JUSTIFICATION_INBOUND)` to find evidence
   - `MemoryAdapter.get_incoming_relations()` → calls `_get_edges()` → `Memory /api/graph/objects/{uuid}/edges`

### Root cause

The edge created by `_create_edge()` at line 1131 uses CH IDs (`ev-b9eda7d6-...`, `afe5c3ad-...`) as `src_id`/`dst_id`. Memory's relationship API expects **UUIDs**, not CH IDs. The relationship may fail silently (returns `False` on HTTP error) or create a relationship between wrong endpoints.

Even if the edge succeeds, warrant's `_collect_justification_path()` resolves the edge's `src_id` through `_resolve_to_ch_id()`, which may fail to map the Memory UUID back to the CH ID if the lookup cache is not populated.

The warrant analyzer reports `evidence_count: 0` because `get_incoming_relations()` returns empty — no SUPPORTS edges are found in the Memory graph for the claim KO.

### Classification

- `evidence_ids` is updated correctly on the KO (verifiable via `get_ko`)
- The graph edge is either not created, or not discoverable by warrant
- **Internal evidence** (`evidence_ids` property) and **independent evidence** (graph-traversable SUPPORTS edges) are fundamentally different — warrant only sees the latter

### Fix

1. `_create_edge()` must use Memory UUIDs, not CH IDs. Resolve both `evidence_id` and `claim_id` through `_resolve_ch_id()` before calling the Memory API.
2. After creating the edge, verify it appears in `get_incoming_relations()` of the target KO.

---

## Finding 2: `IncompleteEnumerationError` — root cause identified

### Error chain

```
scan_anti_patterns() → detect_all_anti_patterns()
  → storage.enumeration_complete check
  → MemoryAdapter.enumeration_complete = False (memory_adapter.py:341)
  → raises IncompleteEnumerationError
```

### Root cause

`enumeration_complete` is hardcoded to `False` in MemoryAdapter because the HTTP search API cannot guarantee complete enumeration of all KOs. The comment at line 338 states:

> enumeration_complete = False because HTTP search API is not provably complete.

Similarly, `justification_path` fails with `'NoneType' object has no attribute 'source'` — a separate backend issue where `superretometer_justification_path` calls `storage.get_ko()` for a KO ID that the adapter cannot resolve to a Memory UUID (the `_resolve_ch_id()` lookup fails).

### Classification

- **Memory side:** No bug. The API works as designed — it returns objects that exist and are not deleted.
- **Adapter side:** `enumeration_complete = False` is a design decision, not a bug. It causes `FULL_REQUIRED` analyses (like `scan_anti_patterns`) to fail closed.
- **Warrant analyzer:** `justification_path` error suggests a KO resolution failure — the adapter tried to read a KO whose Memory UUID it couldn't find.

### Fix

1. `enumeration_complete = False` is acceptable for the Memory adapter. Document that `scan_anti_patterns` is unavailable with this backend.
2. `justification_path` error needs investigation into the `_resolve_ch_id()` failure path.

---

## Finding 3: Counter-evidence mechanism is missing

### Model supports it

`RelationType.CONTRADICTS` is defined in `ko.py:132`:
```python
class RelationType(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    ...
```

Warrant analyzer uses it at `warrant_analyzer.py:580-647` for checking physical unrealizability and constraint contradictions.

### Submission path does NOT

`add_evidence()` at `memory_adapter.py:1131` creates **only** `SUPPORTS` edges:
```python
self._create_edge(evidence_id, claim_id, RelationType.SUPPORTS.value)
```

`submit_proposal` with `type=create_evidence` has no parameter for `contradicts` or `direction`. The MCP tool signature shows:
- `evidence_claim_id` — target claim
- `evidence_observation` — text observation
- **No direction flag**

### `CONTRADICTS` is not in `JUSTIFICATION_INBOUND`

`ko.py:162-165`:
```python
JUSTIFICATION_INBOUND = frozenset({
    RelationType.SUPPORTS,
    RelationType.VALIDATES,
})
```

Even if a `CONTRADICTS` edge existed, warrant's `_collect_justification_path()` would not traverse it.

### Fix

1. Add `direction` or `relation_type` parameter to `create_evidence` proposal
2. Modify `add_evidence()` to respect the direction and create `SUPPORTS` or `CONTRADICTS` edge accordingly
3. Add `CONTRADICTS` to a new `CONTRADICTION_INBOUND` set and have warrant check for contradictions separately from support
4. Warrant should downgrade status to `UNWARRANTED` when any `CONTRADICTS` edge targets the conclusion

---

## Finding 4: Entity search returns soft-deleted objects

### Root cause

MCP handler `executeSearchEntities()` at `service.go:2829`:
```go
WHERE go.deleted_at IS NULL  // line 2918
// Missing: AND go.supersedes_id IS NULL
```

Soft delete creates a NEW version (tombstone) with `deleted_at` set. The old version gets `supersedes_id = <new_version_id>` but keeps `deleted_at IS NULL`. The search query filters `deleted_at IS NULL` but not `supersedes_id IS NULL`, so it returns superseded versions.

The FTSSearch repository method at `repository.go:1416` correctly filters BOTH:
```go
"supersedes_id IS NULL", // line 1427 - HEAD versions only
// and deleted_at IS NULL from buildSearchFilters (line 1346)
```

### Fix

Add `AND go.supersedes_id IS NULL` to the WHERE clause in `executeSearchEntities()` at line 2918:
```go
WHERE go.deleted_at IS NULL
    AND go.supersedes_id IS NULL  // HEAD versions only
```

---

## Test Results Summary

| Step | Status | Details |
|------|--------|---------|
| 1: Operations | BESTÅTT | All tools available and functional |
| 2: Create claim | BESTÅTT | Proposal → execute → get_ko works |
| 3: Warrant (no evidence) | BESTÅTT (merknad) | `conditionally_warranted` with 0 evidence — should be `unwarranted` |
| 4: Partial evidence | BESTÅTT | Evidence stored in `evidence_ids`, not traversable by warrant |
| 5: Counter-evidence | BLOKKERT + FEILET | No `contradicts` mechanism in submission path |
| 6: Cleanup | BESTÅTT | Objects deleted, verified with `key_prefix` query |
| Search after delete | FEILET | `entity-search` returns soft-deleted versions |

## Warrant Results Comparison

| Phase | Status | Evidence Count | Independent Roots |
|-------|--------|---------------|-------------------|
| No evidence | `conditionally_warranted` | 0 | 0 |
| Partial evidence (2/3) | `conditionally_warranted` | 0 | 0 |
| Counter-evidence (1/3 > threshold) | `conditionally_warranted` | 0 | 0 |

Warrant is static — it does not reflect the state of registered evidence. This is because warrant traverses graph edges, not `evidence_ids`.
