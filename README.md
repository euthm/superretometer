# Superretometer

**Reference implementation of the Cognitive Harness specification — structural reasoning and epistemic warrant for autonomous engineering agents.**

## Latest Release

**v0.6.4** — Direction-aware traversal + enumeration completeness (fail-closed).
[Release notes](docs/releases/v0.6.4.md) · [Changelog](CHANGELOG.md)

**v0.6.5** — Packaged MCP server, CLI, and distribution. [Changelog](CHANGELOG.md)

An AI agent can produce plausible answers, run tests, and retain large amounts of
memory. That does not mean its conclusions follow from the evidence.

The Cognitive Harness specification answers the harder question:

> **What justifies this conclusion — and what would have to change if its
> justification fails?**

It represents knowledge, provenance, evidence, assumptions, decisions, and
reasoning as an explicit graph, then evaluates whether conclusions are
independently warranted.

Superretometer is the reference implementation: written in Python, zero required
dependencies, LLM-independent. The specification is in `spec/`.

## Why use it

Consider an engineering simulation that predicts a machine reaches its required
operating point.

The simulation converges. The numbers look reasonable. The energy balance closes.
Multiple checks pass.

It can still return:

**UNWARRANTED**

because, for example:

- A critical parameter was calibrated to produce the desired result.
- A validation check was an identity and therefore could not fail.
- A load characteristic was transferred from another application without evidence
  that the transfer was valid.

The problem is not necessarily that the numerical result is wrong. The problem is
that **the conclusion does not yet follow independently from the evidence.**

It identifies the missing evidence required to change that.

## A check that cannot fail is not evidence

This is a core design principle. A validator that merely reproduces an identity,
a model output used to validate itself, or three apparently independent tests
that all descend from the same measurement do not constitute independent evidence.

Superretometer reasons over the structure of provenance rather than trusting
confidence scores or textual claims.

Consider this provenance topology:

```
Evidence A ─┐
Evidence B ─┼── derived from ── Simulation X
Evidence C ─┘
```

This is epistemically different from:

```
Measurement A ── independent root A
Measurement B ── independent root B
Measurement C ── independent root C
```

even when the textual content of A, B, and C is identical. Identical claims
carried by dependent provenance have less epistemic force than identical claims
carried by independent provenance.

The public conformance suite explicitly tests this distinction.

## Conceptual model

Agent interoperability has several distinct layers:

| Layer | Question |
|---|---|
| **Identity** | Are we talking about the same thing? |
| **Semantics** | Do we mean the same thing? |
| **Provenance** | Where did this knowledge come from? |
| **Warrant** | Are we justified in drawing this conclusion? |
| **Reasoning** | What follows from what we know? |
| **Impact** | What must be reconsidered when knowledge changes? |
| **Action** | What should be done next? |

The Cognitive Harness specification focuses on the middle of this stack:

**provenance → warrant → reasoning → impact**

It can feed an external planner, agent runtime, or human review process. It does
not require one.

## What it does

- **Stable logical identity** independent of storage backends
- **Typed knowledge objects** and semantic relations
- **Explicit provenance and derivation graphs**
- **Dataset lineage** and evidence-independence analysis
- **Structural epistemic warrant** derived from graph structure
- **Threads of Reasoning** with viewpoint traversal
- **Tensions and competing conclusions**
- **Supersession without destroying history**
- **Transitive impact analysis**
- **Evidence-gap identification**
- **Reassessment when upstream knowledge changes**

Warrant is **derived state**. It is recomputed from the current graph structure
rather than stored as permanent truth.

## Structural warrant

The reference implementation can identify structural defects in reasoning:

- **`CALIBRATED_TO_CONCLUSION`** — a parameter fitted to produce the desired
  outcome, without independent test data
- **`TAUTOLOGICAL_VALIDATION`** — a check that cannot fail because all quantities
  derive from the same source
- **`CIRCULAR_DEPENDENCY`** — knowledge objects that justify each other
- **`INERT_PARAMETER`** — a parameter that does not affect any observable
- **`PHYSICALLY_UNREALIZABLE`** — a knowledge object that contradicts a
  constraint in the graph
- **`UNSUPPORTED_TRANSFER`** — data transferred between domains without a
  validated domain mapping

These are structural diagnoses derived from graph topology and provenance.
They are not keyword classifiers.

## Threads of Reasoning

A Thread of Reasoning is a structured trace of how a conclusion was reached:

1. A question is asked.
2. Viewpoints are traversed (conceptual → functional → realization → application).
3. Each step records the claim, the viewpoint, and the knowledge objects used.
4. The thread reaches a conclusion or exposes a gap.

Threads make reasoning auditable and restartable. Multiple threads can pursue
competing hypotheses about the same tension.

## Change impact and supersession

When a knowledge object is superseded by a revised version:

- The old object is marked `SUPERSEDED`, not deleted.
- The succession chain is preserved: v1 → v2 → v3.
- Downstream dependents are marked `REVIEW_REQUIRED`.
- Impact propagates transitively through the dependency graph.
- CANONICAL objects cannot be superseded (they require explicit revocation).

## Quick start

```bash
pip install cognitive-harness
```

Zero dependencies. MCP server and CLI are included in the base package.

```bash
superretometer --version
superretometer mcp
```

**Naming note:** The Python package is `cognitive-harness` (import as `cognitive_harness`).
The project and repository are branded **Superretometer**. Cognitive Harness is the
specification name.

## Minimal executable example

