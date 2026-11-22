# Superretometer in Go

This initial port uses the Python v0.8.3 reference. It implements
`orientation`, `justification_path`, `impact_set`, and `check_warrant` over an immutable
graph snapshot.

Use Go 1.25 or newer. From this directory:

```sh
go test ./...
go build -buildvcs=false -o /tmp/superretometer-go ./cmd/superretometer
/tmp/superretometer-go -snapshot testdata/graph.json -listen 127.0.0.1:3010
```

Add `http://127.0.0.1:3010/mcp` as a Streamable HTTP MCP server. Omit
`-listen` to run the same tools over stdio. The snapshot format is a JSON
object with an `objects` array. Object and relation field names follow
the Python knowledge-object model. See [the example snapshot](testdata/graph.json).

For `check_warrant`, pass the conclusion ID as `conclusion_ko_id`. Include
provenance, derivation, and evidence references on the relevant objects. Use the
optional top-level `datasets` and `evidence` arrays to supply dataset lineage and
evidence records. Evidence records only need their `id` for warrant evaluation.

The preview serves snapshot reads. Graph-wide anti-pattern scanning, gates,
proposals, and live storage integrations still need to be ported before the
Go implementation can replace the Python runtime.
