# Changelog

All notable changes to cognitive-harness (Superretometer).

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
