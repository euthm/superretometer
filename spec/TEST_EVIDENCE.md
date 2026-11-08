# Portable test evidence (v1, proposed in #18)

This additive contract is submitted for spec review. It does not change the seven
ImplementationGatePolicy gates, warrant, independence, truth-category defaults,
legacy provenance, or the simulation policy. Normative schemas live in
`spec/schemas/test-*.schema.json`; identical packaged copies enable installed CLI
validation. OpenSpec change files describe the proposal, not a second authority.

## Trust and distinct verdicts

A receipt is **runner-reported** evidence. Verification checks format, included
bytes, internal bindings and, when explicitly mapped, current local code state.
It cannot authenticate the runner or prove absence of fabricated observations.
Checksums are not signatures, independent review, safety or production approval.
N-IMPL-SELFCONSISTENCY continues to apply.

Four results MUST remain distinct:

1. Actual command exit/outcome and observed test counts.
2. Byte-integrity and capture completeness.
3. Existing raw gate results and computed `design_bearing`.
4. Existing raw warrant, without manufactured independent roots or truth labels.

The reference workflow adds `approved`: true only for a baseline with domain
acceptance PASS, complete capture, verified current mapped source and all seven
gates PASS. This is scoped workflow acceptance, not release/deployment approval.
The gate policy does not itself count tests: incomplete count evidence can have
self-consistent raw gate metadata but MUST NOT become workflow approval.

## Receipt and capture

`test-run/v1` is immutable by content identity. `run_id` is a fresh UUID for every
execution/retry. `receipt_sha256` is SHA-256 of the exact canonical `run.json`
bytes, stored externally to avoid a self-hash cycle. There is no evaluation in
the execution receipt. Unknown required schema/algorithm versions and unknown
fields are rejected. Duplicate JSON keys and non-finite numbers are rejected.

Canonical JSON is UTF-8 of Python-compatible JSON: lexically sorted string object
keys, `ensure_ascii=True`, separators `,` and `:`, no whitespace/newline, no NaN or
Infinity. Receipt v1 has no measured floating-point fields except an optional
finite positive timeout. Integers are serialized as decimal JSON integers. This
encoding is named here; it is not a claim of RFC 8785 conformance. Imported receipt
bytes MUST already be canonical. Other issuers must implement this encoding.

The explicit capture profile declares repository root, source files, lockfiles,
bounded claim, authorized remote, optional requested full commit, falsifier,
acceptance requirements, parser, tools/services/exclusions and archive locator/
retention. Services and claim constraints are **operator declarations**; tool
version commands and execution are observed. All relevant tool commands are
explicit argv; none is inferred from an uploaded document. Missing observation
is null/unknown, never clean, exit zero, zero skips, or a fabricated version.

Only `evidence record ... -- <argv>` (or explicit SDK `record`) runs a command.
It introduces no shell. `argv_template` preserves operator input; `argv` records
the actual substituted vector. `cwd="."` is bound to the explicitly configured
repository root; `{repo}`/`{output}` substitutions happen only during recording.
Import, verification, evaluation and export MUST NOT execute receipt commands,
follow archive locators, use producer-controlled repository paths, or make a
network connection. The reference runner captures stdout/stderr in memory before
redaction/publication; scope output volume and use timeouts for local commands.

Profiles are validated before execution. Output is outside the tested worktree,
with a fresh staging directory for each child. Nonzero exits, inability to start,
timeout and signal outcomes are retained with the actual child exit code/null.
A timeout kills the local process group on POSIX; the original outcome remains
`timed_out` even if the child subsequently exits. No shell pipeline is added that
can hide the child's exit code. An operator-supplied shell pipeline remains the
operator's responsibility.

### Input and worktree observations

Measure Git full commit/object format, branch context, porcelain status, binary
tracked diff from HEAD (index + worktree), and all nonignored untracked contents
before and after execution. The diff fingerprint is SHA-256 of canonical JSON
`{staged_diff_sha256,unstaged_diff_sha256,index_sha256,untracked:[{path,size,sha256},...]}` in Git path order, named
`staged-unstaged-untracked-sha256-json/v1`. Separate index/staged/unstaged
observations retain intermediate staged content even if the worktree matches HEAD.
This is a fingerprint, not an archived patch. Secrets in patches are not stored.

