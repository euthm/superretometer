package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

func call(t *testing.T, s *Service, name string, args record) any {
	t.Helper()
	v, e := s.Call(context.Background(), name, args)
	if e != nil {
		t.Fatal(e)
	}
	return v
}
func proposal(t *testing.T, s *Service, name string, args record) string {
	t.Helper()
	return call(t, s, name, args).(map[string]any)["proposal_id"].(string)
}
func execution(t *testing.T, s *Service, id string) record {
	t.Helper()
	return call(t, s, "execute_proposal", record{"proposal_id": id}).(map[string]any)
}
func snapshot(t *testing.T, s *Service) record {
	t.Helper()
	b, e := s.Snapshot()
	if e != nil {
		t.Fatal(e)
	}
	r, e := decodeState(b)
	if e != nil {
		t.Fatal(e)
	}
	return r
}
func openTest(t *testing.T, opts Options) *Service {
	t.Helper()
	s, e := Open(opts)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { _ = s.Close() })
	return s
}
func seeded(t *testing.T, state string, statePath string) *Service {
	t.Helper()
	p := filepath.Join(t.TempDir(), "seed.json")
	if e := os.WriteFile(p, []byte(state), 0600); e != nil {
		t.Fatal(e)
	}
	return openTest(t, Options{SnapshotPath: p, StatePath: statePath})
}

func TestProposalSurvivesRestartAndExecutesOnlyOnce(t *testing.T) {
	path := filepath.Join(t.TempDir(), "state.json")
	s := openTest(t, Options{StatePath: path})
	id := proposal(t, s, "propose_ko", record{"title": "A supported decision", "ko_type": "decision", "content": record{"answer": 42}, "proposer": "operator", "viewpoints": []string{"customer", "realization"}})
	if len(records(snapshot(t, s), "objects")) != 0 {
		t.Fatal("submission mutated graph before execution")
	}
	if e := s.Close(); e != nil {
		t.Fatal(e)
	}
	s = openTest(t, Options{StatePath: path})
	p := call(t, s, "get_proposal", record{"proposal_id": id}).(map[string]any)
	if str(p, "state") != "pending" {
		t.Fatalf("pending proposal lost: %v", p)
	}
	r := execution(t, s, id)
	if str(r, "state") != "accepted" || str(r, "created_ko_id") == "" {
		t.Fatal(r)
	}
	koID := str(r, "created_ko_id")
	ko := find(snapshot(t, s), "objects", koID)
	if str(ko, "epistemic_status") != "proposed" || ko["provenance"].(map[string]any)["independent"] != false {
		t.Fatalf("proposal fabricated canonicality or independence: %v", ko)
	}
	if e := s.Close(); e != nil {
		t.Fatal(e)
	}
	s = openTest(t, Options{StatePath: path})
	r = execution(t, s, id)
	if str(r, "created_ko_id") != koID || len(records(snapshot(t, s), "objects")) != 1 {
		t.Fatal("terminal proposal re-executed")
	}
}

