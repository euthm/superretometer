# Changelog

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
