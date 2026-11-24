package main

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"slices"
	"testing"
	"time"

	"github.com/euthm/superretometer/go/internal/graph"
	"github.com/euthm/superretometer/go/internal/service"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

func TestStreamableHTTP(t *testing.T) {
	svc, err := service.Open(service.Options{SnapshotPath: "../../testdata/graph.json"})
	if err != nil {
		t.Fatal(err)
	}
	defer svc.Close()
	handler, err := httpHandler(newServer(svc, false), config{}, "", svc)
	if err != nil {
		t.Fatal(err)
	}
	endpoint := httptest.NewServer(handler)
	defer endpoint.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	client := mcp.NewClient(&mcp.Implementation{Name: "superretometer-test", Version: "1"}, nil)
	session, err := client.Connect(ctx, &mcp.StreamableClientTransport{Endpoint: endpoint.URL + "/mcp"}, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer session.Close()
	tools, err := session.ListTools(ctx, nil)
	if err != nil {
		t.Fatal(err)
	}
	names := make([]string, 0, len(tools.Tools))
	for _, tool := range tools.Tools {
		names = append(names, tool.Name)
	}
	slices.Sort(names)
	if len(names) != 29 {
		t.Fatalf("tools = %v, want 29 complete MCP operations", names)
	}
	for _, want := range []string{"orientation", "check_warrant", "impact_set", "justification_path", "scan_anti_patterns", "open_tensions", "review_required", "propose_ko", "propose_relation", "propose_evidence", "propose_tension", "execute_proposal", "check_simulation_gates", "check_implementation_gates"} {
		if !slices.Contains(names, want) {
			t.Fatalf("missing %s in tools: %v", want, names)
		}
	}

	var orientation graph.Orientation
	callTool(t, ctx, session, "orientation", map[string]string{"scope": "rocom"}, &orientation)
	if orientation.Total != 9 || orientation.Conclusions != 1 || orientation.Canonical != 2 || orientation.ReviewRequired != 1 || orientation.Timestamp.IsZero() {
		t.Fatalf("unexpected orientation: %+v", orientation)
	}
	var warrant graph.Warrant
	callTool(t, ctx, session, "check_warrant", map[string]string{"conclusion_ko_id": "claim"}, &warrant)
	if warrant.Status != "unwarranted" || !slices.Contains(warrant.Assumptions, "Missing premise: missing (not found in storage)") {
		t.Fatalf("unexpected warrant: %+v", warrant)
	}
	callTool(t, ctx, session, "check_warrant", map[string]string{"conclusion_ko_id": "loop-a"}, &warrant)
	if warrant.Status != "unwarranted" || len(warrant.Diagnoses) != 1 ||
		warrant.Diagnoses[0].Pattern != "circular_dependency" || !slices.Equal(warrant.Cycles[0], []string{"loop-a", "loop-b", "loop-a"}) {
		t.Fatalf("unexpected cycle diagnosis: %+v", warrant)
	}
	cases := []struct {
		tool string
		root string
		want []string
	}{
		{"justification_path", "claim", []string{"claim", "model", "missing", "trial", "validator", "source"}},
		{"justification_path", "loop-a", []string{"loop-a", "loop-b"}},
		{"impact_set", "trial", []string{"claim", "consumer"}},
		{"impact_set", "claim", []string{"consumer"}},
		{"impact_set", "source", []string{"model", "claim", "consumer"}},
		{"impact_set", "loop-a", []string{"loop-b", "loop-a"}},
		{"impact_set", "absent", []string{}},
	}
	for _, tc := range cases {
		t.Run(tc.tool+"/"+tc.root, func(t *testing.T) {
			var refs []graph.Reference
			callTool(t, ctx, session, tc.tool, map[string]string{"ko_id": tc.root}, &refs)
			got := make([]string, 0, len(refs))
			for _, ref := range refs {
				got = append(got, ref.ID)
			}
			if refs == nil || !slices.Equal(got, tc.want) {
				t.Fatalf("got %v, want %v", got, tc.want)
			}
		})
	}
}

func callTool(t *testing.T, ctx context.Context, session *mcp.ClientSession, name string, args map[string]string, output any) {
	t.Helper()
	result, err := session.CallTool(ctx, &mcp.CallToolParams{Name: name, Arguments: args})
	if err != nil {
		t.Fatal(err)
	}
	if result.IsError || len(result.Content) != 1 {
		t.Fatalf("unexpected tool result: %+v", result)
	}
	content, ok := result.Content[0].(*mcp.TextContent)
	if !ok {
		t.Fatalf("unexpected content type %T", result.Content[0])
	}
	if err := json.Unmarshal([]byte(content.Text), output); err != nil {
		t.Fatal(err)
	}
}
