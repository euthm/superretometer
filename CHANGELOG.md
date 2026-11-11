# Changelog

All notable changes to cognitive-harness (Superretometer).

## [Unreleased]

## [0.8.0] — 2026-11-11

### Added
- Missing validation semantics: fitted parameters with incomplete lineage are
  consistently rejected across all callers, with spec-level documentation of
  the bypass conditions.
- `MISSING_INDEPENDENT_VALIDATION` anti-pattern: fitted parameters without an
  independent test dataset, with unregistered datasets, or with untraceable
  lineage are blocked with the correct diagnosis, distinct from circularity.
- Unified upstream traversal (`_trace_upstream`): single BFS over KOs and
  datasets with shared visited sets, consistent coverage across all callers.
- Provenance source normalisation: case, surrounding whitespace and internal
  whitespace runs are canonicalised before root comparison.
- Evidence validation: `PHYSICAL_OBSERVATION` KOs with dangling `evidence_ids`
  are no longer treated as independently grounded.
- HA controls for merge evidence: read-only scope preflight, reviewed source/
  receipt limits, POSIX process-group operation deadlines, phase/heartbeat
  diagnostics on stderr, and early rejection of existing output paths. Resource
  exhaustion never narrows coverage or produces approval; gate/warrant semantics
  and historical receipts remain unchanged.
- Fail-closed CI merge adapter: reviewed regression policy, complete
  tracked-file coverage, exact commit/repository binding, seven gates, isolated
  negative controls and verified bundle export.
- Manual checkpoint handover: versioned integrity-checked checkpoints,
  project/source validation, budgeted context rendering and explicit
  `checkpoint create/list/restore/inject` CLI commands.
- Portable test-evidence workflow: optional evidence SDK/CLI for explicit
  argv capture, schema/byte verification, proposal-backed portable target import,
  existing gate/warrant evaluation and checksummed third-party bundle export.
- Typed receipts, capture profiles and append-only evaluation/bundle contracts;
  path/length/file hashes supplement the unchanged legacy blob digest.
- Public eight-assertion fixture with separate-process replay, isolated commit/
  validator controls, no private services, and failure/tampering conformance tests.
- Explicit retention/locators, configured redaction, scoped snapshots and POSIX
  target locks.

### Fixed
- CALIBRATED_TO_CONCLUSION now fires only for actual circularity (training or
  test data traces back to the conclusion, or train/test roots overlap).
- Multi-hop circularity: dataset lineage walks KO upstream edges to completion
  (DERIVED_FROM, TRANSFERRED_FROM, upstream_ko_ids), not just one hop.
- Dataset cycles: shared visited sets prevent `RecursionError` on cyclic
  `derived_from_dataset_ids`.
- Sourceless dataset no longer suppresses leaf KO root collection.
- Evidence observation reuses its captured Git index for exact source/lockfile
  membership instead of launching a Git subprocess per file.
- Checkpoint subprocess hash test now reloads the same stored checkpoint in a
  fresh process.

### Changed
- CALIBRATED_TO_CONCLUSION for "no test dataset" is now MISSING_INDEPENDENT_VALIDATION.

### Clarified
- Implementation policy has seven gates; PASS is dimension-specific and is not
  independent certification. Existing policy/warrant algorithms are unchanged.

### Documentation
- Synchronize website/README package metadata from `pyproject.toml` and check
  for drift in CI; distinguish version notes from a published package release.
- Document portable evidence, manual checkpoint handover and the seven
  implementation gates on the public website.
- Record StrategyServer as the maintainer's current external strategy workflow,
  replacing the previous local EPF workflow.
- Clarify the boundary between external strategy/planning, Superretometer evidence
  evaluation, and job execution; retain historical `epf_ready_id` compatibility.

### Runtime
- Runtime server version guard: allowlist replaced with MIN_CANONICAL floor
  check (>= 0.8.0). A stale older package on PYTHONPATH no longer satisfies it.
- Runtime server excluded from wheel (`transports/` not in `pyproject.toml`
  `include`). PyPI distribution contains only `cognitive_harness`.