Observe declared source/lockfile manifests and recursive submodule pins, remote,
initialization and dirty state. Missing/symlink/nontracked declared inputs,
uninitialized/unresolved/dirty submodules or unavailable tool observations make
capture incomplete. No submodules is observed N/A, not guessed from absent config.
Relevant ignored inputs must be explicitly declared; ignored/generated inputs
outside the profile are excluded. Pre/post differences make capture incomplete;
unavailable post-state is null. Dirty pre-state stays dirty even if a command
cleans the worktree. Pre/post snapshots cannot detect transient mutations that are
reverted between observations. External services/dependencies outside the declared
profile are not verified automatically; record exclusions honestly.

A source manifest is sorted unique normalized relative paths, each bound to byte
size and SHA-256. `path-size-sha256-json/v1` is SHA-256 of canonical JSON of this
ordered list. Missing files cannot silently disappear into a verified manifest.
Paths cannot be absolute, dot segments, backslashes, drive prefixes, controls,
`.git`, or symlinks. No glob expansion is implicit.

Legacy `blob_digest` is still `sorted-concatenated-content-sha256/v0`: SHA-256 of
concatenated file bytes in sorted path order, using the existing gate helper.
Its meaning is unchanged. The new manifest provides the missing path/length
boundaries; receipt verification checks both declared coverage and current
manifest. The receipt layer rejects missing paths even though the legacy helper
would otherwise skip them. This does not silently tighten legacy metadata-only
claim evaluation.

### Result adapters and acceptance

`counts-json/v1` reads a `counts/v1` report with exactly `schema_version`, `counts`
and `test_ids`. Counts are nonnegative integers for discovered, executed, passed,
failed, skipped; executed = passed + failed; discovered = executed + skipped.
Unique nonempty IDs cover all discovered cases. This small protocol is usable
from any language. `junit/v1` reads UTF-8 JUnit testcase elements (without DTDs or
entities), counting errors as failures and reporting skipped cases separately.
Ambiguous, malformed or incomplete reports yield unknown counts and a parser
reason. `unknown/v1` explicitly preserves unknown counts even with exit zero.
Verification re-parses the included structured bytes and checks receipt counts/
IDs against them; a receipt cannot independently assert a different test count.

Domain acceptance checks actual execution plus the profile's expected execution
count, zero-failure/no-skip constraints and required IDs. A known violation is
FAIL; unavailable observations are UNKNOWN. A complete failed run remains valid
recorded evidence, without an accepted supporting relation or workflow approval.

## Artifacts, redaction and archive

Artifact paths are normalized relative paths, with role, byte length, SHA-256,
`bundle-relative` locator, transformation and derivation. Exactly one stdout and
stderr stream and at most one structured result are permitted in v1. Imported
file and directory symlinks, missing/unbound files and unsafe paths are rejected.
The v1 transport accepts directories or `run.json`, not tar/zip extraction.

Configured `redact_env` names supply exact sensitive values from the recording
process environment. No environment dump is persisted. Reject these values in
profile/argv metadata before execution; sanitize Git URL credentials and query/
fragment data; redact output bytes before final publication. Hash the **exported**
bytes. Mark transformed artifacts `redacted`, preserving derivation; never label
them original raw bytes. Redacted/unavailable tool versions are unknown.
No claim is made that exact-value redaction detects arbitrary secrets; capture
profiles and commands must not print undeclared credentials. Child-produced result
files exist in temporary staging until transformed/published, then are removed.

The configured archive MUST have an explicit retention policy and locator.
Local reference capture preserves per-run directories until explicit operator
removal. It does not automatically promise a remote durable service, upload to a
locator, or retain ephemeral CI URLs. Operators own the configured filesystem's
backups and third-party retention. Keep code, small fixtures, profiles and compact
evidence indexes in Git; retain bulk run artifacts in the configured archive.

## Proposal import and portable target

The public reference target is explicitly `portable-inmemory/v1`, configured with
an ID, filesystem root and canonical-remote → local-checkout mapping. It does not
read private/home configuration or write to a live Memory session. Other target
kinds are rejected, not silently downgraded. A future private adapter needs exact
identity, serialization/concurrency and readback contracts before it can claim
these guarantees.

Validate receipt and all bound bytes before writes. Create claim, carrying
execution evidence and validator KOs via CREATE_KO proposals, attach measured
ImplementationProvenance and FalsifiableValidator via UPDATE_KO proposals, then
create SUPPORTS (evidence → claim) and VALIDATES (validator → claim) through
CREATE_RELATION proposals only when domain acceptance passes. Keep the default
ASSUMPTION truth category and explicit dependent runner provenance. Failures and
unknowns are archived without manufacturing successful support. Read back nodes,
provenance, validator and edges; rejection or incomplete readback is not acceptance.

