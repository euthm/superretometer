# Epistemic Warrant

## Normative Definition

Warrant is derived state, not authoritative stored truth. A conclusion's warrant MUST be recomputable from current graph structure, provenance, and policy.

## Warrant Statuses

| Status | Meaning |
|---|---|
| `WARRANTED` | All supporting premises are independently grounded. No structural defects. |
| `CONDITIONALLY_WARRANTED` | Warrant holds if certain assumptions are accepted. Premises share provenance roots or depend on unresolved assumptions. |
| `UNWARRANTED` | Structural defects found: circular dependency, calibrated-to-conclusion, tautological validation, physically unrealizable, unsupported transfer. |
| `UNRESOLVED` | Conclusion cannot be found, or graph structure is insufficient to determine warrant. |

## What Determines Warrant

Warrant is determined by:

- Graph topology (justification paths, cycles)
- Provenance independence (distinct root sets)
- Derivation types (FITTED, TRANSFERRED, VALIDATED, MATHEMATICAL)
- Dataset lineage (self-referential training)
- Domain mapping completeness

Warrant is NOT determined by:

- Prose content or labels
- Confidence scores
- KO type or epistemic status
- Keyword heuristics
- Canonical status

## Structural Anti-Patterns

| Pattern | Structural Condition |
|---|---|
| `CALIBRATED_TO_CONCLUSION` | FITTED derivation with self-referential training dataset and no independent test set |
| `TAUTOLOGICAL_VALIDATION` | VALIDATED derivation where all upstream KOs share a single provenance root |
| `INERT_PARAMETER` | Parameter in KO content but not in causal/state equations (requires causal graph) |
| `PHYSICALLY_UNREALIZABLE` | KO contradicts a CONSERVATION_LAW-type constraint |
| `UNSUPPORTED_TRANSFER` | TRANSFERRED derivation with empty `domain_mapping_ko_id` |
| `CIRCULAR_DEPENDENCY` | Cycle detected in justification graph traversal |

## Falsifiability Principle

> A check that cannot fail is not evidence.

Validators used as evidence SHOULD declare `what_would_falsify` — the observation that would invalidate them.

### Invariant Validity for System Boundary (v0.6 — N-INVARIANT)

> An invariant must be valid for the declared system boundary, not merely mathematically computable.

An invariant that is computable but physically invalid for the system boundary gives no epistemic credit. A maskinkjørbar invariant for the wrong boundary does not increase warrant.

- `C_in = C_out` is NOT valid for a recycle loop with reactions at the boundary
- Energy balance across a control volume with heat generation requires the generation term
- An internal reaction balance may be correct for a subsection but not the full plant

## SimulationGatePolicy — Normative Rules (v0.6)

SimulationGatePolicy is a cross-cutting warrant dimension for simulation-bearing claims. It operates alongside the existing warrant analysis.

### The Four Gates

```
PROVENANCE  →  SCOPE  →  REALITY  →  FALSIFIABILITY  →  DESIGN-BEARING
```

Each gate evaluates independently. Status: PASS, BLOCK, or UNKNOWN. BLOCK is an epistemic judgment about the warrant chain, NOT a simulation execution failure.

**Gate 1 — Provenance (N-PROV):** A result file without reproducible source provenance cannot carry a design conclusion. The chain claim → result artifact → SHA256 → run → parameters → model → source commit must be complete and traceable. Orphaned results are informative only.

**Gate 2 — Scope (N-SCOPE):** A simulation result may only warrant claims within the explicitly declared physical scope. Scope is a warrant boundary, not metadata. A component model cannot support a system-level claim.

**Gate 3 — Reality (N-REALITY):** Quantities carrying the claim must have independent grounding. Delegates to `WarrantAnalyzer`. WARRANTED → PASS, UNWARRANTED → BLOCK, CONDITIONALLY_WARRANTED → PASS with conditions.

**Gate 4 — Falsifiability (N-INVARIANT):** Validators must declare what would falsify them. Invariants must be valid for the declared system boundary, not just computable.

### Design-Bearing Semantics

| Condition | Verdict |
|-----------|---------|
| All four gates PASS | **Design-bearing allowed** |
| At least one gate BLOCK | **Informative only** |
| Any gate UNKNOWN | **Insufficiently established** |

Warrant status is recomputed from graph + policy, not stored (N-RECOMPUTE).

### Frozen Baseline (N-BASELINE-IMMUTABLE)

Immutable snapshot: baseline_id, version, model_id, source_commit, parameter_set_id, run_command, result_artifact, result_sha256, gate_report, allowed_claims, timestamp. Cannot be mutated. Material change produces new version.
