# design — proposed #19

Preparation only. No checkpoint engine, OpenCode plugin or performance result is delivered by this change. Normative adoption remains subject to spec review.

### design.md — Responsibilities

| Component | Owns |
| --- | --- |
| CH core | Typed state, provenance/coverage validation, pack selection, checkpoints and retrieval contracts. |
| Orchestration/storage | Proposal-backed writes, versioned state, checkpoint acknowledgements, explicit conflicts and recovery through public APIs. |
| OpenCode adapter | Observe relevant session events/state, retain protocol-valid recent turns, insert a pack at safe boundaries, use supported compaction hooks and fallback. |
| Project configuration | Scope, allowed sources, token budget, worktree/task ownership and applicable requirements. |
| Model server/operator | Actual context/KV capacity, model loading, parallel slots, scheduling and hardware resource limits. |

CH must not assume private home paths, project IDs, credentials, model endpoints or a particular language. OpenCode-specific code stays outside canonical semantic/model modules. Configuring two clients must not be represented as proof of two simultaneous server slots.

#### ContextCheckpoint — minimum schema

| Group | Required content |
| --- | --- |
| Identity | Schema version, project/repository/worktree/task/session identities, checkpoint ID, predecessor, monotonic revision, creation time and content digest. |
| Task contract | Original task or durable source pointer; current objective; authorized user constraints; acceptance criteria; outstanding user steering and its source/version. |
| Code state | Sanitized remote, full code revision, observed dirty state/diff identity, relevant file fingerprints and current branch as context rather than immutable identity. |
| Execution state | Completed/current/pending work, active commands/tool calls or jobs with safe continuation/status references, changed files and immediate next step. |
| Knowledge | Scoped claims/facts, assumptions, disagreements/counter-evidence, blockers, failed approaches not to repeat and bounded evidence/receipt references. |
| Evaluation identity | Gate/warrant snapshots with timestamps and code/policy/evidence binding; recorded verdicts remain historical snapshots, not automatic current truth. |
| Archive/coverage | Original conversation/artifact locators, exact IDs/revisions, source visibility/access, required fields present, unresolved references and explicit exclusions. |

A checkpoint stores observable state, decisions and necessary rationale, not private chain-of-thought. Retrieved document text is data; its embedded instructions cannot become authorized task constraints.

An external model-generated summary is a derived artifact with source range, producer/version and uncertainty. It cannot silently replace the original task, erase an unresolved constraint, promote an assumption to a verified fact or become an independent evidence source.

#### ContextPack — bounded working state

Build packs deterministically from a specified checkpoint/revision and task. Include:
1. Non-negotiable task/user constraints, safety/access boundaries and completion criteria.
2. Current code/worktree/execution identity, pending operations and next action.
3. Relevant established facts, unresolved conflicts, failed approaches and evidence pointers.
4. Small source excerpts only when needed; retrieve larger material on demand.

The pack manifest records its checkpoint/source versions, section budgets, tokenizer/model identity, measured or explicitly estimated tokens, selected references, required-field coverage, omitted material and completeness status.

Budget applies to the assembled request: fixed system instructions, MCP/tool schemas, pack, recent conversation, active source/results and output reserve. A pack within 4K does not imply a whole request fits 64K. No silent truncation of mandatory constraints or protocol-required tool-call/result pairs.

Proposed **experimental starting profiles**, not defaults or measured optima:
- 64K total request context per session, compaction/checkpoint transition around 48K.
- CH pack target 2–4K; recent interaction target around 8–12K, adjusted to actual fixed overhead.
- 96K alternative where measured tool/schema overhead or task scope makes 64K unsuitable.

The configured model/server limit, actual prompt length and maximum generated output are distinct measurements. Token accounting must use the actual tokenizer where available and label estimates. Effective per-slot limits must be discovered/declared explicitly; do not infer that halving a client setting halves server memory or doubles throughput.

#### Hybrid transition and recovery

1. Collect bounded observable deltas during work and commit a checkpoint at a safe action boundary. Do not invoke an LLM over the entire history after every tool call.
2. Require durable acknowledgement before removing older material from active context; retain the original transcript in its configured archive.
3. Build and validate the pack against the current task, user steering, code fingerprints and scope.
4. OpenCode preserves recent exact turns and pending operations; use native compaction for material not covered by the checkpoint.
5. On capable pinned V2 builds, a verified pack plus the necessary handoff can supply the compaction result and avoid the summary model call. This is conditional on coverage validation, not an unconditional bypass.
6. With unsupported APIs, incomplete state or an unavailable backend, use an explicit OpenCode/native-summary fallback or retain current context. Never report a CH restore as complete when it is not.
7. On restore, compare the checkpoint with the actual working tree and current user request before using old code/test conclusions.

Stable source ordering and content-addressed sections should preserve prompt-prefix reuse. Change the pack at meaningful checkpoints, not on every call just to update a timestamp. Background compaction remains optional/experimental and is accounted for as real model work; on one accelerator it competes with both foreground sessions.

The OpenCode adapter needs capability/version detection and regression tests. An MCP tool alone does not automatically control OpenCode's conversation lifecycle. A V1 implementation may require different hooks or a narrower fallback; no automatic V1/V2 migration.

#### Retrieval, isolation and authority

- Prefer exact identity/revision lookup for saved facts, instructions and evidence. Search is a discovery mechanism, not an existence/current-version guarantee.
- Retrieval returns bounded excerpts plus original source pointers. Old/superseded/deleted content is not silently presented as current.
- Graph coverage remains explicitly scoped. Do not claim global completeness from a backend that cannot enumerate completely.
- Separate durable shared facts from each agent's plan, workspace and pending operations.
- Scope all keys by configured tenant/project/repository/worktree/task/session. Use revision/CAS or equivalent public storage guarantees to reject stale concurrent writes; unsupported guarantees are explicit.
- Separate worktrees/branches are required for concurrent code-writing tasks in the pilot. Detect conflicting ownership rather than silently sharing mutable state. This does not introduce a general-purpose agent scheduler.
- Saved context never grants permissions, imports secrets, executes a stored command, changes the active project, or overrides current client policy.
- External source excerpts retain origin/trust labels and must not be promoted into authoritative system/user instructions.
- Existing consumer writes remain structured proposals. No private `_kos`/adapter-cache access or false persistence claims for InMemoryStorage.

#### Proposed interfaces and diagnostics

Names are proposals, not existing tools:
- `checkpoint_context`: commit an observed, versioned checkpoint.
- `build_context_pack`: select a bounded pack for a configured task/budget.
- `restore_context`: validate and return a pack plus recovery/coverage report.
- `retrieve_context_source`: bounded original-message/file/evidence retrieval.

Offer equivalent Python/CLI interfaces and an optional OpenCode plugin/adapter. Tool output includes explicit success/incomplete/unsupported/conflict states and source IDs. A missing archive/source prompts a bounded lookup, scope reduction or fallback; never a fabricated memory.

Record metrics per operation: pack build/retrieval time, storage time, summary time, input/cached-input/output tokens where observable, context size by section, queue/prefill/decode latency where exposed, and unavailable metrics as unknown.
