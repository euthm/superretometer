# FILE: cognitive-harness/cli.py
"""Superretometer CLI.

Usage:
    superretometer --version
    superretometer --help
    superretometer mcp
"""
from __future__ import annotations
import sys

from cognitive_harness import __version__


def main():
    args = sys.argv[1:]

    if not args or args == ["--help", "-h"] or "-h" in args or "--help" in args:
        _print_help()
        sys.exit(0 if "--help" in args or "-h" in args else 0)

    if args == ["--version"]:
        print(__version__)
        sys.exit(0)

    if args[0] == "mcp":
        from cognitive_harness.mcp.server import MCPServer
        server = MCPServer()
        server.run()
        return

    print(f"Unknown command: {args[0]}", file=sys.stderr)
    _print_help()
    sys.exit(1)


def _print_help():
    print("Usage: superretometer [COMMAND] [OPTIONS]")
    print()
    print("Commands:")
    print("  mcp       Start the MCP server on stdin/stdout")
    print()
    print("Options:")
    print("  --version Print version and exit")
    print("  --help    Show this help message")
    print()
    print("Bare invocation shows this help.")
    print("For the MCP server, run: superretometer mcp")


if __name__ == "__main__":
    main()
