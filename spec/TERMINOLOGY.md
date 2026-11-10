# Terminology

## Core Concepts

**Knowledge Object (KO)**: The atomic unit of structured knowledge. Contains a stable logical ID, content, type, truth category, epistemic status, confidence, provenance, and relations.

**Truth Category**: What kind of truth claim the KO makes (physical observation, conservation law, fitted parameter, model-derived, assumption, etc.)

**Epistemic Status**: The lifecycle state of the KO (proposed, tentative, validated, canonical, superseded).

**Confidence Level**: Speculative, low, medium, high, certain. Separate from warrant.

**Provenance**: Where the knowledge came from. Source, author, revision, independence flag, upstream derivation.

**Reproducible Provenance** (v0.6): A complete, traceable chain from result artifact through run, parameters, model, to source commit. Allows the result to be regenerated. A result without reproducible provenance cannot carry a design conclusion (N-PROV).

**Derivation**: How a KO was produced from upstream KOs or datasets. Types: FITTED, TRANSFERRED, VALIDATED, MATHEMATICAL.

**Relation**: Typed edge between KOs. SUPPORTS, DEPENDS_ON, SUPERSEDES, DERIVED_FROM, CONTRADICTS, etc.

**Dataset**: Collection of observations used to train or validate a derivation. Tracks source KO and lineage.

**Calibrated to Conclusion**: A fitted parameter's training or test lineage reaches
the conclusion it is meant to support, or the training and test observations share
provenance roots. A separate holdout does not repair conclusion-derived training.

**Missing Independent Validation**: A fitted parameter has no registered, traceable
test/training split. Missing datasets, unresolved lineage references, empty lineage
and source labels containing only whitespace do not establish independent roots.
This blocks design-bearing warrant without asserting conclusion-derived calibration.

**Warrant**: Derived analysis of whether a conclusion is structurally supported by independent evidence. Not stored — computed.

**Thread of Reasoning**: Ordered investigation through viewpoints, inspired by Müller's CAFCR framework.

**Tension**: Identified conflict between KOs that requires investigation.

**Supersession**: A KO is replaced by a successor. The old KO is marked SUPERSEDED but remains in the graph. History is never deleted.

**Impact Set**: KOs affected by a change, computed by traversing incoming DEPENDS_ON and SUPPORTS edges.

## SimulationGatePolicy Concepts (v0.6)

**SimulationGatePolicy**: Four-gate evaluation (Provenance, Scope, Reality, Falsifiability) for simulation-bearing claims. All four gates must PASS for a claim to be design-bearing.

**Design-bearing Claim**: A simulation-backed claim that has passed all four gates and may support architectural, design, or procurement decisions.

**Informative Result**: A simulation result valid for analysis but blocked from carrying a design conclusion by at least one gate. NOT equivalent to "simulation failed."

**Scope** (normative): The explicitly declared physical domain, extent, components, and boundaries of a model. Acts as a warrant boundary, not metadata. A simulation result may only warrant claims within the explicitly declared scope (N-SCOPE).

**System Boundary**: The defined edge of the modeled system. Determines which invariants are valid for falsifiability evaluation.

**Frozen Baseline**: An immutable snapshot of a simulation study: model, source commit, parameters, run command, result artifact with SHA256, gate report, allowed claims, timestamp. Cannot be silently mutated (N-BASELINE-IMMUTABLE).

**Gate PASS**: The gate's condition is satisfied for this dimension.

**Gate BLOCK**: The gate's condition is not met. The result may be informative but not design-bearing. Distinct from execution failure.

**Gate UNKNOWN**: Insufficient information to evaluate. Treated conservatively as BLOCK for design-bearing purposes.

## Gate Status Canonical Definition

Gate status is dimension-specific: PASS means the gate condition is satisfied; UNKNOWN means required information is unavailable; BLOCK means a condition is violated. Implementation-gate PASS establishes the stated metadata/source check, not independent epistemic grounding (N-IMPL-SELFCONSISTENCY). All required gates must PASS for design_bearing; warrant is computed separately.

## ImplementationGatePolicy Concepts (v0.7)

**ImplementationGatePolicy**: Seven-gate evaluation (Provenance, Scope, Worktree, Test, Falsifiability, Dependency, Freshness) for implementation-bearing claims. All seven gates must PASS for a claim to be design-bearing.

**ImplementationProvenance**: Structured metadata for code implementation claims. Tracks `repo_remote`, `repo_path`, `branch`, `commit`, `submodule_pins`, `test_run_id`, `test_result_sha256`. Parallel to `SimulationProvenance` but oriented to repository→commit→test rather than model→run→result.

**N-IMPL-PROV**: Normative rule — an "implemented" claim must trace to a specific commit of a named repository; branch is optional context. Orphaned claims are informative only.

**N-IMPL-SCOPE**: Normative rule — the provenance's `repo_remote` must match a scope-declared remote. Remote mismatch = BLOCK.

**N-IMPL-TEST**: Normative rule — a test run must exist with a passing result. Missing required test/validator evidence = UNKNOWN; a known failed exit or commit mismatch = BLOCK (see WARRANT.md).

**N-IMPL-REMOTE**: Remote Mismatch Rule — an implementation claim is blocked if its provenance remote does not match any scope-declared remote. Normalization applies: `git@` and `https://` forms are equivalent.

**Remote Mismatch**: The condition where an implementation claim's provenance references a repository remote that is not among the scope-declared authorized remotes. Results in a SCOPE gate BLOCK.

**UNgrounded Claim**: A claim that declares falsifiability but has no passing validator. Displayed as UNGROUNDED in AIM reports. Distinct from BLOCK — unfalsified, not necessarily false.

**TestRunReceipt**: Immutable runner-reported execution/code/artifact record, identified by canonical-byte SHA-256; not independent certification. See TEST_EVIDENCE.md.

**Evaluation snapshot**: Append-only gate/warrant result bound to a receipt, scoped graph inputs and exact policy source identity. Distinct from an execution retry.

**Portable evidence bundle**: Complete, path-safe, checksummed directory of one receipt and selected historical evaluations, verifiable without a Memory session.
