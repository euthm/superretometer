# Security Policy

## Reporting a Vulnerability

Report security issues privately to the repository maintainers.

## Scope

Cognitive Harness processes knowledge graphs and computes derived warrant. It does not:
- Handle secrets or credentials
- Make network connections (core package)
- Execute arbitrary code

The MCP server reads from stdin and writes to stdout. Ensure your MCP client validates input.
