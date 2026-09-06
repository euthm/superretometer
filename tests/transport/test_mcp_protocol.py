# FILE: tests/transport/test_mcp_protocol.py
"""MCP transport regression tests — validate protocol, version consistency, and tool behavior."""
from __future__ import annotations

import json
import sys

import pytest

from cognitive_harness import __version__


class _MCPTester:
    """Directly calls MCP handler methods — no subprocess needed."""

    def __init__(self):
        from cognitive_harness.mcp.server import MCPServer
        self.server = MCPServer()
        self._rid = 1

    def _next_rid(self):
        self._rid += 1
        return self._rid

    def call_tool(self, name, arguments=None):
        rid = self._next_rid()
        args = arguments or {}
        handler = self.server._handle_call({
            "jsonrpc": "2.0", "method": "tools/call", "id": rid,
            "params": {"name": name, "arguments": args},
        })
        # Capture output from _respond — it writes to stdout.
        # Instead, call the handler directly:
        handlers = {
            "orientation": self.server._handle_orientation,
            "check_warrant": self.server._handle_check_warrant,
            "justification_path": self.server._handle_justification_path,
            "scan_anti_patterns": self.server._handle_scan_anti_patterns,
            "open_tensions": self.server._handle_open_tensions,
            "review_required": self.server._handle_review_required,
            "impact_set": self.server._handle_impact_set,
            "propose_ko": self.server._handle_propose_ko,
            "propose_relation": self.server._handle_propose_relation,
            "propose_evidence": self.server._handle_propose_evidence,
            "propose_tension": self.server._handle_propose_tension,
            "propose_thread": self.server._handle_propose_thread,
        }
        handler_fn = handlers.get(name)
        assert handler_fn is not None, f"Unknown tool: {name}"
        try:
            result = handler_fn(args)
            return {"id": rid, "result": result}
        except Exception as e:
            return {"id": rid, "error": {"code": -32603, "message": str(e)}}

    def get_tools(self):
        from cognitive_harness.mcp.server import TOOLS
        return TOOLS


@pytest.fixture
def mcp():
    return _MCPTester()


class TestMCPVersion:
    def test_package_version_not_unknown(self):
        assert __version__ != "0+unknown"

    def test_cli_version_matches_package(self):
        import subprocess
        r = subprocess.run([sys.executable, "-m", "cognitive_harness.cli", "--version"],
                           capture_output=True, text=True)
        assert r.returncode == 0
        assert r.stdout.strip() == __version__


class TestMCPToolSchemas:
    def test_tools_list_has_schemas(self, mcp):
        for tool in mcp.get_tools():
            assert "inputSchema" in tool, f"Missing inputSchema for {tool['name']}"
            assert "type" in tool["inputSchema"]


class TestMCPToolFunctionality:
    def test_orientation(self, mcp):
        r = mcp.call_tool("orientation")
        assert "error" not in r
        assert "total_kos" in r["result"]
        assert "timestamp" in r["result"]

    def test_scan_anti_patterns_empty(self, mcp):
        r = mcp.call_tool("scan_anti_patterns")
        assert "error" not in r
        assert isinstance(r["result"], list)

    def test_open_tensions_empty(self, mcp):
        r = mcp.call_tool("open_tensions")
        assert "error" not in r
        assert isinstance(r["result"], list)

    def test_review_required_empty(self, mcp):
        r = mcp.call_tool("review_required")
        assert "error" not in r

    def test_propose_ko(self, mcp):
        r = mcp.call_tool("propose_ko", {
            "ko_type": "conclusion", "title": "Test claim", "proposer": "test",
        })
        assert "error" not in r, r.get("error")
        assert "proposal_id" in r["result"]

    def test_propose_evidence(self, mcp):
        r = mcp.call_tool("propose_evidence", {
            "claim_ko_id": "some-claim", "observation": "Test ev", "proposer": "test",
        })
        assert "error" not in r, r.get("error")
        assert "proposal_id" in r["result"]

    def test_check_warrant_nonexistent(self, mcp):
        r = mcp.call_tool("check_warrant", {"conclusion_ko_id": "nonexistent"})
        assert "error" not in r
        assert r["result"]["warrant_status"] == "unresolved"

    def test_propose_thread_not_implemented(self, mcp):
        r = mcp.call_tool("propose_thread", {"tension_id": "t1", "question": "Q?"})
        assert r.get("error", {}).get("code") == -32603
        assert "not yet supported" in r["error"]["message"]


class TestNoPrivateAccess:
    def test_no_underscore_kos_in_source(self):
        import inspect
        from cognitive_harness.mcp import server
        source = inspect.getsource(server)
        assert "._kos()" not in source
        assert "._list_tensions()" not in source


class TestMCPVersionConsistency:
    """MCP serverInfo.version matches package version."""

    def test_server_uses_package_version(self, mcp):
        from cognitive_harness.mcp.server import MCPServer
        # The server's initialize handler reads __version__
        # Verify it's not hardcoded
        import inspect
        source = inspect.getsource(MCPServer)
        assert '"0.1.0"' not in source
        assert '"0.6.4"' not in source
        # It should reference __version__
        assert "__version__" in source
