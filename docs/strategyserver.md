# StrategyServer workflow and compatibility

## Current maintainer setup

As of 25 October 2026, the maintainer reports using **StrategyServer** for the
local strategy workflow, replacing the previous local EPF workflow. This records
the current tool choice; it does not assert that StrategyServer has abandoned
EPF concepts internally or that an installed version has been inspected.

| Component | Responsibility |
|---|---|
| StrategyServer | External strategy context, priorities, and planning decisions |
| Superretometer | Claims, provenance, evidence dependencies, and recomputable gate assessments |
| External runner | Execute authorized work, collect actual results, and persist job state and evidence |
| Independent reviewer | Check the delivered revision and its evidence before approval |

An approved plan supplies decision context. It is not evidence that code works.
A gate assessment permits only the next step already authorized by the workflow;
it does not grant repository, merge, deployment, or production authority.

## Public implementation boundary

The Python reference implementation remains standalone and storage-independent.
Its bundled MCP server uses `InMemoryStorage`. A StrategyServer connection,
durable storage adapter, and automatic job dispatcher are not supplied by this
documentation change. Merely configuring both MCP services does not create
cross-service execution or persistence.

External integrations should read strategy context through the configured
StrategyServer interface and register claims/evidence through Superretometer's
public proposal pipeline. Proposal submission and execution are distinct steps;
the integration must arrange validation/execution through the supported
orchestration API. It must not mutate private storage fields.

Keep service credentials, endpoints, customer data, and local installation paths
outside the public repository. A future adapter needs verified service APIs and
integration tests before it can be described as implemented.

## Legacy EPF provenance

`ImplementationProvenance.epf_ready_id` and its JSON schema remain available for
historical EPF records. This change does not rename, delete, or reinterpret that
field. Existing manifests and release notes retain their original meaning.

New StrategyServer records must not place unrelated IDs into `epf_ready_id`.
An external integration should retain the strategy source, stable artifact ID,
and revision or content digest alongside its evidence manifest. A strategy
reference is context, not a substitute for repository identity, tested commit,
test output hash, or a falsifiable validator.

No StrategyServer-specific provenance field or API mapping is introduced here.
That would require a separate schema/API proposal and compatibility tests once
the actual service contract is known. The existing six implementation gates and
their expected outcomes remain unchanged.

## Background

Emergent Memory and Emergent Strategy remain part of the project's historical
attribution. Historical credit does not imply that the public package depends
on either service or that it describes the maintainer's current installation.
