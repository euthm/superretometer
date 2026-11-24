# Superretometer Go MCP server

The Go 0.10.0 server implements the complete **11-tool public MCP interface**,
plus explicit proposal execution, evidence readback, lifecycle operations and
both gate policies: **29 tools in total**. It runs as one native binary over
stdio or Streamable HTTP. Python is used for differential verification only.

The default graph is in memory. Set `--state` to retain knowledge objects,
evidence, proposals, tensions and history across restarts. Existing snapshot
files remain usable as initial data.

## Build and start

Use Go 1.25 or newer. From this directory:

```sh
mkdir -p bin
go build -trimpath -ldflags="-X main.revision=$(git rev-parse HEAD)" -o bin/superretometer ./cmd/superretometer
./bin/superretometer --version
./bin/superretometer mcp --state /absolute/path/state.json
```

Both `superretometer mcp ...` and `superretometer ...` work. The original preview
rejected the `mcp` subcommand and required a snapshot; this version accepts it
and can start an empty graph. Stdio output contains only MCP messages. An idle
stdio process waits for its MCP client, rather than printing a startup banner.

Use an absolute path in client configurations. The Go binary is built separately
from the Python package; installing `cognitive-harness` does not replace it.

### OpenCode local server entry

Replace only the Superretometer entry in your existing configuration:

```json
"superretometer": {
  "type": "local",
  "command": [
    "/absolute/path/superretometer",
    "mcp",
    "--state",
    "/absolute/path/state.json"
  ]
}
```

Use the surrounding config format supported by your OpenCode installation.
Native V2 puts entries under `mcp.servers`; supported V1 configurations put them
under `mcp`. A higher-precedence project entry can override the global entry.

## HTTP service

For a proxy on the same host:

```sh
./bin/superretometer mcp \
  --state /absolute/path/state.json \
  --listen 127.0.0.1:3010
```

Connect to `http://127.0.0.1:3010/mcp` using **Streamable HTTP**. The handler uses
MCP sessions; the client retains the session ID returned by initialization.
Sessions expire after 30 minutes of inactivity and are reinitialized after a
server restart. The graph and pending proposals survive when `--state` is set.

For access over a network, terminate HTTPS at an authenticated reverse proxy.
Non-loopback listeners require either a bearer token in
`SUPERRETOMETER_AUTH_TOKEN` or explicit `--behind-proxy`. The latter means the
operator has configured an authenticated proxy and isolated the origin port;
it does not authenticate requests itself. Override the variable name with
`--auth-token-env NAME`; token values are never passed as command arguments.

The server validates `Origin` for every MCP HTTP method. Browser clients behind
a TLS-terminating proxy can use an exact `--allowed-origin https://your-host`
entry. Native MCP clients without an Origin header are supported. HTTP request
bodies are limited to 4 MiB. `GET /healthz` returns version/revision and checks
that the knowledge state is available; it does not disclose graph content.

Writable HTTP requires `--state`. For an analysis-only service, use:

```sh
./bin/superretometer mcp \
  --snapshot /absolute/path/graph.json \
  --read-only \
  --listen 127.0.0.1:3010
```

Read-only mode removes mutation tools from the server, including proposal
submission and execution. Tool annotations alone are not used for enforcement.

### Docker / AWS

The supplied Compose service listens on `0.0.0.0:3010` **inside the container**
and publishes `127.0.0.1:3010` on the host for the existing authenticated proxy:

```sh
SUPERRETOMETER_REVISION=$(git rev-parse HEAD) docker compose up -d --build
docker compose logs --tail=50 superretometer
docker compose exec superretometer superretometer --healthcheck
```

Run these commands from `go/`. Compose uses a non-root process, a persistent
named volume, restart policy, health check and bounded memory. The default
memory limit is 512 MiB with a 384 MiB Go memory target; size it to the graph.
The standalone Docker image requires a token for its non-loopback listener;
Compose explicitly selects the proxy-protected configuration.

Point the proxy to `http://127.0.0.1:3010` when it runs on the host. A proxy in
another container must use the shared container network/service name instead.
Do not publish the origin port publicly when relying on `--behind-proxy`.

An OpenCode remote entry needs `type: "remote"` and the HTTPS `/mcp` URL.
For a Cloudflare Service Auth policy, supply the two service-token headers
through environment substitutions and set `oauth: false`. For OAuth, keep
OAuth enabled and authenticate in the client. The token must be authorized for
this application, not merely for another service on the same domain.

## Existing graphs and durable state

```sh
./bin/superretometer mcp \
  --snapshot /absolute/path/exported-graph.json \
  --state /absolute/path/state.json
```

