# Issue #19 preparation record

Date: 8 November 2026. This is a preparation record, not a performance report.

## Version boundaries

- Public evidence reference: PR #20, source commit
  `775362cbb2395860c09f05b724c403359697efae`.
- The operator reported local AI1 `main` fast-forwarded to this commit. At the
  first preparation check GitHub PR #20 remained open and remote main was
  `a86b3f547a5494fe906dbdd09a617eadd1bf0ce7`. The operator then completed the
  remote merge. A subsequent GitHub read verified PR #20 closed with merged=true
  and remote main at `775362cbb2395860c09f05b724c403359697efae`.
  The distinction is preserved: local state alone was not remote merge proof.
- This preparation is based on the #18 source commit. It makes no runtime,
  private Memory adapter, OpenCode config, model server or application changes.
- Issue #18 was administratively closed as the accepted public reference delivery;
  remote merge is now independently confirmed. Permanent installation/runtime
  bindings still require checks on the target machine.

## Ready for review

OpenSpec proposal/design/scenarios/tasks, profiles A–E, twelve quality controls,
measurement/acceptance definitions and a standard-library-only preflight probe.
The intended read-only first action is documented in
`examples/context_continuity/README.md`.

Official OpenCode docs were checked for current compaction and plugin migration
behavior. They require exact installed-build verification before selecting an
adapter path. No installed AI1 OpenCode version or plugin capability is claimed
from those public pages.

## Not yet established

No checkpoint core or client adapter is implemented in this preparation. No
actual context reduction, summary bypass, automatic Memory handoff, concurrent
model execution, saved tokens or speed improvement has been demonstrated.
The preparation tests validate definitions/probe behavior only; they cannot be
counted as passing context-continuity or prompt-injection controls.

Proceed: collect actual client/runtime/module and server/tokenizer/overhead facts;
implement public deterministic checkpoint/pack controls; prove exact-build native
fallback; then run the paired model pilot with independently executable quality
checks and #18 evidence packages.
