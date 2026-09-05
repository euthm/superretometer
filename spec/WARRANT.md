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