- Install commands in README, index.html, and release notes unified to
  `pip install git+https://github.com/euthm/superretometer@v0.8.0`.
- `scripts/sync_site_metadata.py` now checks install line consistency across
  README, index.html, and current release notes.

## [0.7.1] — 2026-11-07

### Added
- Contradiction detection in warrant analysis: `contradicting_kos` in WarrantResult,
  UNWARRANTED when contradicting evidence exists.
- `CONTRADICTION_INBOUND` relation set for counter-evidence traversal.
- `ko_truth_category` and `evidence_relation_type` parsed in `submit_proposal`.
- `evidence_relation_type` parameter in `add_evidence` MCP tool.
- Soft-delete via `delete_ko` (Memory API, clears mappings).

### Fixed
- InMemoryStorage passes `truth_category` in CREATE_KO execution.
- Memory adapter persistence: `lookup_by_key` limit 10→200, `Response.__bool__` fix,
  `_resolve_ch_id` fallback for CH-ID → Memory UUID resolution.
- MCP tool replies encoded as visible `CallToolResult` content.
- Lookup objects filtered from KO listing.

## [0.7.0] — 2026-09-06 (Candidate)

### Added
- `ImplementationProvenance` dataclass: 21 fields for code-bearing claims
- `ImplementationGatePolicy`: six-gate warrant policy (provenance, scope, worktree,
  test, falsifiability, dependency)
- `canonical_remote()`: transport-agnostic repository identity normalization
- `sanitize_remote()`: credential stripping for safe provenance storage
- Worktree reproducibility: `worktree_clean`, `worktree_diff_sha256`
- Test identity separation: `test_run_id` (runner), `validator_ko_id` (CH KO),
  `test_result_sha256` (artifact)
- Test execution provenance: `test_command`, `test_exit_code`, `tested_commit`,
  `tested_worktree_diff_sha256`, `test_timestamp`
- Dependency integrity: `submodule_pins`, `tested_submodule_pins` with canonical remotes
- Falsifiability gate: reuses `KnowledgeObject.validators` / `FalsifiableValidator`
- Timezone-aware ISO 8601 timestamp validation for portable provenance
- 30 CH-IMPL conformance tests (CH-IMPL-001 through CH-IMPL-030)
- `spec/schemas/provenance.schema.json`: `implementation_provenance` definition
- `spec/WARRANT.md`: ImplementationGatePolicy normative rules

### Changed
- `repo_remote_raw` renamed to `repo_remote_sanitized` (credentials stripped before storage)
- `repo_remote` field deprecated (backward compat maintained)
- Test gate semantics hardened: requires complete evidence chain + exit 0 + commit match
  + timezone-aware timestamp (legacy partial provenance → UNKNOWN, not PASS)
- Provenance gate no longer requires branch (detached HEAD eligible)
- Gate report now includes six gates: provenance, scope, worktree, test,
  falsifiability, dependency

### Deprecated
- `repo_remote_raw` → use `repo_remote_sanitized`
- `normalize_remote()` → use `canonical_remote()`

## [0.6.5] — 2026-09-06

### Added
- `cognitive_harness.__version__` — single version source from package metadata
- `cognitive_harness.cli` — CLI with `superretometer --version`, `superretometer --help`, `superretometer mcp`
- `[project.scripts]` entrypoint `superretometer = "cognitive_harness.cli:main"`
- `cognitive_harness.mcp.server` — packaged MCP server (moved from `transports/mcp/`)

### Changed
- MCP `serverInfo.version` now reports actual package version (was hardcoded `0.1.0`)
- MCP `orientation` uses `list_all_kos()` instead of private `_kos()`
- MCP `open_tensions` uses public iteration (was calling nonexistent `_list_tensions()`)
- MCP `propose_thread` removed from advertised tool surface (no ConsumerAPI backing exists)
- MCP `propose_ko` now passes `viewpoints` parameter (was missing required arg)
- MCP `propose_evidence` now passes `claim_id` (was passing `claim_ko_id`)
- `transports/mcp/server.py` becomes deprecated compatibility shim
- `[mcp]` optional dependency removed — MCP server uses only stdlib JSON-RPC

