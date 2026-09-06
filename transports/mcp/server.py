# FILE: transports/mcp/server.py
"""Deprecated compatibility shim.

The MCP server has moved to cognitive_harness.mcp.server.
This shim exists for source compatibility with existing imports.
"""
import warnings

warnings.warn(
    "transports.mcp.server is deprecated. "
    "Use cognitive_harness.mcp.server instead.",
    DeprecationWarning,
    stacklevel=2,
)

from cognitive_harness.mcp.server import MCPServer, main, TOOLS  # noqa: F401

__all__ = ["MCPServer", "main", "TOOLS"]