func TestAllMutationKindsAndCanonicalPreservation(t *testing.T) {
	s := seeded(t, `{"objects":[{"id":"old","type":"conclusion","title":"Old canonical","epistemic_status":"canonical","confidence":"medium","extra":{"a":1}},{"id":"new","title":"Replacement","epistemic_status":"validated"},{"id":"consumer","title":"Consumer","relations":[{"to":"old","type":"depends_on"}]}]}`, "")
	update := proposal(t, s, "propose_update_ko", record{"ko_id": "old", "updates": record{"title": "overwritten"}})
	if str(execution(t, s, update), "state") != "rejected" {
		t.Fatal("canonical update accepted")
	}
	invalidate := proposal(t, s, "propose_transition", record{"ko_id": "old", "target_status": "invalidated"})
	if str(execution(t, s, invalidate), "state") != "rejected" {
		t.Fatal("canonical invalidation accepted")
	}
	relation := proposal(t, s, "propose_relation", record{"from_ko_id": "new", "to_ko_id": "consumer", "relation_type": "supports"})
	if str(execution(t, s, relation), "state") != "accepted" {
		t.Fatal("valid relation rejected")
	}
	evidence := proposal(t, s, "propose_evidence", record{"claim_ko_id": "new", "observation": "An observation", "records": []string{"source.csv"}})
	r := execution(t, s, evidence)
	if str(r, "created_evidence_id") == "" {
		t.Fatal(r)
	}
	ev := find(snapshot(t, s), "evidence", str(r, "created_evidence_id"))
	if str(ev, "status") != "pending" {
		t.Fatal("new evidence was automatically verified")
	}
	tension := proposal(t, s, "propose_tension", record{"title": "Review replacement", "ko_ids": []string{"new"}})
	r = execution(t, s, tension)
	if str(r, "created_tension_id") == "" {
		t.Fatal("accepted tension not materialized")
	}
	if len(call(t, s, "open_tensions", nil).([]any)) != 1 {
		t.Fatal("tension not discoverable")
	}
	sup := proposal(t, s, "propose_supersede", record{"old_ko_id": "old", "new_ko_id": "new"})
	if str(execution(t, s, sup), "state") != "accepted" {
		t.Fatal("valid supersession rejected")
	}
	state := snapshot(t, s)
	old := find(state, "objects", "old")
	if str(old, "title") != "Old canonical" || old["extra"] == nil || str(old, "epistemic_status") != "superseded" {
		t.Fatal("history was lost", old)
	}
	if !boolean(find(state, "objects", "consumer"), "review_required") {
		t.Fatal("downstream consumer not marked for review")
	}
	chain := call(t, s, "succession_chain", record{"ko_id": "new"}).([]any)
	if len(chain) != 2 || str(chain[0].(map[string]any), "id") != "old" {
		t.Fatal(chain)
	}
}

func TestEvidenceAndStatusValidation(t *testing.T) {
	s := seeded(t, `{"objects":[{"id":"claim","title":"Claim","epistemic_status":"proposed"},{"id":"v","title":"Verified","epistemic_status":"validated","confidence":"high","evidence_ids":["ev"]},{"id":"spec","epistemic_status":"validated","confidence":"speculative","evidence_ids":["ev2"]}],"evidence":[{"id":"ev","claim_id":"v","status":"verified"},{"id":"ev2","claim_id":"spec","status":"verified"}]}`, "")
	p := proposal(t, s, "propose_transition", record{"ko_id": "claim", "target_status": "validated"})
	r := execution(t, s, p)
	if str(r, "state") != "rejected" || str(r, "rejection_reason") != "No verified evidence; cannot validate" {
		t.Fatal(r)
	}
	p = proposal(t, s, "propose_transition", record{"ko_id": "v", "target_status": "canonical"})
	if str(execution(t, s, p), "state") != "accepted" {
		t.Fatal("high confidence incorrectly compared lexically")
	}
	p = proposal(t, s, "propose_transition", record{"ko_id": "spec", "target_status": "canonical"})
	if str(execution(t, s, p), "state") != "rejected" {
		t.Fatal("speculative confidence promoted")
	}
}

// OPENSPEC requires MEDIUM confidence and verified evidence for promotion.
// Exercise all exposed routes so a generic update cannot bypass the rule.
func TestCanonicalPromotionContractAcrossRoutes(t *testing.T) {
	for _, route := range []string{"propose_transition", "propose_promote_canonical", "propose_update_ko"} {
		for _, confidence := range []string{"speculative", "low", "medium", "high", "certain"} {
			for _, verified := range []bool{false, true} {
				t.Run(route+"/"+confidence+"/verified="+fmt.Sprint(verified), func(t *testing.T) {
					seed := record{"objects": []any{record{"id": "claim", "epistemic_status": "validated", "confidence": confidence, "evidence_ids": []any{"ev"}}}, "evidence": []any{}}
					if verified {
						seed["evidence"] = []any{record{"id": "ev", "claim_id": "claim", "status": "verified"}}
					}
					data, _ := json.Marshal(seed)
					s := seeded(t, string(data), "")
					args := record{"ko_id": "claim", "target_status": "canonical", "updates": record{"epistemic_status": "canonical"}}
					p := proposal(t, s, route, args)
					r := execution(t, s, p)
					want := verified && set("medium", "high", "certain")[confidence]
					if (str(r, "state") == "accepted") != want {
						t.Fatalf("promotion contract mismatch: %v", r)
					}
				})
			}
		}
	}
}