The snapshot seeds **only a new state file**. An existing state is authoritative;
restarting with an older seed cannot overwrite it. The input snapshot is not
modified. The JSON document requires an `objects` array and can include
`datasets`, `evidence`, `tensions` and `proposals` arrays. Object and relation
fields follow the canonical Python models. Unknown metadata and JSON numeric
precision are retained in the stored records. Do not use
[`testdata/graph.json`](testdata/graph.json) as production data: it is a fixture.

Every mutation is validated on a separate candidate state. The service writes
and fsyncs a temporary file, atomically replaces the state, and syncs the
directory before acknowledging success. Precommit failure leaves state
unchanged. Ambiguous durability after replacement stops further access until
restart. State files are private to the service account. One writer owns each
state file; starting a second process on it fails clearly. Use a separate state
file/service for each project. This backend is intended for one process, not
multiple replicas sharing a file.

Back up the state file and keep the persistent volume when rebuilding. A backup
read sees either the preceding or complete new JSON document. Keep a stopped
service backup before changing storage format or migrating a production graph.

## Tools and workflow

| Group | Tools |
|---|---|
| Public analysis | `orientation`, `check_warrant`, `justification_path`, `scan_anti_patterns`, `open_tensions`, `review_required`, `impact_set` |
| Public proposals | `propose_ko`, `propose_relation`, `propose_evidence`, `propose_tension` |
| Gate policies | `check_simulation_gates`, `check_implementation_gates` |
| Readback | `get_ko`, `search_knowledge`, `get_evidence`, `list_evidence_for_ko`, `succession_chain`, `list_canonical`, `list_active_by_scope` |
| Proposal lifecycle | `submit_proposal`, `get_proposal`, `list_proposals`, `execute_proposal`, `execute_proposals` |
| State-change proposals | `propose_transition`, `propose_promote_canonical`, `propose_supersede`, `propose_update_ko` |

1. Submit a proposal and retain its `proposal_id`.
2. Inspect it with `get_proposal`.
3. Explicitly call `execute_proposal` with that ID.
4. Inspect its accepted/rejected result and the resulting object/evidence/tension.

Submission never executes automatically. New evidence is **pending**, not
verified. Repeating an accepted or rejected proposal returns the stored result
without applying it twice. Newly proposed knowledge is not automatically
independent evidence. Canonical promotion follows the existing specification:
validated state, linked verified evidence, and confidence at least medium.

`check_warrant` accepts `conclusion_ko_id` and the compatibility alias `ko_id`.
Gate tools use `ko_id`. Generic `submit_proposal` takes typed canonical Proposal
fields; `ko_content` is a JSON value, and `updates` is a JSON object. JSON-looking
strings remain strings; false, zero and null are not replaced by defaults.

The seven implementation gates assess supplied provenance for consistency.
Filesystem freshness is **UNKNOWN** unless the operator permits the checkout:

```sh
./bin/superretometer mcp --state /absolute/path/state.json \
  --repository-root /srv/repositories
```

The allowlist is configured by the operator, never by MCP arguments. Symlinks
cannot escape the allowed repository root during byte reads. Gate passes are
not independent certification that a submitted test or commit claim is genuine.

## Compatibility and deliberate corrections

The Go graph analysis is checked against the unchanged Python conformance and
adversarial fixtures. The proposal executor follows the specification where
the old implementation has defects:

- Confidence uses its defined order. The old lexical comparison rejected high
  confidence and could accept speculative confidence.
- All canonical promotion paths require linked verified evidence, and validate
  the final object for multi-field updates before changing any state.
- Accepted tension proposals materialize a tension. Completed proposals are
  idempotent across restart.
- Stable IDs and succession links cannot be rewritten by an object update.
  Self/cyclic supersession and rewriting terminal predecessors are rejected.
  Superseded state requires the explicit linked supersession operation.
- Relation updates validate relation types and endpoints. Additive graph
  relations/evidence retain the reference storage behavior; protected canonical
  content cannot be edited directly.

These fixes have explicit positive and negative tests; they are not hidden in
parity normalization. Python code and normative warrant rules are unchanged.

This is the standalone Go **MCP service**, with a local durable backend. The
Python checkpoint/test-evidence capture CLI and autonomous thread runner remain
separate tools. The private Memory/Strategy adapter is not copied into the
public server; use a complete graph export for migration. No NCM model or
inference dependency is introduced.

## Verification

From `go/`:

```sh
go test -race ./...
go vet ./...
```

From the repository root with the Python development dependencies installed:

```sh
python3 -m pytest tests/ -q
python3 scripts/check_go_parity.py --report go-parity.json
```

The differential runner replays unchanged Python tests and compares diagnoses,
roots, gate statuses/reasons, traversals, public reads and pending submissions.
Incomplete external backends are explicitly excluded and counted because a
complete snapshot cannot model objects deliberately hidden by that backend.
The CI additionally builds downloadable Linux amd64/arm64 binaries and tests
the container, persistent volume permissions and restart health.
