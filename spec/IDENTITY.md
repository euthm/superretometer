# Identity Contract

## Normative Requirement

Every Knowledge Object MUST have a stable logical identifier (`id`) that is:

- Independent of storage backend (UUID, row ID, document pointer)
- Independent of session, process, or agent instance
- Independent of representation (JSON, protobuf, RDF)
- Stable across supersession (the successor KO has its own ID; the old ID persists in history)

## Backend UUIDs

Backend identifiers (database UUIDs, document pointers, etc.) MUST NOT define cognitive identity. They are implementation details of the storage layer.

## Graph Edges

All graph edges (relations, derivations, provenance links) MUST reference logical Cognitive Harness identifiers. Backend IDs must never appear in the cognitive layer.

## Identifier Format

v0.1 uses free-form strings. The only constraint is uniqueness within the knowledge graph. Examples:

```
"ko-thermal-capacity-2024-03"
"ev-steel-strength"
"conc-design-approved"
```

Future versions may introduce structured formats (URNs, JSON-LD IRIs) without changing semantics.
