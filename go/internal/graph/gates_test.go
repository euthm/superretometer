package graph

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

func testGraph(t *testing.T, snapshot map[string]any) *Graph {
	t.Helper()
	data, err := json.Marshal(snapshot)
	if err != nil {
		t.Fatal(err)
	}
	g, err := Load(bytes.NewReader(data))
	if err != nil {
		t.Fatal(err)
	}
	return g
}

// Fixtures follow tests/conformance/test_simulation_gates.py: source/run links,
// exact scope, independently evidenced observation and a falsifiable validator.
func simulationFixture() map[string]any {
	return map[string]any{"objects": []any{
		map[string]any{"id": "claim", "type": "conclusion", "scope": "component slab", "truth_category": "model_derived",
			"content": map[string]any{
				"simulation_provenance": map[string]any{"result_artifact": "result.csv", "result_sha256": "abc", "run_id": "run", "model_id": "model", "parameter_set_id": "parameters", "source_path": "model.mo", "source_commit": "commit"},
				"scope_declaration":     map[string]any{"system_boundary": "component slab", "modeled_domain": "thermal", "included_components": []string{"substrate"}, "excluded_components": []string{"plant"}},
			},
			"validators": []any{map[string]any{"id": "falsifier", "what_would_falsify": "Error greater than 5%"}}},
		map[string]any{"id": "run"}, map[string]any{"id": "model"}, map[string]any{"id": "parameters"},
		map[string]any{"id": "observation", "title": "Measurement", "truth_category": "physical_observation", "provenance": map[string]any{"source": "lab-A", "independent": true}, "evidence_ids": []string{"record"}, "relations": []any{map[string]any{"to": "claim", "type": "supports"}}},
		map[string]any{"id": "law", "truth_category": "conservation_law", "provenance": map[string]any{"source": "physics", "independent": true}, "relations": []any{map[string]any{"to": "claim", "type": "supports"}}},
	}, "evidence": []any{map[string]any{"id": "record", "claim_id": "observation"}}}
}

func TestSimulationGatesConformance(t *testing.T) {
	cases := []struct {
		name   string
		modify func(map[string]any)
		gate   string
		want   string
	}{
		{"complete", func(map[string]any) {}, "reality", "pass"},
		{"missing provenance", func(c map[string]any) { delete(c["content"].(map[string]any), "simulation_provenance") }, "provenance", "block"},
		{"missing source commit", func(c map[string]any) {
			delete(c["content"].(map[string]any)["simulation_provenance"].(map[string]any), "source_commit")
		}, "provenance", "block"},
		{"broken run link", func(c map[string]any) {
			c["content"].(map[string]any)["simulation_provenance"].(map[string]any)["run_id"] = "absent"
		}, "provenance", "block"},
		{"broader scope", func(c map[string]any) { c["scope"] = "component slab and whole plant" }, "scope", "block"},
		{"disallowed claim class", func(c map[string]any) {
			c["content"].(map[string]any)["scope_declaration"].(map[string]any)["disallowed_claim_classes"] = []string{"conclusion"}
		}, "scope", "block"},
		{"no falsifier", func(c map[string]any) { delete(c, "validators") }, "falsifiability", "block"},
		{"invalid invariant", func(c map[string]any) { c["content"].(map[string]any)["invariant_valid_for_boundary"] = false }, "falsifiability", "block"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			snapshot := simulationFixture()
			tc.modify(snapshot["objects"].([]any)[0].(map[string]any))
			r := testGraph(t, snapshot).SimulationGates("claim")
			gates := map[string]GateResult{"provenance": r.Provenance, "scope": r.Scope, "reality": r.Reality, "falsifiability": r.Falsifiability}
			if got := gates[tc.gate]; got.Status != tc.want {
				t.Fatalf("%s = %+v, want %s", tc.gate, got, tc.want)
			}
			if r.DesignBearing != (tc.name == "complete") {
				t.Fatalf("design_bearing = %v, report %+v", r.DesignBearing, r)
			}
		})
	}
}

func TestSimulationUnknownAndUpstreamFalsification(t *testing.T) {
	snapshot := simulationFixture()
	objects := snapshot["objects"].([]any)
	claim := objects[0].(map[string]any)
	delete(claim, "validators")
	observation := objects[4].(map[string]any)
	observation["truth_category"] = "assumption"
	observation["provenance"] = map[string]any{"source": "assumption", "independent": false}
	observation["validators"] = []any{map[string]any{"what_would_falsify": "Measured heat flow differs by 5%"}}
	g := testGraph(t, snapshot)
	r := g.SimulationGates("claim")
	if r.Reality.Status != "unknown" || r.Falsifiability.Status != "pass" || r.DesignBearing {
		t.Fatalf("conditional evidence must remain unknown: %+v", r)
	}
	missing := g.SimulationGates("absent")
	if missing.Provenance.Status != "block" || missing.Reality.Status != "unknown" || missing.DesignBearing {
		t.Fatalf("missing claim: %+v", missing)
	}
}

