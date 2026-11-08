# Issue #19: preparation before changing context management

This directory contains **test definitions and a read-only environment probe**.
It does not implement checkpoints, an OpenCode plugin, compaction replacement,
Memory integration or a measured throughput/token improvement. Run baseline and
functional controls before applying experimental settings.

Prerequisite for evidence capture: issue #18 commit
`775362cbb2395860c09f05b724c403359697efae` (PR #20), installed in the intended
permanent environment. A local fast-forward is not proof of a remote PR merge.
The diagnostic reports its own interpreter/module paths, not those of a running
MCP subprocess. Check the actual MCP process separately before a live pilot.

## First action on the target machine

Use the Python interpreter intended for Superretometer. From this checkout:

```bash
python examples/context_continuity/preflight.py --output /tmp/ch19-preflight-001.json
```

The output path must not exist and its parent must already exist. The probe only
runs the resolved `opencode --version` argv (ten-second timeout) and checks local
package metadata/module origins. It does not read `.env`, home client configs,
raw transcripts or credentials; does not call an LLM; does not change settings,
projects, worktrees or server slots. Unavailable facts remain null. A saved report
is not a benchmark PASS. Do not interpret version number alone as hook support.

Optionally provide deliberate allowlisted measurements in a separate JSON file:

```json
{
  "model_id": "configured-model-label",
  "quantization": "observed-quantization-label",
  "model_server_version": "observed-version",
  "tokenizer_id": "actual-tokenizer-label",
  "tokenizer_revision": "actual-tokenizer-revision",
  "context_tokens_per_slot": null,
  "parallel_slots": null,
  "system_tokens": null,
  "tool_schema_tokens": null,
  "output_reserve_tokens": null
}
```

```bash
python examples/context_continuity/preflight.py \
  --observations /path/to/allowlisted-observations.json \
  --output /tmp/ch19-preflight-002.json
```

Never pass the complete OpenCode configuration or environment dump. These are
operator-supplied observations; the probe does not independently query/verify the
server. URLs/credentials and unknown keys are rejected. No raw version-probe logs
are persisted. The diagnostic itself uses standard Python only.

## Freeze experiment inputs

`profiles.json` defines A–E for review. Its values are experimental candidates,
not deployed settings or measured optima:

| Mode | Strategy | Sessions | Candidate window |
| --- | --- | --- | --- |
| A | Current measured OpenCode behavior | 1 | Measure, do not infer from UI |
| B | OpenCode summary compaction | 1 | 65,536 total request tokens |
| C | CH checkpoint/pack + recent turns | 1 | Same as B |
| D | OpenCode summary compaction | 2 | Same effective per-slot limit as B |
| E | Hybrid | 2 | Same as D |

Start with A/B/C. D/E require two verified server slots, adequate device/KV
capacity and isolated code-writing worktrees. Two terminals alone establish none
of these. Background compaction stays off for the first comparison; any later
trial counts its tokens, latency and hardware competition explicitly.

Candidate transition is 49,152 tokens, with pack up to 4,096, recent turns around
12,288 and output reserve 8,192. Count actual system/tool schemas and active
source/results too. Unknown overhead prevents a budget-compliance claim. If
mandatory state cannot fit, declare capacity failure or a separate 96K cohort;
do not silently change a paired comparison or discard required instructions.

Pair B/C and D/E with matching tasks, model/quantization, tools, tokenizer,
resources, output reserve and cache conditions. A is context, not a substitute
for matched baselines. Rotate trial order; report warm/cold cache states and
available queue/prefill/decode times. Client/server limits are distinct.

## Functional and performance acceptance

`controls.json` freezes twelve proposed functional controls and negative checks.
They are **definitions, not executed conformance results**. The actual checkpoint
engine/plugin tests must show that each positive passes and each intentional
violation is detected. Use fixed executable oracles and held-out task assertions,
not an LLM's assessment of its own answer. Do not change expected outputs after
seeing trial results. The preflight tests validate only preparation tooling.

Proposed local pilot criteria (review/freeze before model trials): all mandatory
controls pass in every valid trial; no cross-session leakage, unsafe writes, lost
constraints or confused SHA/receipt binding. At least three task types and three
paired repetitions per type. Each matched comparison proposes median wall time
<=85% and observed total tokens <=80% of its baseline, with no per-task median
wall-time regression above 10%. These thresholds are a proposed operational
choice, not a result or statistical guarantee. Preserve negative/inconclusive
results; missing required measurements cannot be counted as zero.

Total tokens include foreground, summary and background/recovery calls. Record
input/output and cached-input components as supplied by the provider. Cached
input is a component of total input when the provider reports it that way;
do not add it twice. Retrieval/pack/storage/model work count in total wall time.
Report unobservable metrics as null plus a reason, not estimated hardware wins.

## OpenCode compatibility gate

Checked official docs on 8 November 2026:

- https://opencode.ai/docs/compaction
- https://opencode.ai/docs/build/plugins/server
- https://opencode.ai/docs/build/plugins/migrate-v1/

These describe V2 compaction and plugin APIs; they are not evidence that the
installed build supports them. Pin its exact version/build and matching SDK.
Inspect/test that version's context/compaction hooks, pending-call boundaries,
recent-turn retention and native fallback before enabling a bypass. V1 and V2
plugin implementations differ; do not migrate or upgrade the client automatically.
A standalone MCP tool does not control conversation compaction by itself.

## Evidence and next implementation

Reuse #18's capture/verify/import/evaluate/export flow for executable fixture and
pilot results. Keep small profiles/controls/checkpoint fixtures in Git. Preserve
raw per-run outputs, source/model/client/server identities, call IDs, measurement
completeness, logs and manifests in an explicitly retained archive. Synthetic
controls and real model trials must be labeled separately. No private project
IDs, access tokens, production transcripts or application conclusions belong here.

Next implement the public checkpoint/pack/restore/retrieval core and executable
controls; then one pinned OpenCode adapter with tested fallback; then the opt-in
model pilot. `openspec/changes/add-hybrid-context-checkpoints/` preserves the
proposal and tasks. This preparation changes no runtime behavior or warrant rules.
