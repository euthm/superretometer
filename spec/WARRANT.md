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

**Gate 3 — Reality (N-REALITY):** Quantities carrying the claim must have independent grounding. Delegates to `WarrantAnalyzer`. WARRANTED → PASS, UNWARRANTED → BLOCK, CONDITIONALLY_WARRANTED → UNKNOWN (explicitly assumed but not independently grounded).

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

## ImplementationGatePolicy — Normative Rules (v0.7)

ImplementationGatePolicy is a cross-cutting warrant dimension for implementation-bearing claims. It operates alongside SimulationGatePolicy and covers code, configuration, and deployment claims.

### The Four Gates

```
PROVENANCE  →  SCOPE  →  WORKTREE  →  TEST  →  DESIGN-BEARING
```

Each gate evaluates independently. Status: PASS, BLOCK, or UNKNOWN.

### Repository Identity

**Repository revision identity** is the composite of canonical repository identity and commit SHA:

```
repo_remote_canonical + commit
```

- **repo_remote_sanitized**: observed transport locator with credentials/tokens removed. Preserves transport form for audit. Never stores credential-bearing URLs. If audit of exact raw input is required, use `repo_remote_raw_sha256` (hash only).
- **repo_remote_canonical**: normalized repository identity. Transport syntax removed, lowercase hostname, trailing `.git` removed. Used for all gate comparisons.
- **commit**: Git commit hash. The revision anchor.
- **branch**: contextual metadata only. Not part of revision identity. Detached HEAD with canonical remote + exact commit is eligible for valid provenance. Changing branch name while commit remains unchanged does not invalidate provenance.

Canonicalization normalizes transport syntax, not repository identity:

| Raw Remote | Canonical |
|---|---|
| `git@github.com:euthm/foo.git` | `github.com/euthm/foo` |
| `https://github.com/euthm/foo.git` | `github.com/euthm/foo` |
| `ssh://git@github.com/euthm/foo.git` | `github.com/euthm/foo` |

### Worktree State

**Code-state reproducibility** requires that the tested code exactly matches the claimed code state.

- **worktree_clean = true**: the commit alone represents the tested state. Eligible for PASS.
- **worktree_clean = false + worktree_diff_sha256 present**: dirty state is reproducibly identified but cannot PASS (UNKNOWN).
- **worktree_clean = false + no diff hash**: tested state not reproducibly identified (BLOCK).
- **worktree_clean = null/absent**: unobserved (UNKNOWN).

**worktree_diff_sha256** normatively hashes a deterministic representation of all implementation-bearing deviations from HEAD: staged changes, unstaged changes, and untracked files. The hash must be reproducible from the same diff output.

### Test Evidence Binding

Test identity is separated into three distinct concepts:

- **test_run_id**: external runner/execution identity (e.g., GitHub Actions run ID). Not a CH graph reference.
- **validator_ko_id**: CH KnowledgeObject containing validation evidence. The only graph reference.
- **test_result_sha256**: immutable hash of test output/report artifact.

Test execution provenance requires:

- **test_command**: exact command that was executed
- **test_exit_code**: exit code (0 = success, required for PASS)
- **tested_commit**: commit against which tests ran (must equal claim.commit)
- **tested_worktree_diff_sha256**: worktree diff SHA at test time (must equal claim.worktree_diff_sha256 when dirty)
- **test_timestamp**: ISO 8601 execution time

**Invariant**: `claim.commit == tested_commit`. Mismatch → BLOCK.

When worktree is dirty: `claim.worktree_diff_sha256 == tested_worktree_diff_sha256`. Mismatch → BLOCK.

**Gate 1 — Provenance (N-IMPL-PROV):** An "implemented" claim must trace to a specific commit on a canonical repository. The chain claim → commit → canonical remote must be complete. Branch is contextual metadata.

**Gate 2 — Scope (N-IMPL-SCOPE):** The provenance's `repo_remote_canonical` MUST match a scope-declared remote. Scope comparison uses canonical identity only; raw transport URLs are never compared directly. Remote mismatch = BLOCK.

**Gate 3 — Worktree (N-IMPL-WORKTREE):** Code state must be reproducibly identified. Clean commit → PASS. Dirty with diff hash → UNKNOWN. Dirty without diff → BLOCK. Unobserved → UNKNOWN.

**Gate 4 — Test (N-IMPL-TEST):** Complete test evidence chain is required. The gate checks:
1. Evidence presence: validator_ko_id, test_run_id, test_command, test_result_sha256 must all be present (missing → UNKNOWN)
2. Validator resolution: validator_ko_id must resolve to a KO in the graph (missing → UNKNOWN)
3. Commit invariant: tested_commit must equal claim.commit (mismatch → BLOCK)
4. Worktree invariant: when dirty, tested_worktree_diff must equal claim diff (mismatch → BLOCK)
5. Exit code: must be 0 (non-zero → BLOCK, absent → UNKNOWN)
6. Timestamp: must be valid ISO 8601 (missing → UNKNOWN, invalid → BLOCK)

**Gate 5 — Falsifiability (N-IMPL-FALSIFY):** At least one FalsifiableValidator on the claim must have a non-empty `what_would_falsify`. This uses the existing `KnowledgeObject.validators` list — no duplication into ImplementationProvenance. Missing or empty falsifiers → UNKNOWN (UNGROUNDED). Present → PASS.

**Gate 6 — Dependency (N-IMPL-DEPENDENCY):** Submodule/dependency state must be consistent between claim and tested state. Each submodule pin carries `repo_remote_sanitized`, `repo_remote_canonical`, and `commit`. The claim's `submodule_pins` must match `tested_submodule_pins` in set, canonical remote, and commit. Mismatch → BLOCK. Missing tested evidence → UNKNOWN. No submodules → PASS.

### Design-Bearing Semantics

| Condition | Verdict |
|-----------|---------|
| All six gates PASS | **Design-bearing allowed** |
| At least one gate BLOCK | **Informative only** |
| Any gate UNKNOWN | **Insufficiently established** |

### Test Timestamp

`test_timestamp` is provenance/audit metadata. Required for complete validation provenance. Must be valid ISO 8601. Not compared against Git commit timestamps (unreliable for causal ordering). Missing → UNKNOWN. Invalid format → BLOCK. No freshness/expiry semantics in v0.7.

### Remote Mismatch Rule (N-IMPL-REMOTE)

> An implementation claim is blocked if its provenance canonical remote does not match any scope-declared canonical remote.

Comparison uses canonical identity only. `git@github.com:owner/repo.git` and `https://github.com/owner/repo.git` are identical. A claim about code on an unauthorized or misidentified repository → **BLOCK**.

### UNGROUNDED Claims

A claim that declares `what_would_falsify` validators but has no passing validator attached is displayed as **UNGROUNDED** in AIM reports. This is distinct from BLOCK — it means the claim is unfalsified, not necessarily false.