func implementationFixture(repo, digest string) map[string]any {
	return map[string]any{"objects": []any{
		map[string]any{"id": "claim", "type": "conclusion", "content": map[string]any{
			"declared_remotes": []string{"https://github.com/example/project.git"},
			"implementation_provenance": map[string]any{
				"repo_remote": "git@github.com:example/project.git", "repo_path": repo, "commit": "abcdef123456", "worktree_clean": true,
				"test_run_id": "run-1", "validator_ko_id": "validator", "test_command": "go test ./...", "test_exit_code": 0,
				"test_result_sha256": strings.Repeat("a", 64), "tested_commit": "abcdef123456", "test_timestamp": "2026-11-24T08:00:00+01:00",
				"blob_paths": []string{"main.go"}, "blob_digest": digest,
			}}, "validators": []any{map[string]any{"id": "falsifier", "what_would_falsify": "A negative test accepts an invalid request"}}},
		map[string]any{"id": "validator", "type": "validation_result"},
	}}
}

func TestImplementationGatesConformance(t *testing.T) {
	repo := t.TempDir()
	code := []byte("package main\n")
	if err := os.WriteFile(filepath.Join(repo, "main.go"), code, 0600); err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(code)
	cases := []struct {
		name   string
		modify func(map[string]any)
		gate   string
		want   string
	}{
		{"complete", func(map[string]any) {}, "freshness", "pass"},
		{"wrong repository", func(p map[string]any) { p["repo_remote"] = "https://github.com/other/project.git" }, "scope", "block"},
		{"conflicting identity", func(p map[string]any) {
			p["repo_remote_sanitized"] = "https://github.com/other/project"
			p["repo_remote_canonical"] = "github.com/example/project"
		}, "provenance", "block"},
		{"missing commit", func(p map[string]any) { delete(p, "commit") }, "provenance", "block"},
		{"dirty unidentified", func(p map[string]any) { p["worktree_clean"] = false }, "worktree", "block"},
		{"dirty identified", func(p map[string]any) {
			p["worktree_clean"] = false
			p["worktree_diff_sha256"] = "diff"
			p["tested_worktree_diff_sha256"] = "diff"
		}, "worktree", "unknown"},
		{"unobserved worktree", func(p map[string]any) { delete(p, "worktree_clean") }, "worktree", "unknown"},
		{"missing validator", func(p map[string]any) { p["validator_ko_id"] = "absent" }, "test", "unknown"},
		{"missing run", func(p map[string]any) { delete(p, "test_run_id") }, "test", "unknown"},
		{"missing command", func(p map[string]any) { delete(p, "test_command") }, "test", "unknown"},
		{"missing result hash", func(p map[string]any) { delete(p, "test_result_sha256") }, "test", "unknown"},
		{"different tested commit", func(p map[string]any) { p["tested_commit"] = "another" }, "test", "block"},
		{"different tested worktree", func(p map[string]any) {
			p["worktree_clean"] = false
			p["worktree_diff_sha256"] = "a"
			p["tested_worktree_diff_sha256"] = "b"
		}, "test", "block"},
		{"failed tests", func(p map[string]any) { p["test_exit_code"] = 1 }, "test", "block"},
		{"unobserved exit", func(p map[string]any) { delete(p, "test_exit_code") }, "test", "unknown"},
		{"naive time", func(p map[string]any) { p["test_timestamp"] = "2026-11-24T08:00:00" }, "test", "unknown"},
		{"invalid time", func(p map[string]any) { p["test_timestamp"] = "yesterday" }, "test", "block"},
		{"missing freshness", func(p map[string]any) { delete(p, "blob_digest") }, "freshness", "unknown"},
		{"changed code", func(p map[string]any) { p["blob_digest"] = "wrong" }, "freshness", "block"},
		{"unobserved dependency", func(p map[string]any) { p["submodule_pins"] = map[string]any{"dep": map[string]any{"commit": "abc"}} }, "dependency", "unknown"},
		{"changed dependency", func(p map[string]any) {
			p["submodule_pins"] = map[string]any{"dep": map[string]any{"commit": "abc"}}
			p["tested_submodule_pins"] = map[string]any{"dep": map[string]any{"commit": "def"}}
		}, "dependency", "block"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			snapshot := implementationFixture(repo, hex.EncodeToString(digest[:]))
			claim := snapshot["objects"].([]any)[0].(map[string]any)
			tc.modify(claim["content"].(map[string]any)["implementation_provenance"].(map[string]any))
			r := testGraph(t, snapshot).WithFreshnessRoots([]string{repo}).ImplementationGates("claim")
			gates := map[string]GateResult{"provenance": r.Provenance, "scope": r.Scope, "worktree": r.Worktree, "test": r.Test, "falsifiability": r.Falsifiability, "dependency": r.Dependency, "freshness": r.Freshness}
			if got := gates[tc.gate]; got.Status != tc.want {
				t.Fatalf("%s = %+v, want %s", tc.gate, got, tc.want)
			}
			if r.DesignBearing != (tc.name == "complete") {
				t.Fatalf("design_bearing = %v: %+v", r.DesignBearing, r)
			}
		})
	}
}

