package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/euthm/superretometer/go/internal/service"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

func TestCompatibleCLI(t *testing.T) {
	for _, prefix := range [][]string{nil, {"mcp"}} {
		args := append(append([]string{}, prefix...), "--snapshot", "graph.json", "--state", "state.json", "--repository-root", "/trusted")
		cfg, err := parseConfig(args, io.Discard)
		if err != nil || cfg.Snapshot != "graph.json" || cfg.State != "state.json" || !slices.Equal(cfg.RepositoryRoots, []string{"/trusted"}) {
			t.Fatalf("%v: config=%+v err=%v", args, cfg, err)
		}
	}
	if _, err := parseConfig([]string{"mcp", "unexpected", "--state", "state.json"}, io.Discard); err == nil {
		t.Fatal("positional arguments must not silently hide flags")
	}
	var output bytes.Buffer
	if err := mainContext(context.Background(), []string{"--version"}, &output, io.Discard); err != nil || !strings.Contains(output.String(), version) {
		t.Fatalf("version output: %q, %v", output.String(), err)
	}
}

func TestHTTPStartupBoundaries(t *testing.T) {
	t.Setenv("SUPERRETOMETER_AUTH_TOKEN", "")
	for _, args := range [][]string{
		{"--listen", "0.0.0.0:3010", "--read-only"},
		{"--listen", "127.0.0.1:3010"},
		{"--listen", "not-an-address", "--read-only"},
	} {
		if err := mainContext(context.Background(), args, io.Discard, io.Discard); err == nil {
			t.Fatalf("expected actionable startup error for %v", args)
		}
	}
}

func connectHTTP(t *testing.T, svc *service.Service, readOnly bool) (*mcp.ClientSession, context.Context) {
	t.Helper()
	handler, err := httpHandler(newServer(svc, readOnly), config{ReadOnly: readOnly}, "", svc)
	if err != nil {
		t.Fatal(err)
	}
	endpoint := httptest.NewServer(handler)
	t.Cleanup(endpoint.Close)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	t.Cleanup(cancel)
	client := mcp.NewClient(&mcp.Implementation{Name: "transport-contract", Version: "1"}, nil)
	session, err := client.Connect(ctx, &mcp.StreamableClientTransport{Endpoint: endpoint.URL + "/mcp"}, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = session.Close() })
	return session, ctx
}

func toolJSON(t *testing.T, ctx context.Context, session *mcp.ClientSession, name string, args map[string]any) any {
	t.Helper()
	result, err := session.CallTool(ctx, &mcp.CallToolParams{Name: name, Arguments: args})
	if err != nil {
		t.Fatalf("%s: %v", name, err)
	}
	if result.IsError || len(result.Content) != 1 {
		t.Fatalf("%s: %+v", name, result)
	}
	content, ok := result.Content[0].(*mcp.TextContent)
	if !ok {
		t.Fatalf("%s returned non-text result", name)
	}
	var value any
	if err := json.Unmarshal([]byte(content.Text), &value); err != nil {
		t.Fatal(err)
	}
	return value
}

func TestHTTPProposalLifecycleAndErrors(t *testing.T) {
	state := filepath.Join(t.TempDir(), "state.json")
	svc, err := service.Open(service.Options{StatePath: state})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = svc.Close() })
	session, ctx := connectHTTP(t, svc, false)
	proposal := toolJSON(t, ctx, session, "propose_ko", map[string]any{"title": "A falsifiable claim", "content": false}).(map[string]any)
	pid := proposal["proposal_id"].(string)
	orientation := toolJSON(t, ctx, session, "orientation", nil).(map[string]any)
	if orientation["total_kos"] != float64(0) {
		t.Fatal("submission mutated knowledge graph")
	}
	accepted := toolJSON(t, ctx, session, "execute_proposal", map[string]any{"proposal_id": pid}).(map[string]any)
	if accepted["state"] != "accepted" {
		t.Fatalf("proposal: %v", accepted)
	}
	id := accepted["created_ko_id"].(string)
	ko := toolJSON(t, ctx, session, "get_ko", map[string]any{"ko_id": id}).(map[string]any)
	if ko["content"] != false || ko["epistemic_status"] != "proposed" {
		t.Fatalf("content/status drift: %v", ko)
	}
	again := toolJSON(t, ctx, session, "execute_proposal", map[string]any{"proposal_id": pid}).(map[string]any)
	if again["created_ko_id"] != id {
		t.Fatal("retry created another object")
	}
	for _, request := range []*mcp.CallToolParams{
		{Name: "propose_ko", Arguments: map[string]any{}},
		{Name: "propose_relation", Arguments: map[string]any{"from_ko_id": id, "to_ko_id": id, "relation_type": "invented"}},
		{Name: "get_ko", Arguments: map[string]any{"ko_id": "absent"}},
	} {
		result, err := session.CallTool(ctx, request)
		if err == nil && !result.IsError {
			t.Fatalf("%s error was reported as success: %+v", request.Name, result)
		}
	}
	for _, tool := range []string{"check_simulation_gates", "check_implementation_gates"} {
		report := toolJSON(t, ctx, session, tool, map[string]any{"ko_id": id}).(map[string]any)
		if report["design_bearing"] != false {
			t.Fatalf("ungrounded claim passed %s: %v", tool, report)
		}
	}
}

