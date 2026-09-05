# Security Policy

## Reporting a Vulnerability

Report security issues privately to the repository maintainers through the
[Security Advisories](https://github.com/euthm/superretometer/security/advisories/new) page.

## Scope

Cognitive Harness processes knowledge graphs and computes derived warrant. It does not:
- Handle secrets or credentials
- Make network connections (core package)
- Execute arbitrary code

The MCP server reads from stdin and writes to stdout. Ensure your MCP client validates input.

## What Not to Include

Contributors must **not** include the following in the repository:

- API tokens or keys
- Memory server credentials or project tokens
- Private graph dumps or knowledge exports
- Proprietary engineering data (simulations, parameters, measurements)
- Customer or internal product data
- Local `.env` or `.env.local` files
- SSH keys, certificates, or private keys

The `.gitignore` file already excludes `.env*` patterns. Verify your local
`.gitignore` includes these patterns before committing.

## Examples

All examples in this repository use synthetic, sanitized data. They do not
reference real products, customers, or internal systems.

## Security Model

The structural warrant analysis operates on graph topology, not on the semantic
content of knowledge objects. An attacker who controls the graph can produce
arbitrary warrant results — this is expected and analogous to SQL injection:
the system correctly evaluates the graph it is given. The responsibility for
graph integrity lies with the data producer.
