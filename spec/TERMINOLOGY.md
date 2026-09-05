# Terminology

## Core Concepts

**Knowledge Object (KO)**: The atomic unit of structured knowledge. Contains a stable logical ID, content, type, truth category, epistemic status, confidence, provenance, and relations.

**Truth Category**: What kind of truth claim the KO makes (physical observation, conservation law, fitted parameter, model-derived, assumption, etc.)

**Epistemic Status**: The lifecycle state of the KO (proposed, tentative, validated, canonical, superseded).

**Confidence Level**: Speculative, low, medium, high, certain. Separate from warrant.

**Provenance**: Where the knowledge came from. Source, author, revision, independence flag, upstream derivation.

**Derivation**: How a KO was produced from upstream KOs or datasets. Types: FITTED, TRANSFERRED, VALIDATED, MATHEMATICAL.

**Relation**: Typed edge between KOs. SUPPORTS, DEPENDS_ON, SUPERSEDES, DERIVED_FROM, CONTRADICTS, etc.

**Dataset**: Collection of observations used to train or validate a derivation. Tracks source KO and lineage.

**Warrant**: Derived analysis of whether a conclusion is structurally supported by independent evidence. Not stored — computed.

**Thread of Reasoning**: Ordered investigation through viewpoints, inspired by Müller's CAFCR framework.

**Tension**: Identified conflict between KOs that requires investigation.

**Supersession**: A KO is replaced by a successor. The old KO is marked SUPERSEDED but remains in the graph. History is never deleted.

**Impact Set**: KOs affected by a change, computed by traversing incoming DEPENDS_ON and SUPPORTS edges.
