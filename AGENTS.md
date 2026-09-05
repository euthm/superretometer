# Superretometer — Agent Instructions

Superretometer is the reference implementation of the Cognitive Harness specification.

## Identity

- **Superretometer** — project, repository, MCP identity, website
- **Cognitive Harness** — specification and semantic model (in `spec/`)
- **`cognitive_harness`** — Python package (import paths)

## Normative hierarchy

1. `spec/` is the normative source of truth for semantics.
2. `tests/conformance/` defines the behavioral contract.
3. `cognitive_harness/` is the reference implementation.
4. `transports/`, `examples/` are non-normative.

## Rules

- **Implementation must not silently redefine semantics.** A change in `cognitive_harness/` that alters warrant behavior MUST be accompanied by a spec change and conformance test update.
- **Conformance tests are important.** A check that cannot fail is not evidence. Changing both implementation and expected test output in the same PR is a red flag.
- **No private Memory/EPF assumptions** belong in the public implementation. The public codebase uses `InMemoryStorage` only.
- **Relation/provenance semantics must be treated carefully.** Do not change edge directionality or relation types without a spec-change PR.
- **SimulationGatePolicy changes** must be accompanied by spec updates in `spec/WARRANT.md` and `spec/TERMINOLOGY.md` and conformance tests in `tests/conformance/test_simulation_gates.py`.
- **Run tests before proposing changes.** `python3 -m pytest tests/ -v` must pass.
- **Do not import WIP changes** from private runtime repositories.

## Quick commands

```bash
# Tests
python3 -m pytest tests/ -v

# Examples
PYTHONPATH=. python3 examples/minimal/run.py

# MCP server
PYTHONPATH=. python3 transports/mcp/server.py
```
