# Architecture

## Conceptual Stack

```
Identity
    ↓
Semantics (KOType, TruthCategory, EpistemicStatus, ConfidenceLevel)
    ↓
Provenance (source, author, independence, derivation, datasets)
    ↓
Simulation Provenance (v0.6 — reproducible chain: result → SHA256 → run → params → model → commit)
    ↓
Epistemic Warrant (derived — computed from graph structure)
    ↓
SimulationGatePolicy (v0.6 — four gates: Provenance → Scope → Reality → Falsifiability → Design-bearing)
    ↓
Scope as Warrant Boundary (v0.6 — explicit physical scope declaration)
    ↓
Lines / Threads of Reasoning (CAFCR viewpoint traversal)
    ↓
Impact + Reassessment (supersession, review-required)
    ↓
Frozen Baseline (v0.6 — immutable snapshot with gate report)
    ↓
External planner / agent / human action
```

## Layer Separation

### Model Layer (`cognitive_harness.model`)
Pure data structures. No behavior. Defines KO, Relation, Derivation, Dataset, Thread, Tension, Proposal.

### Storage Layer (`cognitive_harness.storage`)
`StorageInterface` — abstract interface for persistence. Implementations: `InMemoryStorage` (reference), external adapters (not included in v0.1).

### Analysis Layer (`cognitive_harness.analysis`)
`WarrantAnalyzer` — computes warrant from graph structure. Read-only.
`SimulationGatePolicy` (v0.6) — four-gate evaluation for simulation-bearing claims. Read-only. Returns `SimulationGateReport`.

### Reasoning Layer (`cognitive_harness.reasoning`)
`ReasonerInterface` — abstract. `RuleEngineReasoner` — rule-based thread progression.

### Orchestration Layer (`cognitive_harness.orchestration`)
`OrchestrationEngine` — proposal validation and execution. Enforces status transitions and canonical protection.

### Consumer Layer (`cognitive_harness.consumer`)
`ConsumerAPI` — the ONLY interface for external agents. Read queries + proposal submission. Never direct mutation.

### Transport Layer (`transports/`)
MCP server — stdio-based JSON-RPC. First supported interoperability transport.

## Design Principles

1. **Warrant is derived** — never stored as authoritative state
2. **Proposals, not mutations** — agents submit structured proposals; orchestration validates
3. **History is preserved** — supersession marks old KOs as SUPERSEDED; nothing is deleted
4. **Independence is structural** — determined by provenance root sets, not labels or confidence
5. **Scope is normative** — explicitly declared physical scope acts as a warrant boundary (v0.6)
6. **Simulation gates are recomputable** — warrant status derived from graph + policy, not cached (v0.6)
