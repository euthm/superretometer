# Storage Backend Contract (v0.6.3)

This document defines the requirements for any `StorageInterface` implementation.
The canonical contract is `cognitive_harness.storage.interface.StorageInterface`.

## Purpose

The storage layer is the ONLY persistence dependency of the Cognitive Harness.
All analysis, reasoning, and orchestration logic depends exclusively on the
public `StorageInterface` methods. No caller may access internal storage
attributes (`_kos`, `_objects`, private dicts).

## Required Backend Capabilities

### 1. Knowledge Object CRUD

| Operation | Method | Requirement |
|---|---|---|
| Create | `create_ko(ko) -> str` | Accepts a `KnowledgeObject`; returns its ID. Backend may assign ID if not set. |
| Read | `get_ko(ko_id) -> KnowledgeObject \| None` | Returns full KO or `None`. Must return the exact object, not a projection. |
| Update | `update_ko(ko_id, updates) -> bool` | Merges field-level updates. Returns `False` if KO missing or canonical (canonical KOs must be superseded). |

### 2. Full Enumeration — `list_all_kos()`

**Mandatory.** `list_all_kos() -> list[KnowledgeObject]` must return every KO
in the backend regardless of:
- epistemic status (active, superseded, invalidated, canonical)
- scope
- viewpoint
- type

Completeness is required. Paginated backends must page to completion before
returning. Partial results are unacceptable — `WarrantAnalyzer.detect_all_anti_patterns()`
operates on the full set.

Callers MUST NOT access `_kos` or any internal attribute to enumerate KOs.
`list_all_kos()` is the sole iteration mechanism.

### 3. Relation Semantics

Relations are directional, typed edges:

#### 3.1 Normative Direction Rule (v0.6.4)

Every relation type has a normative direction. The edge direction in storage
MUST match the semantic direction. Analysis MUST be direction-aware.

| Relation | Semantic Direction | Graph Edge |
|---|---|---|
| `SUPPORTS` | evidence → claim | `evidence -> SUPPORTS -> claim` |
| `VALIDATES` | validator → claim | `validator -> VALIDATES -> claim` |
| `DEPENDS_ON` | dependent → prerequisite | `dependent -> DEPENDS_ON -> prerequisite` |
| `DERIVED_FROM` | derived → source | `derived -> DERIVED_FROM -> source` |
| `FITTED_ON` | fitted_KO → dataset | `fitted_ko -> FITTED_ON -> dataset` |
| `TESTED_AGAINST` | tested_KO → dataset | `tested_ko -> TESTED_AGAINST -> dataset` |
| `TRANSFERRED_FROM` | transferred → source | `transferred -> TRANSFERRED_FROM -> source` |
| `CONTRADICTS` | contradictor → contradicted | `A -> CONTRADICTS -> B` |
| `CONSTRAINS` | constraint → target | `constraint -> CONSTRAINS -> target` |
| `IMPACTS` | source → target | `A -> IMPACTS -> B` |
| `REFINES` | refinement → original | `refinement -> REFINES -> original` |
| `SUPERSEDES` | successor → predecessor | `successor -> SUPERSEDES -> predecessor` |
| `EQUIVALENT_TO` | A ↔ B (symmetric) | `A -> EQUIVALENT_TO -> B` |

#### 3.2 Direction-Aware Traversal

Warrant analysis from a conclusion MUST traverse direction-aware:

- **INBOUND relations** (SUPPORTS, VALIDATES): evidence/support flows INTO the
  conclusion. Discovered by following INCOMING edges.
- **OUTBOUND relations** (DEPENDS_ON, DERIVED_FROM, etc.): conclusion points
  OUTWARD to prerequisites and sources. Discovered by following OUTGOING edges.

A single-direction traversal (only outgoing edges) cannot discover inbound
justification. The storage interface must support both directions.

#### 3.3 Impact Traversal

Impact analysis (downstream of a changed KO) must also be direction-aware:

- If a prerequisite/source changes, find KOs that `DEPENDS_ON` or `DERIVED_FROM` it.
- If evidence/support changes, find the claim it `SUPPORTS` or `VALIDATES`.
- If a constraint changes, find the KOs it `CONSTRAINS`.