### Fixed
- `RELEASE_NOTES_v0.1.0.md` moved to `docs/releases/v0.1.0.md`

### Removed
- `mcp>=1.0.0` from optional dependencies (not used)

## [0.6.4] — 2026-09-06

### Added
- `cognitive_harness.exceptions.IncompleteEnumerationError` — raised when FULL_REQUIRED analyses cannot guarantee complete graph enumeration
- `StorageInterface.enumeration_complete` property — backends declare whether `list_all_kos()` is provably complete
- `StorageInterface.get_outgoing_relations()` / `get_incoming_relations()` — direction-aware relation access
- `JUSTIFICATION_INBOUND` / `JUSTIFICATION_OUTBOUND` relation sets — direction-aware justification traversal
- `InMemoryStorage` implements direction-aware methods

### Changed
- WarrantAnalyzer: direction-aware BFS through justification graph — SUPPORTS/VALIDATES traversed as incoming, DEPENDS_ON/DERIVED_FROM as outgoing
- WarrantAnalyzer: `detect_all_anti_patterns()` fails closed with `IncompleteEnumerationError` when `enumeration_complete` is False
- `InMemoryStorage.compute_impact_set()`: direction-aware — if evidence changes, impact flows to supported claims; if prerequisite changes, impact flows to dependents
- `InMemoryStorage.get_justification_path()`: direction-aware traversal
- Custom `StorageInterface` backends must now implement `get_outgoing_relations()` and `get_incoming_relations()`
- Test fixtures: SUPPORTS relations created with `storage.create_relation(evidence, conclusion, SUPPORTS)` instead of embedding in KO relations

### Fixed
- Direction semantics: SUPPORTS edges were traversed in wrong direction (outgoing from conclusion instead of incoming to conclusion)
- Cycle detection: direction-aware to avoid false positives from mixed-direction graphs

### Known Limitations
- Memory HTTP backend enumeration (`MemoryAdapter.list_all_kos()`) is NOT provably complete — search-based pagination may miss entities
- FULL_REQUIRED analyses (`detect_all_anti_patterns`, `list_review_required`) fail closed on Memory HTTP backend
- LOCAL_COMPLETE_ADJACENCY operations (warrant, gates, impact, justification path) remain usable when local adjacency is complete

## 0.6.3 — Storage Backend Contract + list_all_kos

### Added
- `spec/STORAGE.md` — formal storage backend contract document
- `list_all_kos()` to `StorageInterface` — required for all backends
- `InMemoryStorage.list_all_kos()` — reference implementation
- `WarrantAnalyzer._iter_all_kos()` — uses `list_all_kos()` only, no `_kos` access
- Conformance test `test_storage_independence.py` with `NoKosStorage` — proves
  `WarrantAnalyzer` operates correctly without private storage attributes

### Changed
- `WarrantAnalyzer.detect_all_anti_patterns()` — iterates via `list_all_kos()`,
  not `_kos`. Callers must not reach into internal storage state.

### Design Decisions
- `list_all_kos()` is mandatory — backends that paginate must page to completion
- No `_kos` compatibility shim — private attributes are not part of the contract
- Adapters must NOT implement warrant, anti-pattern, or gate logic

## 0.1.0 — Initial Public Release

### Added
- Knowledge Object model with seven independent dimensions
- Structural warrant analysis (graph-based, not keyword-based)
- Six structural anti-pattern detectors
- Falsifiable validators (what_would_falsify)
- Threads of Reasoning (CAFCR viewpoint traversal)
- Supersession without deleting history
- Impact propagation on knowledge changes
- InMemoryStorage reference implementation
- StorageInterface abstract contract
- MCP reference server (11 tools)
- JSON Schema definitions
- Adversarial benchmark (20/20, 100% P/R)
- Conformance test suite (identity, warrant structure)
- Examples: minimal, structural engineering, engineering model (anti-pattern demo)

### Design Decisions
- Warrant is derived, not stored
- Agents propose; orchestration validates
- Logical identity independent of storage backend
- Python reference implementation; specification defines semantics
