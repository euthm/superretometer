# Update a local Superretometer MCP installation

Use one reviewed Superretometer checkout for the MCP server and optional
examples. Updating another project that uses CH does not update this checkout.
A running Python process must be restarted before it uses newly installed code.

## What is included

| Component | How it runs |
|---|---|
| CH core and bundled MCP | Base package; `superretometer mcp` over stdin/stdout |
| Harness2 integration smoke test | Optional script in this Git checkout |
| Julia advisory | Optional local endpoint passed explicitly to the smoke script |
| HTTP/Cloudflare wrapper | External deployment; not supplied by this package |

The optional examples do not add H2/Julia MCP tools or start model servers.
Pulling the repository does not change a client's configured interpreter.

## One-time setup

Use Python 3.12 or 3.13 if you also want the optional H2 example. The core
package supports the Python versions declared in `pyproject.toml`.

From your reviewed checkout, create a dedicated environment if one does not
already exist:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

For a client that starts local stdio MCP servers, configure the absolute path
to this environment's executable, for example:

```json
{
  "command": "/absolute/path/to/superretometer/.venv/bin/superretometer",
  "args": ["mcp"]
}
```

Adapt the surrounding configuration to your MCP client. If an existing
installation has a different environment or wrapper, inspect its actual
startup configuration and update that environment; do not assume this
example changes the active server.

## Later updates

After a reviewed PR has merged, update the checkout's `main` branch.
First inspect the remote, branch and local changes:

```sh
git remote -v
git branch --show-current
git status --short
```

The remote should be your intended `euthm/superretometer` repository. Preserve
local changes or use a separate worktree before proceeding. On a clean
`main` branch, pull and install into the environment used by your MCP client:

```sh
git pull --ff-only
.venv/bin/python -m pip install -e .
git rev-parse HEAD
.venv/bin/superretometer --version
.venv/bin/python -c 'import sys, cognitive_harness; print(sys.executable); print(cognitive_harness.__file__)'
```

If a fast-forward is rejected, inspect the divergence rather than resetting
or force-updating the checkout. A PR branch can be reviewed in a separate
worktree before merge; do not describe it as released `main`.

The editable install links this environment to this checkout. Later Python
source edits are visible to a new process; repeat installation after dependency,
package-metadata or entry-point changes. The command above makes the intended
installation explicit.

## Reconnect and verify

The bundled MCP server uses **InMemoryStorage**. Its graph is lost when that
process ends. Preserve important evidence using your integration's supported
export/persistence mechanism before restarting. Neither a Memory note nor a
Git pull automatically preserves the live MCP graph.

Restart/reconnect only Superretometer through the client or existing service
manager that owns it. Leave other services running. Then:

1. Verify the actual client command points to the environment inspected above.
2. Inspect the MCP `initialize` response: server name should be
   `superretometer` and its version should match the installed package.
3. Run `tools/list` and call `orientation` through the actual client connection.
   Orientation verifies a response and graph state, not the Git SHA.
4. Record the checkout SHA, Python/module paths and connection result together.
   A version string alone does not distinguish commits with the same version.

The stock MCP exposes proposal submission separately from execution.
A proposal ID or a manually written gate table is not proof that an
implementation gate evaluated a claim. Preserve the actual execution/evidence
receipts when reporting such evaluations.

## Optional CH + H2 + Julia smoke test

From the same checkout, use a separate example environment if you want to
keep optional H2 dependencies out of the MCP environment. With Python 3.12/3.13:

```sh
python3 -m venv .venv-toolchain
.venv-toolchain/bin/python -m pip install -r examples/toolchain_pilot/requirements.txt
.venv-toolchain/bin/python examples/toolchain_pilot/run.py
```

An existing pinned H2 checkout can be passed with `--harness2-source` instead.
These scripts are checkout examples; the packaged MCP entry point does not
run them automatically.

Expected offline results: baseline and hardcoded candidate BLOCK, composed
candidate test PASS, tamper rejection, advisory boundary controls PASS, and
live Julia NOT_RUN. This is a scripted integration control with zero model
calls, not a model coding benchmark or permission to adopt the candidate.

To test your own already-running compatible local Julia service, add
`--julia-url http://127.0.0.1:8011/v1/systemone`. A live disagreement remains a
reported FAIL and never changes CH gates. Do not tune the expected labels to
make a model pass. See [the smoke-test README](../examples/toolchain_pilot/README.md)
for the endpoint contract, artifact locations and exit codes.