func TestCompoundUpdateValidatesResultingStateBeforeMutation(t *testing.T) {
	base := `{"objects":[{"id":"claim","title":"Verified claim","content":{"original":true},"truth_category":"physical_observation","provenance":{"source":"measurement","author":"operator","independent":true},"epistemic_status":"validated","confidence":"high","evidence_ids":["ev"]}],"evidence":[{"id":"ev","claim_id":"claim","status":"verified"}]}`
	for name, updates := range map[string]record{
		"confidence downgrade":                  {"epistemic_status": "canonical", "confidence": "low"},
		"evidence removal":                      {"epistemic_status": "canonical", "evidence_ids": []any{}},
		"multiple fields with downgrade":        {"epistemic_status": "canonical", "confidence": "speculative", "truth_category": "conservation_law", "provenance": record{"source": "changed", "author": "agent", "independent": true}, "content": record{"original": false}},
		"multiple fields with evidence removal": {"epistemic_status": "canonical", "evidence_ids": []any{}, "truth_category": "model_derived", "content": false, "provenance": nil},
		"self succession":                       {"superseded_by_id": "claim"},
		"unmanaged tension link":                {"tension_ids": []any{"unknown"}},
		"unknown relation":                      {"relations": []any{record{"to": "claim", "type": "invented"}}},
		"missing target":                        {"relations": []any{record{"to": "missing", "type": "supports"}}},
	} {
		t.Run(name, func(t *testing.T) {
			s := seeded(t, base, "")
			before, _ := json.Marshal(find(snapshot(t, s), "objects", "claim"))
			p := proposal(t, s, "propose_update_ko", record{"ko_id": "claim", "updates": updates})
			if r := execution(t, s, p); str(r, "state") != "rejected" {
				t.Fatalf("invalid compound update accepted: %v", r)
			}
			after, _ := json.Marshal(find(snapshot(t, s), "objects", "claim"))
			if string(before) != string(after) {
				t.Fatal("rejected update partially mutated object")
			}
		})
	}
	// A candidate that improves confidence is judged using its new value.
	s := seeded(t, strings.Replace(base, `"confidence":"high"`, `"confidence":"low"`, 1), "")
	p := proposal(t, s, "propose_update_ko", record{"ko_id": "claim", "updates": record{"epistemic_status": "canonical", "confidence": "medium"}})
	if str(execution(t, s, p), "state") != "accepted" {
		t.Fatal("valid resulting candidate rejected")
	}
}

func TestMalformedGenericProposalIsRejected(t *testing.T) {
	s := openTest(t, Options{})
	for _, fields := range []record{{"ko_type": 7}, {"ko_type": "invented"}, {"ko_truth_category": "made_up"}, {"ko_confidence": true}, {"ko_viewpoints": []any{3}}, {"evidence_relation_type": "depends_on"}, {"updates": []any{}}} {
		args := record{"proposal_type": "create_ko", "ko_title": "bad"}
		for k, v := range fields {
			args[k] = v
		}
		if _, err := s.Call(context.Background(), "submit_proposal", args); err == nil {
			t.Fatalf("accepted malformed proposal %v", fields)
		}
	}
	if len(records(snapshot(t, s), "proposals")) != 0 {
		t.Fatal("malformed proposal persisted")
	}
}

func TestRepositoryCredentialsAreNotPersisted(t *testing.T) {
	s := openTest(t, Options{})
	_, err := s.Call(context.Background(), "propose_ko", record{"title": "unsafe remote", "content": record{"implementation_provenance": record{"repo_remote_raw": "https://secret@example.org/repo.git"}}})
	if err == nil || strings.Contains(err.Error(), "secret") {
		t.Fatalf("credentials not rejected safely: %v", err)
	}
	if len(records(snapshot(t, s), "proposals")) != 0 {
		t.Fatal("credential-bearing proposal retained")
	}
	_, err = s.Call(context.Background(), "propose_ko", record{"title": "ssh remote", "content": record{"implementation_provenance": record{"repo_remote_sanitized": "ssh://git@example.org/repo.git"}}})
	if err != nil {
		t.Fatal(err)
	}
}

