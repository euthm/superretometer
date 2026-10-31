# MCP tool results must be visible to the client

This patch targets Superretometer source f4015e666af0766a78f3ea736f1025d35c06d04c.
It fixes transport encoding, not gate semantics, storage policy or deployment.

## Reproduced defect

Both cognitive_harness.mcp.server and transports/runtime_server.py previously
returned raw domain data directly as the JSON-RPC result for tools/call.
For example, orientation returned result.total_kos, or a proposal call returned
result.proposal_id. Neither contained MCP content blocks. A client that reads
CallToolResult.content can therefore display no tool output even when the
handler computed a response. This reproduces a protocol defect locally; it
does not establish which code is running on AI1 or prove a storage outage.

The declared MCP version is 2024-11-05. Its tools/call result format is documented
at https://modelcontextprotocol.io/specification/2024-11-05/server/tools .

The patch wraps tool replies in content=[{type: text, text: JSON payload}] and
sets isError for the runtime's explicit error replies. Initialize/tools/list
keep their own protocol shapes. Handler return values and CH policies are
unchanged. Empty lists remain JSON [] in text; they are not invisible replies.

## Validation on 31 October 2026

- Python 3.12.3.
- Twelve new serialized-response tests, including a stock stdio subprocess.
- Against the unmodified base: 10 failed, 2 passed (missing content envelopes).
- With the patch: 12 passed.
- Complete tests/: 208 passed, 13 existing warnings, 8 subtests passed, exit 0.
- The full run used HARNESS2_SOURCE pointing to the existing pinned upstream
  1cfe254e8d25b15f37048c3730134686abe60335 checkout. Its example remains scripted
  and uses no model calls. No model service, Memory, Cloudflare or AI1 was called.

Runtime tests replace the optional Memory HTTP adapter with an import fixture
and use InMemoryStorage. They verify visible submit -> execute -> readback ->
ImplementationGatePolicy responses. A hand-written gates table is not adopted
as policy output; absent provenance still produces a real BLOCK. Injected
storage failure is visible as isError rather than an empty success reply.
These tests do not validate Memory persistence, including after restart.

The older transport tests called handlers directly. They did not assert the
serialized response envelope, so they could pass with this protocol defect.

## AI1 verification after review/install

1. Record the active MCP command, Python executable, module location and exact
   source SHA. Package version 0.7.0 alone does not identify the active code.
2. Apply/install the reviewed source in that process's environment. If AI1 runs
   an external copied runtime_server.py, update/review that copy explicitly;
   a package install does not replace the custom launch script.
3. Preserve the live graph using the integration's export mechanism before
   reconnecting only the affected MCP server. Do not restart model/DB services.
4. Inspect initialize and tools/list, then call orientation through the actual
   client. Successful tools/call replies must contain visible text content;
   failures must be explicit rather than inferred from a blank display.
5. On the persistent runtime, submit a small fixture proposal, execute its ID,
   read back the returned KO ID and call check_implementation_gates. Submission
   alone does not create the KO or evaluate any gates. Retain actual receipts.
6. Check the same KO after reconnect using the same project/scope. This is the
   persistence test. InMemoryStorage is intentionally process-local; a Memory
   note is not a persisted CH graph. Preserve the result even if it fails.

Do not seed data or install Ollama merely because a tool displays blank output.
If storage remains unavailable, retain the explicit error and diagnose that
adapter separately. No persistence fix or all-gates-PASS claim is made here.