func TestFreshnessRequiresExplicitFilesystemAuthority(t *testing.T) {
	allowed, outside := t.TempDir(), t.TempDir()
	if err := os.WriteFile(filepath.Join(outside, "secret"), []byte("outside-data"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(outside, "secret"), filepath.Join(allowed, "main.go")); err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256([]byte("outside-data"))
	g := testGraph(t, implementationFixture(allowed, hex.EncodeToString(digest[:])))
	if r := g.ImplementationGates("claim"); r.Freshness.Status != "unknown" || r.DesignBearing {
		t.Fatalf("unconfigured access: %+v", r)
	}
	if r := g.WithFreshnessRoots([]string{allowed}).ImplementationGates("claim"); r.Freshness.Status != "unknown" || !strings.Contains(r.Freshness.Reason, "outside repository") {
		t.Fatalf("symlink escape: %+v", r.Freshness)
	}
	g = testGraph(t, implementationFixture(outside, hex.EncodeToString(digest[:])))
	if r := g.WithFreshnessRoots([]string{allowed}).ImplementationGates("claim"); r.Freshness.Status != "unknown" || !strings.Contains(r.Freshness.Reason, "outside configured") {
		t.Fatalf("root escape: %+v", r.Freshness)
	}
}

func TestGlobalScanCoversIsolatedNonConclusions(t *testing.T) {
	g := testGraph(t, map[string]any{"objects": []any{
		map[string]any{"id": "transfer", "type": "requirement", "derivation": map[string]any{"derivation_type": "transferred"}},
		map[string]any{"id": "fit", "type": "requirement", "derivation": map[string]any{"derivation_type": "fitted"}},
		map[string]any{"id": "validation", "type": "requirement", "derivation": map[string]any{"derivation_type": "validated", "upstream_ko_ids": []string{"a", "b"}}},
		map[string]any{"id": "a", "provenance": map[string]any{"source": "same observation"}},
		map[string]any{"id": "b", "provenance": map[string]any{"source": " SAME   observation "}},
		map[string]any{"id": "physical", "type": "requirement"},
		map[string]any{"id": "law", "truth_category": "conservation_law", "relations": []any{map[string]any{"to": "physical", "type": "contradicts"}}},
		map[string]any{"id": "evidenced", "evidence_ids": []string{"record"}},
	}, "evidence": []any{map[string]any{"id": "record", "claim_id": "evidenced"}}})
	patterns := []string{}
	for _, diagnosis := range g.ScanAntiPatterns() {
		patterns = append(patterns, diagnosis.Pattern)
	}
	slices.Sort(patterns)
	want := []string{"missing_independent_validation", "physically_unrealizable", "tautological_validation", "unsupported_transfer"}
	if !slices.Equal(patterns, want) {
		t.Fatalf("global scan patterns = %v, want %v", patterns, want)
	}
}

func TestObjectAccessDoesNotMutateSnapshot(t *testing.T) {
	g := testGraph(t, simulationFixture())
	o, ok := g.GetObject("claim")
	if !ok {
		t.Fatal("claim missing")
	}
	content(o)["scope_declaration"].(map[string]any)["system_boundary"] = "changed"
	o.Validators[0].WhatWouldFalsify = ""
	all := g.Objects()
	all[0].Validators[0].WhatWouldFalsify = ""
	if r := g.SimulationGates("claim"); !r.DesignBearing {
		t.Fatalf("caller mutation escaped defensive copy: %+v", r)
	}
	if _, found := g.GetObject("absent"); found {
		t.Fatal("missing object should not be fabricated")
	}
}

func TestCanonicalRemoteConformance(t *testing.T) {
	for _, remote := range []string{"git@GitHub.com:example/Project.git", "https://secret@GitHub.com/example/Project.git/", "ssh://git@github.com:2222/example/Project.git", "git://github.com/example/Project", "GitHub.com/example/Project"} {
		if got := CanonicalRemote(remote); got != "github.com/example/Project" {
			t.Errorf("CanonicalRemote(%q) = %q", remote, got)
		}
	}
}