Mappings explicitly separate `ch_id` and `backend_id` (equal only in this public
reference target). Persist identity by target ID + run ID + receipt digest. Same
receipt returns the same IDs with no duplicate edges; same run ID with changed
content is a conflict. Per-target POSIX nonblocking process locks reject concurrent
writers. Atomic receipt/snapshot publication and ledger replacement prevent an
interrupted import from exposing a partially accepted graph. A crash may leave an
unreferenced verified receipt; a later retry can use it. Guarantees cover process
restart, not unsynced storage/power-loss durability or hostile local filesystem
writers. POSIX locking unsupported on another OS is an explicit error.

InMemoryStorage is still volatile. A new process **explicitly restores** the
portable target's scoped three-node snapshot through public storage CRUD,
checking mappings, typed objects and relations. This restores prior proposal
results; it does not re-execute arbitrary proposals or commands, access `_kos`,
or pretend a bare InMemory instance survives process exit. The scoped archive
contains proposal-result identities and the complete graph used by this workflow,
not an entire private knowledge base. The target snapshot checksum detects byte
changes, not a malicious issuer recomputing its own unsigned checksum.

## Evaluation and export

Each evaluation is a fresh UUID and immutable directory. Persist receipt digest,
run/target IDs, timestamp, control label, exact graph inputs, current verification
context, raw gates and raw warrant. Policy identity includes installed package
version and a path-bound digest of all `cognitive_harness/**/*.py` source bytes.
Producer identity also records this source digest, covering uncommitted/editable
code rather than falsely treating a version string as exact identity.

The baseline projects observations into existing ImplementationProvenance without
changing gate algorithms. Dirty state remains UNKNOWN under current policy. A
mapped matching checkout is required for current approval. Missing mapping/source
makes freshness unavailable/UNKNOWN. Preserve historical responses; a newly
observed mismatch/unavailable source cannot become a new current PASS merely by
copying an old snapshot.

Negative controls modify only an ephemeral evaluation graph and are labeled:
`commit_mismatch` changes only claim commit to a different full-length value;
`missing_validator` removes only its provenance validator binding. Keep the
original execution receipt and imported graph unchanged. The first control must
BLOCK test while unrelated gate statuses retain the baseline; the second must
make test UNKNOWN. Reasons may include the changed commit. Neither control is
approved or presented as a genuine new test execution.

A bundle binds one execution receipt and selected evaluations:

- `run.json`, original-or-explicitly-transformed logs and structured test result.
- `evaluations/<id>/{evaluation,gates,warrant,graph}.json` for each selected run.
- `README.md` explaining scope, trust limits and inspection/reproduction.
- `SHA256SUMS`: versioned **canonical JSON**, not shell checksum syntax. `files`
  maps every included relative file name to size + SHA-256, excluding itself.

There is no hash cycle: run binds artifacts; evaluation binds run and graph; the
manifest binds run, artifacts and evaluations, not itself. The exported manifest's
hash is returned externally. Missing/extra files and byte changes are rejected.
Historical snapshot bindings and raw-response equality are checked offline.
Verifying a historical bundle never silently re-evaluates it. Export to an
existing destination is rejected; later evaluations/exports use new identities.
Optional signing/remote archive hosting and native Memory import remain future
adapters, not a prerequisite or implied capability of this reference target.

## CLI and compatibility

Install `cognitive-harness[evidence]` (JSON Schema validator); base CLI/MCP continue
to work without this optional extra. Equivalent Python API is exported from
`cognitive_harness.evidence`. The CLI adds record, verify, import, evaluate and
export; see `examples/test_evidence/README.md`. No arbitrary runner tool is added
to MCP. Existing CLI/MCP/provenance APIs remain compatible.

Exit codes: 0 = successful operation (record/evaluate require their stated scoped
acceptance), 2 = rejected/invalid/incomplete operation, 3 = recording acceptance
UNKNOWN, 4 = failed domain acceptance or nonapproved evaluation. Child exit code
is a separate receipt/output field. `verify` exit 0 certifies included byte/
contract integrity only; `import` exit 0 means durable scoped import, not approval.
The machine-readable JSON response states the actual verdicts.