func TestReadOnlyCatalogAndAuthentication(t *testing.T) {
	svc, err := service.Open(service.Options{})
	if err != nil {
		t.Fatal(err)
	}
	defer svc.Close()
	session, ctx := connectHTTP(t, svc, true)
	catalog, err := session.ListTools(ctx, nil)
	if err != nil {
		t.Fatal(err)
	}
	for _, tool := range catalog.Tools {
		if tool.Annotations == nil || !tool.Annotations.ReadOnlyHint {
			t.Fatalf("write tool in read-only catalog: %s", tool.Name)
		}
	}
	result, err := session.CallTool(ctx, &mcp.CallToolParams{Name: "propose_ko", Arguments: map[string]any{"title": "forbidden"}})
	if err == nil && !result.IsError {
		t.Fatal("read-only server accepted a mutation")
	}
	handler, err := httpHandler(newServer(svc, false), config{}, "test-token", svc)
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		path, token, origin string
		status              int
	}{
		{"/mcp", "", "", http.StatusUnauthorized},
		{"/mcp", "wrong", "", http.StatusUnauthorized},
		{"/mcp", "test-token", "https://untrusted.example", http.StatusForbidden},
		{"/healthz", "", "", http.StatusOK},
	} {
		method := http.MethodPost
		if tc.path == "/healthz" {
			method = http.MethodGet
		}
		req := httptest.NewRequest(method, "http://localhost"+tc.path, strings.NewReader("{}"))
		if tc.token != "" {
			req.Header.Set("Authorization", "Bearer "+tc.token)
		}
		if tc.origin != "" {
			req.Header.Set("Origin", tc.origin)
		}
		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, req)
		if recorder.Code != tc.status {
			t.Fatalf("%s token=%t origin=%s: HTTP %d, want %d", tc.path, tc.token != "", tc.origin, recorder.Code, tc.status)
		}
	}
	for _, method := range []string{http.MethodGet, http.MethodDelete, http.MethodOptions} {
		req := httptest.NewRequest(method, "http://localhost/mcp", nil)
		req.Header.Set("Authorization", "Bearer test-token")
		req.Header.Set("Origin", "https://untrusted.example")
		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, req)
		if recorder.Code != http.StatusForbidden {
			t.Fatalf("%s untrusted Origin reached MCP: HTTP %d", method, recorder.Code)
		}
	}
	_ = svc.Close()
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "http://localhost/healthz", nil))
	if recorder.Code != http.StatusServiceUnavailable {
		t.Fatal("closed state still reports healthy")
	}
}

// A real subprocess runs the actual CLI path, so stdout contamination, the mcp
// alias, EOF handling and lock release are exercised beyond in-process tests.
func TestMCPProcessHelper(t *testing.T) {
	if os.Getenv("SUPERRETOMETER_TEST_HELPER") != "1" {
		return
	}
	index := slices.Index(os.Args, "--")
	if index < 0 {
		os.Exit(2)
	}
	if err := mainContext(context.Background(), os.Args[index+1:], os.Stdout, os.Stderr); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	os.Exit(0)
}

func TestStdioExecutableAndColdRestart(t *testing.T) {
	state := filepath.Join(t.TempDir(), "state.json")
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	var pid string
	for attempt := 0; attempt < 2; attempt++ {
		command := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestMCPProcessHelper$", "--", "mcp", "--state", state)
		command.Env = append(os.Environ(), "SUPERRETOMETER_TEST_HELPER=1")
		var stderr bytes.Buffer
		command.Stderr = &stderr
		client := mcp.NewClient(&mcp.Implementation{Name: "stdio-contract", Version: "1"}, nil)
		session, err := client.Connect(ctx, &mcp.CommandTransport{Command: command}, nil)
		if err != nil {
			t.Fatalf("stdio attempt %d: %v stderr=%s", attempt, err, stderr.String())
		}
		catalog, err := session.ListTools(ctx, nil)
		if err != nil || len(catalog.Tools) != 29 {
			t.Fatalf("stdio catalog: %v %v", catalog, err)
		}
		if attempt == 0 {
			result := toolJSON(t, ctx, session, "propose_ko", map[string]any{"title": "Survives a cold restart"}).(map[string]any)
			pid = result["proposal_id"].(string)
		} else {
			proposal := toolJSON(t, ctx, session, "get_proposal", map[string]any{"proposal_id": pid}).(map[string]any)
			if proposal["state"] != "pending" {
				t.Fatalf("pending proposal lost: %v", proposal)
			}
			result := toolJSON(t, ctx, session, "execute_proposal", map[string]any{"proposal_id": pid}).(map[string]any)
			if result["state"] != "accepted" {
				t.Fatalf("restart execution failed: %v", result)
			}
		}
		if err := session.Close(); err != nil {
			t.Fatalf("stdio shutdown: %v", err)
		}
		if stderr.Len() != 0 {
			t.Fatalf("unexpected stdio log: %s", stderr.String())
		}
	}
}
