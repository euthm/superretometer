# Changelog

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