```python
from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus,
    ConfidenceLevel, RelationType, Provenance, Relation,
)
from cognitive_harness.storage.inmemory import InMemoryStorage
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer

storage = InMemoryStorage()

# Independent evidence
storage.create_ko(KnowledgeObject(
    id="ev-steel-strength",
    type=KOType.OBSERVATION,
    title="Lamination steel yield stress: 450 MPa",
    content="Measured from manufacturer datasheet, independent source.",
    truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
    epistemic_status=EpistemicStatus.CANONICAL,
    confidence=ConfidenceLevel.HIGH,
    provenance=Provenance(
        source="manufacturer-datasheet",
        author="materials-lab",
        independent=True,
    ),
    relations=[Relation(to="conc-safe-stress", type=RelationType.SUPPORTS)],
))

# Conclusion
storage.create_ko(KnowledgeObject(
    id="conc-safe-stress",
    type=KOType.CONCLUSION,
    title="Core stress is within material limits",
    content="Maximum calculated stress (320 MPa) below yield (450 MPa).",
    truth_category=TruthCategory.MODEL_DERIVED,
    epistemic_status=EpistemicStatus.PROPOSED,
    confidence=ConfidenceLevel.MEDIUM,
    provenance=Provenance(source="calculation", author="design-team"),
))

# Warrant analysis
wa = WarrantAnalyzer(storage)
result = wa.compute_warrant("conc-safe-stress")
print(f"Warrant: {result.warrant_status.value}")
# → Warrant: warranted
```

See `examples/minimal/run.py` for the complete executable file.

## Architecture

```
┌──────────────────────────────────────────────┐
│  Consumer (reads knowledge, proposes changes)│
├──────────────────────────────────────────────┤
│  Orchestration — tension routing, proposals   │
├──────────────────────────────────────────────┤
│  Reasoning — rule engine, derivation          │
├──────────────────────────────────────────────┤
│  Analysis — warrant, anti-patterns, impact    │
├──────────────────────────────────────────────┤
│  Model — knowledge objects, relations,        │
│           threads, tensions, proposals        │
├──────────────────────────────────────────────┤
│  Storage — InMemory (default) or custom       │
├──────────────────────────────────────────────┤
│  Transport — MCP (optional)                   │
└──────────────────────────────────────────────┘
```

Storage is an implementation dependency. The specification and reasoning layers
do not assume a particular backend.

## MCP integration

The MCP server is included in the base package. Run it with:

```bash
superretometer mcp
```

Or programmatically:

```python
from cognitive_harness.mcp.server import MCPServer
MCPServer().run()
```

Available tools: `orientation`, `check_warrant`, `justification_path`,
`scan_anti_patterns`, `open_tensions`, `review_required`, `impact_set`,
`propose_ko`, `propose_relation`, `propose_evidence`, `propose_tension`,
`propose_thread` (NotImplementedError — use OrchestrationEngine directly).

## Specification documents

- [`spec/IDENTITY.md`](spec/IDENTITY.md) — logical identity contract
- [`spec/WARRANT.md`](spec/WARRANT.md) — warrant semantics and computation
- [`spec/ARCHITECTURE.md`](spec/ARCHITECTURE.md) — layering and boundaries
- [`spec/TERMINOLOGY.md`](spec/TERMINOLOGY.md) — glossary
- [`spec/REASONING.md`](spec/REASONING.md) — rule engine and derivation
- [`spec/OPENSPEC.md`](spec/OPENSPEC.md) — complete specification
- [`spec/schemas/`](spec/schemas/) — JSON schemas for all model types

## Conformance suite

Two test suites validate the public specification:

- **Adversarial** (13 tests) — each structural anti-pattern tested against
  carefully constructed graph configurations designed to produce false
  positives and false negatives.
- **Conformance** (14 tests) — identity stability, supersession chains,
  circular justification detection, impact propagation, thread operations,
  warrant derivation, and provenance independence.

### Counterfactual conformance property

The conformance suite verifies a non-trivial structural property: identical
textual knowledge with different provenance topology can produce different
warrant. Graph A (shared upstream) yields `CONDITIONALLY_WARRANTED` while
Graph B (independent sources) yields `WARRANTED`, despite identical content.

## Intellectual background

The Cognitive Harness specification draws on several conceptual traditions:

- **Gerrit Müller** — CAFCR (*A Cognitive Approach for Flexibly Coordinating
  Reasoning*, 2004) inspired the Thread model and viewpoint-based reasoning
  traversal. Superretometer adapts, not reproduces, these concepts.

- **EPR criterion** — The Einstein-Podolsky-Rosen paper (1935) on "elements
  of physical reality" inspired the distinction between numerical completeness
  and independently grounded elements. A conclusion is warranted only if its
  premises are independently grounded.

- **Harness-of-Harness** — Yan et al. (2026) inspired orchestration layer
  separation, state preservation across reasoning trajectories, and progressive
  disclosure.

- **ISO/IEC/IEEE 42010** — Architecture description principles inform the
  layering and stakeholder-viewpoint structure.

These are sources of inspiration. Superretometer / Cognitive Harness is an independent work and
is not endorsed by the original authors. See `docs/` for detailed attribution.

## Project status

v0.6.5 — Packaged MCP server, CLI, and distribution.
v0.6.4 — Direction-aware traversal + enumeration completeness.
v0.1.0 — First public release. Specification and reference implementation are
stable. The conformance suite defines the behavioral contract. Breaking changes
to the model or warrant semantics will require a new major version.

## License

Apache-2.0. See [`LICENSE`](LICENSE).