func TestPersistenceFailureRollsBackAndPostCommitFailureStopsService(t *testing.T) {
	path := filepath.Join(t.TempDir(), "state.json")
	s := openTest(t, Options{StatePath: path})
	before, _ := os.ReadFile(path)
	s.write = func(string, []byte) (bool, error) { return false, errors.New("disk full") }
	_, err := s.Call(context.Background(), "propose_ko", record{"title": "must not be saved"})
	if err == nil || !strings.Contains(err.Error(), "no changes committed") {
		t.Fatal(err)
	}
	if len(records(snapshot(t, s), "proposals")) != 0 {
		t.Fatal("failed write mutated memory")
	}
	after, _ := os.ReadFile(path)
	if string(before) != string(after) {
		t.Fatal("failed write mutated disk")
	}
	s.write = func(path string, b []byte) (bool, error) {
		committed, err := atomicWrite(path, b)
		if err != nil {
			return committed, err
		}
		return true, errors.New("directory sync failed")
	}
	if _, err = s.Call(context.Background(), "propose_ko", record{"title": "uncertain outcome"}); err == nil || !strings.Contains(err.Error(), "restart required") {
		t.Fatal(err)
	}
	if _, err = s.Call(context.Background(), "orientation", nil); err == nil {
		t.Fatal("service continued after uncertain commit")
	}
	_ = s.Close()
	s = openTest(t, Options{StatePath: path})
	if len(records(snapshot(t, s), "proposals")) != 1 {
		t.Fatal("committed state not recovered after restart")
	}
}

func TestSingleWriterAndSeedPrecedence(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "state.json")
	s := openTest(t, Options{StatePath: path})
	if other, err := Open(Options{StatePath: path}); err == nil {
		_ = other.Close()
		t.Fatal("second writer acquired state")
	}
	id := proposal(t, s, "propose_ko", record{"title": "retained"})
	execution(t, s, id)
	_ = s.Close()
	s = openTest(t, Options{StatePath: path, SnapshotPath: filepath.Join(dir, "does-not-exist.json")})
	if len(records(snapshot(t, s), "objects")) != 1 {
		t.Fatal("existing state overwritten by seed")
	}
}

func TestOpaqueFieldsAndIntegerPrecisionSurvive(t *testing.T) {
	path := filepath.Join(t.TempDir(), "state.json")
	s := seeded(t, `{"objects":[{"id":"a","title":"Keep me","vendor":{"large":9007199254740993},"content":{"provenance":{"future_field":"kept"}}}],"vendor_meta":{"keep":true}}`, path)
	p := proposal(t, s, "propose_ko", record{"title": "another"})
	execution(t, s, p)
	_ = s.Close()
	s = openTest(t, Options{StatePath: path})
	state := snapshot(t, s)
	if state["vendor_meta"] == nil || find(state, "objects", "a")["vendor"].(map[string]any)["large"] != json.Number("9007199254740993") {
		t.Fatal("opaque metadata or numeric precision lost")
	}
}

func TestBatchIsAtomicForUnknownProposalAndReadsAreCopies(t *testing.T) {
	s := openTest(t, Options{})
	id := proposal(t, s, "propose_ko", record{"title": "pending"})
	if _, err := s.Call(context.Background(), "execute_proposals", record{"proposal_ids": []string{id, "missing"}}); err == nil {
		t.Fatal("missing proposal accepted")
	}
	if len(records(snapshot(t, s), "objects")) != 0 {
		t.Fatal("partial batch applied")
	}
	p := call(t, s, "get_proposal", record{"proposal_id": id}).(map[string]any)
	p["state"] = "accepted"
	if str(call(t, s, "get_proposal", record{"proposal_id": id}).(map[string]any), "state") != "pending" {
		t.Fatal("caller mutated service through read result")
	}
}

