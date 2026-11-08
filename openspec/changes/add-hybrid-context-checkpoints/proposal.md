# proposal — proposed #19

Preparation only. No checkpoint engine, OpenCode plugin or performance result is delivered by this change. Normative adoption remains subject to spec review.

### proposal.md — Why / What / Scope

**Why:** active context should carry the information needed for the next action, while durable storage retains the history and its provenance. Saving tokens by dropping a constraint or redoing a test is not an improvement.

**What:**
1. A language/model/client-independent ContextCheckpoint contract.
2. A deterministic, token-budgeted ContextPack builder with explicit coverage and omissions.
3. Bounded retrieval of original messages, source/evidence and missing details.
4. An optional OpenCode integration that blends the pack with recent conversation and provides native-compaction fallback.
5. Session/worktree isolation and reproducible quality/performance evaluation.

**MVP:** public filesystem/InMemory fixtures; explicit checkpoint/build/restore operations; one pinned OpenCode adapter; no mandatory Memory service, paid model or project-specific code.

**Non-goals:** replace OpenCode, build a new external harness/scheduler, change model weights, rewrite warrant, infer new permissions from saved text, promise lossless natural-language summarization, start concurrent model instances automatically, or require full-history export into the knowledge graph.
