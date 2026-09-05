# Contributing to Superretometer

## Naming

- **Superretometer** — project, repository, reference implementation
- **Cognitive Harness** — specification and semantic model
- **`cognitive_harness`** — Python package name (import paths)

## Specification vs. Implementation

The specification (in `spec/`) defines semantics. The Python reference implementation (`cognitive_harness/`) is normative while the specification is stabilizing.

Other implementations may claim conformance by passing the public conformance suite (`tests/conformance/`).

## Pull Requests

1. Update `CHANGELOG.md` with your change
2. Ensure `tests/conformance/` passes
3. If changing the specification, update `spec/` documents and JSON Schemas

## Code Style

- English comments
- Minimal diffs — touch only what's required
- No drive-by refactors

## Reporting Issues

Include:
- Reproducible example (preferably a conformance test)
- Expected vs. observed behavior
- Whether it's a specification or implementation issue