func TestConcurrentSubmissionsAndCancellation(t *testing.T) {
	s := openTest(t, Options{})
	var wg sync.WaitGroup
	errorsCh := make(chan error, 24)
	for i := 0; i < 24; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, err := s.Call(context.Background(), "propose_ko", record{"title": "parallel"})
			errorsCh <- err
		}()
	}
	wg.Wait()
	close(errorsCh)
	for err := range errorsCh {
		if err != nil {
			t.Fatal(err)
		}
	}
	if len(records(snapshot(t, s), "proposals")) != 24 {
		t.Fatal("concurrent proposals lost")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := s.Call(ctx, "propose_ko", record{"title": "cancelled"}); !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	if len(records(snapshot(t, s), "proposals")) != 24 {
		t.Fatal("cancelled proposal committed")
	}
}

func TestGenericProposalCannotForgeAcceptedState(t *testing.T) {
	s := openTest(t, Options{})
	id := proposal(t, s, "submit_proposal", record{"proposal_type": "create_ko", "ko_title": "Generic proposal", "id": "forged", "state": "accepted", "created_ko_id": "forged"})
	if id == "forged" {
		t.Fatal("caller chose proposal identity")
	}
	p := call(t, s, "get_proposal", record{"proposal_id": id}).(map[string]any)
	if str(p, "state") != "pending" || str(p, "created_ko_id") != "" {
		t.Fatal("caller forged execution result")
	}
	if str(execution(t, s, id), "state") != "accepted" {
		t.Fatal("valid generic proposal rejected")
	}
}

func TestSelfSupersessionAndMissingObjectsAreRejected(t *testing.T) {
	s := seeded(t, `{"objects":[{"id":"a","epistemic_status":"canonical"}]}`, "")
	id := proposal(t, s, "propose_supersede", record{"old_ko_id": "a", "new_ko_id": "a"})
	if str(execution(t, s, id), "state") != "rejected" {
		t.Fatal("self supersession accepted")
	}
	if _, err := s.Call(context.Background(), "get_ko", record{"ko_id": "missing"}); err == nil {
		t.Fatal("get missing KO did not error")
	}
	if _, err := s.Call(context.Background(), "propose_relation", record{"from_ko_id": "a", "to_ko_id": "b", "relation_type": "invented"}); err == nil {
		t.Fatal("unknown relation enum accepted")
	}
	if str(find(snapshot(t, s), "objects", "a"), "epistemic_status") != "canonical" {
		t.Fatal("rejected mutation changed canonical object")
	}
}

func TestTerminalPredecessorCannotBeSuperseded(t *testing.T) {
	for _, status := range []string{"invalidated", "superseded"} {
		t.Run(status, func(t *testing.T) {
			seed := record{"objects": []any{record{"id": "old", "epistemic_status": status, "content": "preserved historical claim"}, record{"id": "new", "epistemic_status": "proposed"}}}
			data, _ := json.Marshal(seed)
			s := seeded(t, string(data), "")
			before, _ := json.Marshal(records(snapshot(t, s), "objects"))
			p := proposal(t, s, "propose_supersede", record{"old_ko_id": "old", "new_ko_id": "new"})
			if r := execution(t, s, p); str(r, "state") != "rejected" {
				t.Fatal("terminal predecessor rewritten", r)
			}
			after, _ := json.Marshal(records(snapshot(t, s), "objects"))
			if string(before) != string(after) {
				t.Fatal("terminal history changed after rejection")
			}
		})
	}
}

func TestBareSupersededTransitionRequiresSuccessor(t *testing.T) {
	for _, route := range []string{"propose_transition", "propose_update_ko"} {
		t.Run(route, func(t *testing.T) {
			s := seeded(t, `{"objects":[{"id":"old","epistemic_status":"validated","title":"Preserved claim"}]}`, "")
			before, _ := json.Marshal(records(snapshot(t, s), "objects"))
			p := proposal(t, s, route, record{"ko_id": "old", "target_status": "superseded", "updates": record{"epistemic_status": "superseded", "title": "must not change"}})
			r := execution(t, s, p)
			if str(r, "state") != "rejected" || !strings.Contains(str(r, "rejection_reason"), "propose_supersede") {
				t.Fatal("bare supersession did not give actionable rejection", r)
			}
			after, _ := json.Marshal(records(snapshot(t, s), "objects"))
			if string(before) != string(after) {
				t.Fatal("bare status update altered preserved history")
			}
		})
	}
}