Impact does NOT flow backward from conclusions to evidence — changing a
conclusion does not impact its evidence.

---

Relations are directional, typed edges:

```
from_id -> RelationType -> to_id
```

- `create_relation(from_id, to_id, rel_type) -> bool` creates a directed edge
  from `from_id` to `to_id` with the given `RelationType`.
- Relations are first-class: each has a unique ID.
- `get_ko(ko_id).relations` returns the outgoing relations for that KO.
- Incoming relations must be discoverable (via edge query, reverse index, or
  full graph traversal).
- The identity of a relation is the triple `(from_id, RelationType, to_id)`.
  No legacy `source_id` WIP semantics.

**Graph traversal:** `compute_impact_set(ko_id)`, `get_justification_path(ko_id)`,
and `list_all_kos()` + relation traversal must support BFS/DFS over the
justification graph. The backend does not need to implement traversal algorithms —
those are in the analysis layer. The backend must provide the edges.

### 4. Query Operations

| Method | Requirement |
|---|---|
| `query_semantic(query, viewpoint_id, limit)` | Text/semantic search. Returns matching KOs. |
| `query_by_viewpoint(viewpoint_id)` | KOs containing the given viewpoint. |
| `query_by_type(ko_type)` | KOs of the given type. |
| `query_active_by_scope(scope)` | Non-terminal KOs within scope. |
| `list_canonical(scope)` | KOs with `EpistemicStatus.CANONICAL`, optionally filtered by scope. |

These query methods are convenience operations. A backend that implements
`list_all_kos()` + `get_ko()` can satisfy them by filtering. Partial
implementations that return incomplete results for `list_canonical()` or
`query_by_type()` will produce silent analysis errors.

### 5. Succession and Impact

| Method | Requirement |
|---|---|
| `get_succession_chain(ko_id)` | Returns `[oldest, ..., current]` following `supersedes_id` / `superseded_by_id` links. |
| `compute_impact_set(ko_id)` | BFS over incoming edges with relation types in `IMPACT_RELATIONS`. Returns affected KO IDs. |
| `mark_review_required(ko_ids, reason)` | Marks KOs for reassessment. Does not change epistemic status. |
| `list_review_required()` | Returns all KOs marked review-required. |

### 6. Evidence

| Method | Requirement |
|---|---|
| `add_evidence(evidence_id, claim_id, status, observation, records)` | Associates evidence with a claim KO. |
| `get_evidence(evidence_id)` | Returns evidence dict or `None`. |
| `list_evidence_for_ko(ko_id)` | Returns all evidence for a claim. |

Evidence is opaque from the analysis layer's perspective. The `WarrantAnalyzer`
checks evidence IDs but does not interpret evidence content.

### 7. Proposals (Consumer Pipeline)

| Method | Requirement |
|---|---|
| `submit_proposal(proposal) -> str` | Accepts a structured proposal. Returns proposal ID. |
| `validate_and_execute(proposal_id) -> Proposal` | Deterministic validation. Sets `ProposalState.ACCEPTED` or `REJECTED`. |

The proposal pipeline is the ONLY mutation path for external consumers.
Internal components (orchestration, reasoner) may use `create_ko` directly.

### 8. Datasets

| Method | Requirement |
|---|---|
| `create_dataset(dataset) -> str` | Registers a Dataset object. |
| `get_dataset(dataset_id)` | Returns Dataset or `None`. |

Datasets are used by `WarrantAnalyzer` for independence analysis (training/test
dataset provenance tracing).

### 9. Locking

| Method | Requirement |
|---|---|
| `lock_ko(ko_id, thread_id) -> bool` | Advisory lock. Returns `False` if already locked. |
| `unlock_ko(ko_id, thread_id) -> bool` | Releases lock held by `thread_id`. |

Locking is advisory. Backends without distributed locking may return `True`
for lock/unlock (no-op). The orchestration engine uses locks for thread
coordination, not for data integrity.

## What Adapters Must NOT Implement

The following are ANALYSIS semantics, not storage:

- **Warrant computation** — `compute_warrant()` is in `WarrantAnalyzer`, not storage.
  Storage method `list_by_warrant_status()` returns KOs tagged by external analysis;
  warrant itself is never stored authoritatively.
