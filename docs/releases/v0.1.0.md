# Release Notes — Superretometer v0.1.0 (Cognitive Harness Reference Implementation)

First release of Superretometer, the reference implementation of the Cognitive Harness specification.

## What is Cognitive Harness?

An LLM-independent specification and reference implementation for structural
engineering reasoning and epistemic warrant. It answers:

> What justifies this conclusion — and what would have to change if its
> justification fails?

## What's in v0.1.0

### Specification

- **Logical identity contract** — stable identifiers independent of storage
  backends (`spec/IDENTITY.md`)
- **Warrant semantics** — derived epistemic status from graph structure, not
  stored truth (`spec/WARRANT.md`)
- **Architecture** — layered separation: storage → model → reasoning → analysis
  → orchestration → consumer (`spec/ARCHITECTURE.md`)
- **Terminology** — precise definitions of knowledge objects, provenance,
  warrant, threads, tensions (`spec/TERMINOLOGY.md`)
- **Reasoning** — rule engine and derivation semantics (`spec/REASONING.md`)
- **JSON schemas** — machine-readable type definitions for all model objects
  (`spec/schemas/`)

### Reference implementation

- **Knowledge object model** — typed KOs with provenance, relations, validators,
  and derivation chains
- **Provenance and evidence-independence analysis** — traces evidence back to
  independent provenance roots; shared upstream weakens warrant
- **Structural warrant** — computes warrant status (`WARRANTED`,
  `CONDITIONALLY_WARRANTED`, `UNWARRANTED`, `UNRESOLVED`) from graph structure
- **Anti-pattern detection** — six structural diagnoses derived from graph
  topology (not keyword classification)
- **Threads of Reasoning** — auditable, restartable reasoning traces with
  viewpoint traversal (conceptual → functional → realization → application)
- **Tensions** — competing conclusions tracked as first-class graph objects
- **Supersession and history preservation** — revisions create succession chains;
  old KOs marked `SUPERSEDED`, not deleted
- **Impact propagation** — transitive impact analysis marks downstream dependents
  as `REVIEW_REQUIRED` when upstream knowledge changes
- **InMemoryStorage** — complete in-memory implementation of `StorageInterface`

### Optional MCP server

- Standalone MCP server over JSON-RPC stdio
- 11 tools: orientation, check_warrant, justification_path, scan_anti_patterns,
  open_tensions, review_required, impact_set, propose_ko, propose_relation,
  propose_evidence, propose_tension, propose_thread
- Uses `InMemoryStorage` by default; pluggable via `StorageInterface`

### Public conformance suite

- **13 adversarial tests** — each anti-pattern tested against carefully
  constructed graph configurations designed to produce false positives and
  false negatives
- **14 conformance tests** — identity stability, supersession chains, circular
  justification, impact propagation, thread operations, warrant derivation,
  provenance independence
- **27/27 tests passing** at release preparation

### Counterfactual conformance property

The conformance suite verifies a non-trivial structural property: identical
textual knowledge with different provenance topology produces different warrant.

Graph A (three tests sharing one upstream simulation) yields
`CONDITIONALLY_WARRANTED` while Graph B (three tests from independent
measurements) yields `WARRANTED`, despite the text of the knowledge objects
being identical.

This demonstrates that warrant depends on provenance structure, not on content.

### Examples

- `examples/minimal/` — a warranted conclusion from independent evidence
- `examples/structural_engineering/` — bridge cable safety analysis
- `examples/engineering_model/` — demonstrates three anti-patterns leading to
  an UNWARRANTED conclusion with explicit evidence gaps

## What is not included

- No LLM-specific adapters or prompt templates
- No persistent storage backends (use `InMemoryStorage` or implement your own)
- No A2A protocol or inter-agent messaging
- No JSON-LD or RDF serialization
- No Python package on PyPI (available via source or git clone)

## Requirements

- Python >= 3.10
- Zero required dependencies
- Optional: `mcp>=1.0.0` for MCP transport
- Optional: `pytest>=7.0` for running the test suite

## License

Apache-2.0

## Attribution

See `docs/` for intellectual background and attribution. Cognitive Harness draws
on concepts from Gerrit Müller's CAFCR, the EPR criterion, and the
Harness-of-Harness framework. It is an independent work, not endorsed by the
original authors.
