# Contributing to Superretometer

## Naming

- **Superretometer** — project, repository, reference implementation
- **Cognitive Harness** — specification and semantic model
- **`cognitive_harness`** — Python package name (import paths)

## Specification vs. Implementation

The specification (in `spec/`) defines semantics. The Python reference implementation (`cognitive_harness/`) is normative while the specification is stabilizing.

Other implementations may claim conformance by passing the public conformance suite (`tests/conformance/`).

## Development Workflow

```
issue / proposal
      ↓
branch
      ↓
pull request
      ↓
CI
      ↓
review (≥ 1 approving)
      ↓
merge (squash)
```

- `main` is protected. Direct pushes are disabled.
- All changes require a pull request.
- At least one approving review is required.
- Conversations must be resolved before merge.
- CI must pass.
- Squash merge is preferred for ordinary contributions.
- Merged branches are deleted automatically.

## Pull Requests

1. Update `CHANGELOG.md` with your change
2. Ensure `tests/conformance/` passes
3. Fill out the PR template classification checklist
4. If changing the specification, update `spec/` documents and JSON Schemas

## Specification Changes

Changes to specification semantics are treated differently from implementation changes.

A PR changing documentation, implementation bugs, MCP transport, examples, or
performance is **not** equivalent to a PR changing warrant semantics, relation
semantics, epistemic states, provenance semantics, or normative JSON schemas.

Semantic/specification changes **must**:

1. Use the `spec-change` label
2. Describe the problem
3. State the proposed semantic change precisely
4. Provide examples/counterexamples
5. Describe backward compatibility impact
6. Add or update conformance tests
7. Receive explicit maintainer approval

**Do not allow an implementation change to silently redefine the specification.**

## Protecting the Conformance Suite

A check that cannot fail is not evidence.

A PR must not be considered valid merely because it changes implementation and
expected test output together. If conformance test expectations change, explain
why the previous expectation was wrong — not merely that the new implementation
produces a different result.

## Code Style

- English comments
- Minimal diffs — touch only what is required
- No drive-by refactors

## Reporting Issues

Include:
- Reproducible example (preferably a conformance test)
- Expected vs. observed behavior
- Whether it is a specification or implementation issue
