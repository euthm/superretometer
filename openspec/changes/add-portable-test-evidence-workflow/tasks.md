# Implementation checklist

- [x] Add proposed normative receipt, profile, evaluation and bundle contracts.
- [x] Preserve legacy blob-digest interpretation and existing gate/warrant rules.
- [x] Capture explicit argv, code pre/post/index/submodules, counts and artifacts.
- [x] Retain failed/not-run/timeout/unknown runs; validate profiles before execution.
- [x] Verify schema, counts-to-result bindings, file bytes and unsafe paths offline.
- [x] Implement proposal-backed import/readback through public storage contracts.
- [x] Add explicit POSIX-locked filesystem target with atomic ledger, same-ID
      reimport, conflict detection and separate-process scoped snapshot restoration.
- [x] Append evaluations with raw gates/warrant and exact receipt/graph/policy IDs.
- [x] Export complete, immutable-by-identity third-party evidence directories.
- [x] Expose SDK and additive CLI while preserving base CLI/MCP compatibility.
- [x] Add positive, isolated SHA/validator controls, tampering, dirty/missing inputs,
      parser uncertainty, partial import, redaction, archive expiry and restart tests.
- [x] Provide public synthetic eight-assertion fixture and full separate-CLI example.
- [x] Document retention, origin, self-consistency limits and migration boundaries.
- [ ] Final maintainer/spec review and CI approval before merge.

## Optional follow-ups (not claimed by this reference implementation)

- Native persistent/private Memory target: exact-ID, concurrency, readback and
  restart conformance must be demonstrated before claiming the same guarantees.
- CI/remote archive hosting and opt-in Rust/PostgreSQL project integration profile.
- Detached signing/attestation and MCP verify/import/evaluate/export transports.
- Bounded streaming output capture for exceptionally large runner logs (the local
  v1 runner buffers stdout/stderr until explicit redaction/publication).

No private deployment/runtime changes or HRRM execution results belong to this PR.