- **Anti-pattern detection** — `detect_all_anti_patterns()` is in `WarrantAnalyzer`.
  Storage method `list_anti_pattern_hits()` returns cached results; detection is analysis.
- **Simulation gates** — `SimulationGatePolicy` is read-only analysis.
- **Reasoning** — `ReasonerInterface` is separate from storage.
- **Orchestration** — proposal validation rules are in `OrchestrationEngine`.
- **Consumer presentation** — `_present_ko()` is in `ConsumerAPI`.

Adapters that embed warrant logic, anti-pattern detection, or gate evaluation
create private semantic forks. This is a design violation.

## Handling Unsupported Capabilities

If a backend cannot implement a method (e.g., no native evidence storage, no
distributed locking):

1. **Do not silently return empty results** for methods that affect analysis correctness
   (`list_all_kos`, `get_ko`, `create_relation`, `get_justification_path`).
2. **Raise `NotImplementedError`** with a message naming the missing capability.
3. **Model missing concepts as objects** — evidence can be a `KnowledgeObject` with
   type `EVIDENCE` and a `SUPPORTS` relation to the claim.
4. **No-op locking** is acceptable — return `True` for lock/unlock.

## Backend Independence Conformance

A conformant backend passes `tests/conformance/test_storage_independence.py`:

- No `_kos` attribute (or any equivalent private attribute) is accessible
- `list_all_kos()` returns all objects
- `WarrantAnalyzer` operates correctly without internal state access
- Full anti-pattern detection works on the backend

The `NoKosStorage` test class in the conformance suite deliberately raises
`AttributeError` on `_kos` access. Any code path that touches `_kos` fails.

## Pagination and Completeness

Backends with pagination (remote APIs, databases):

- `list_all_kos()` must return ALL objects. Paginate to completion.
- `query_semantic()` may return a limited set (bounded by `limit` parameter).
- `compute_impact_set()` must be complete — partial BFS produces silent analysis errors.
- `get_justification_path()` must be complete — partial paths produce wrong warrant.

A backend that returns a truncated `list_all_kos()` is non-conformant.

## Graph Enumeration Completeness (v0.6.4)

### The Problem

`list_all_kos()` is used by `WarrantAnalyzer.detect_all_anti_patterns()` and other
graph-level analyses. The question is: can the backend GUARANTEE that every KO in the
selected scope is returned?

### InMemoryStorage

Complete. `_kos.values()` returns every object. No pagination, no search, no tombstones.
**Guarantee: complete.**

### Memory Backend (external graph)

Two API surfaces exist:

**MCP Tools (provably complete):**
- `memory_entity-type-list()` — lists all registered entity types
- `memory_entity-query(type_name, limit=200, offset=N)` — paginated by type
- Pattern: type-list → per-type paginated entity-query → deduplicate → complete

**HTTP REST API (NOT provably complete):**
- `/api/graph/search` with `"*"` query — search-based, not guaranteed complete
- `/api/graph/objects/count` — returns total count for verification
- `/api/graph/journal` — event log, may miss objects created outside adapter
- No type-list endpoint exists in HTTP API

**Completeness assessment:**
- MCP approach (type-list + paginated query) is **provably complete**
- HTTP search approach is **NOT provably complete** — search may miss entities
- The current MemoryAdapter uses the HTTP API and supplements with `_created_ids` registry
- For full completeness, the adapter must be extended to call MCP tools or the
  HTTP API must be extended with type-list + paginated query endpoints

**Warning:** Soft-deleted (tombstoned) entities are excluded from enumeration by default.
Superseded KOs must be explicitly included if analysis requires them.

### Fail-Closed Behavior

Operations that require FULL graph completeness:
- `detect_all_anti_patterns()` — must see every KO
- `compute_impact_set()` — must see every KO for BFS
- Global cycle detection

Operations that can operate on partial/local retrieval:
- `compute_warrant(ko_id)` — traverses from a specific KO
- `evaluate_gates(ko_id)` — local to one claim
- `get_justification_path(ko_id)` — local traversal

If a backend cannot guarantee complete enumeration, it MUST either:
1. Raise `NotImplementedError` on `list_all_kos()`, or
2. Return a completeness flag that the analysis layer can check before proceeding.
