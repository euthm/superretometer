# Pull Request

## Classification

Mark what this PR changes:

- [ ] Implementation (`cognitive_harness/`, `transports/`)
- [ ] Specification (`spec/`)
- [ ] Conformance tests (`tests/conformance/`)
- [ ] Adversarial tests (`tests/adversarial/`)
- [ ] Examples (`examples/`)
- [ ] Documentation (`README.md`, `docs/`)
- [ ] CI / tooling (`.github/`)

## Change declaration

- [ ] I have changed implementation code
- [ ] I have changed specification semantics
- [ ] I have changed conformance test expectations
- [ ] Existing expected behavior is changed by this PR

**If conformance expectations change:** explain why the previous expectation was wrong, not merely that the new implementation produces a different result.

## Description

<!-- What does this PR do? -->

## Testing

- [ ] `python3 -m pytest tests/ -v` passes
- [ ] Examples run correctly
- [ ] If specification changed: conformance tests updated and new behavior tested

## CH merge evidence (after the guard is activated)

- Candidate commit:
- `CH evidence` check / workflow run:
- Run ID and receipt SHA-256 (from `merge-result.json`):
- Evidence artifact or durable archive locator (CI artifacts expire after 30 days):
- Remaining limitations and separately reported warrant:
- [ ] Changes to tests, policies, workflows or the evaluator have human owner review
- [ ] H2 proposal does not merge itself, waive failed checks or change branch rules

## For specification changes (label: `spec-change`)

- [ ] Problem described
- [ ] Proposed semantic change stated precisely
- [ ] Examples/counterexamples provided
- [ ] Backward compatibility analyzed
- [ ] Conformance tests added/updated
- [ ] Maintainer approval requested
