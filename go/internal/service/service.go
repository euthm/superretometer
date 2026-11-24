// Package service supplies the public Superretometer consumer boundary.
// All mutations pass through proposals; a committed state is published only
// after its complete JSON document has been persisted successfully.
package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/euthm/superretometer/go/internal/graph"
)

type Options struct {
	SnapshotPath   string
	StatePath      string
	FreshnessRoots []string
}

type record = map[string]any

type Service struct {
	mu       sync.Mutex
	state    record
	graph    *graph.Graph
	opts     Options
	lock     *os.File
	closed   bool
	poisoned error
	// Overridden only by package tests to simulate a failed durable write.
	write func(string, []byte) (bool, error)
}

// Open imports SnapshotPath once if StatePath does not exist. An existing state
// always takes precedence over the seed snapshot. With neither path, the
// service uses an empty in-memory graph, like the Python reference server.
func Open(opts Options) (*Service, error) {
	s := &Service{opts: opts, write: atomicWrite}
	var err error
	if opts.StatePath != "" {
		s.opts.StatePath, err = filepath.Abs(opts.StatePath)
		if err != nil {
			return nil, err
		}
		if err = os.MkdirAll(filepath.Dir(s.opts.StatePath), 0700); err != nil {
			return nil, err
		}
		parent, err := filepath.EvalSymlinks(filepath.Dir(s.opts.StatePath))
		if err != nil {
			return nil, err
		}
		s.opts.StatePath = filepath.Join(parent, filepath.Base(s.opts.StatePath))
		if info, err := os.Lstat(s.opts.StatePath); err == nil && info.Mode()&os.ModeSymlink != 0 {
			return nil, errors.New("state path must be a regular file, not a symbolic link")
		} else if err != nil && !errors.Is(err, os.ErrNotExist) {
			return nil, err
		}
		s.lock, err = acquireLock(s.opts.StatePath + ".lock")
		if err != nil {
			return nil, fmt.Errorf("lock state: %w", err)
		}
	}
	ok := false
	defer func() {
		if !ok {
			_ = s.Close()
		}
	}()
	path := opts.SnapshotPath
	newState := opts.StatePath != ""
	if opts.StatePath != "" {
		_, err := os.Stat(s.opts.StatePath)
		if err == nil {
			path = s.opts.StatePath
			newState = false
		} else if !errors.Is(err, os.ErrNotExist) {
			return nil, err
		}
	}
	if path == "" {
		s.state = record{"format_version": 1, "objects": []any{}, "datasets": []any{}, "evidence": []any{}, "tensions": []any{}, "proposals": []any{}}
	} else {
		data, err := os.ReadFile(path)
		if err != nil {
			return nil, fmt.Errorf("read state/snapshot: %w", err)
		}
		s.state, err = decodeState(data)
		if err != nil {
			return nil, err
		}
	}
	s.graph, err = s.buildGraph(s.state)
	if err != nil {
		return nil, err
	}
	if newState {
		if err := rejectRemoteCredentials(s.state); err != nil {
			return nil, err
		}
		data, err := json.MarshalIndent(s.state, "", "  ")
		if err != nil {
			return nil, err
		}
		if _, err = s.write(s.opts.StatePath, append(data, '\n')); err != nil {
			return nil, err
		}
	}
	ok = true
	return s, nil
}

func decodeState(data []byte) (record, error) {
	d := json.NewDecoder(bytes.NewReader(data))
	d.UseNumber()
	var state record
	if err := d.Decode(&state); err != nil {
		return nil, fmt.Errorf("decode state: %w", err)
	}
	if state == nil {
		return nil, errors.New("state must be a JSON object")
	}
	var extra any
	if err := d.Decode(&extra); err != io.EOF {
		return nil, errors.New("state must contain one JSON document")
	}
	if _, ok := state["objects"].([]any); !ok {
		return nil, errors.New("state requires an objects array")
	}
	if version, exists := state["format_version"]; exists && fmt.Sprint(version) != "1" {
		return nil, fmt.Errorf("unsupported state format_version %v", version)
	}
	for _, key := range []string{"objects", "datasets", "evidence", "tensions", "proposals"} {
		if _, exists := state[key]; !exists {
			state[key] = []any{}
		}
		items, ok := state[key].([]any)
		if !ok {
			return nil, fmt.Errorf("%s must be an array", key)
		}
		seen := map[string]bool{}
		for _, item := range items {
			r, ok := item.(map[string]any)
			if !ok {
				return nil, fmt.Errorf("%s entries must be objects", key)
			}
			id := str(r, "id")
			if id == "" || seen[id] {
				return nil, fmt.Errorf("empty or duplicate %s ID %q", key, id)
			}
			seen[id] = true
		}
	}
	return state, nil
}

func (s *Service) buildGraph(state record) (*graph.Graph, error) {
	data, err := json.Marshal(state)
	if err != nil {
		return nil, err
	}
	g, err := graph.Load(bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	return g.WithFreshnessRoots(s.opts.FreshnessRoots), nil
}

func (s *Service) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		return nil
	}
	s.closed = true
	if s.lock != nil {
		return releaseLock(s.lock)
	}
	return nil
}

// Snapshot returns an independent serialization, including proposals and any
// extension fields that were present in the input snapshot.
func (s *Service) Snapshot() ([]byte, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.available(); err != nil {
		return nil, err
	}
	return json.Marshal(s.state)
}

func (s *Service) available() error {
	if s.closed {
		return errors.New("service is closed")
	}
	if s.poisoned != nil {
		return s.poisoned
	}
	return nil
}

func (s *Service) Call(ctx context.Context, name string, args map[string]any) (any, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.available(); err != nil {
		return nil, err
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if args == nil {
		args = record{}
	}
	originalName := name
	if name == "search_knowledge" {
		name = "query"
	}
	if name == "get_ko" {
		name = "explain"
	}
	if name == "execute_proposal" {
		id, err := requiredString(args, "proposal_id")
		if err != nil {
			return nil, err
		}
		args = record{"proposal_ids": []string{id}}
		name = "execute_proposals"
	}
	switch name {
	case "orientation":
		return s.graph.Orientation(str(args, "scope"), time.Now()), nil
	case "check_warrant":
		if _, ok := args["conclusion_ko_id"]; !ok {
			copy := record{}
			for k, v := range args {
				copy[k] = v
			}
			copy["conclusion_ko_id"] = args["ko_id"]
			args = copy
		}
		id, err := requiredString(args, "conclusion_ko_id")
		if err != nil {
			return nil, err
		}
		return s.graph.CheckWarrant(id), nil
	case "justification_path", "impact_set":
		id, err := requiredString(args, "ko_id")
		if err != nil {
			return nil, err
		}
		if name == "impact_set" {
			return s.graph.ImpactSet(id), nil
		}
		return s.graph.JustificationPath(id), nil
	case "scan_anti_patterns":
		return s.graph.ScanAntiPatterns(), nil
	case "evaluate_simulation_gates", "evaluate_implementation_gates":
		id, err := requiredString(args, "claim_ko_id")
		if err != nil {
			return nil, err
		}
		if name == "evaluate_simulation_gates" {
			return s.graph.SimulationGates(id), nil
		}
		return s.graph.ImplementationGates(id), nil
	case "open_tensions":
		out := []any{}
		for _, t := range records(s.state, "tensions") {
			if str(t, "status") == "resolved" {
				continue
			}
			out = append(out, record{"id": str(t, "id"), "title": str(t, "title"), "description": str(t, "description"), "priority": defaultString(t, "priority", "medium"), "status": defaultString(t, "status", "open"), "ko_ids": list(t, "ko_ids"), "thread_ids": list(t, "thread_ids")})
		}
		return cloneValue(out)
	case "review_required", "list_canonical", "list_active_by_scope", "query":
		out := []any{}
		scope, viewpoint := str(args, "scope"), str(args, "viewpoint")
		query := strings.ToLower(str(args, "topic"))
		if query == "" {
			query = strings.ToLower(str(args, "query"))
		}
		limit := 10
		if v, ok := args["limit"]; ok {
			var err error
			limit, err = intArg(v)
			if err != nil || limit < 0 {
				return nil, errors.New("limit must be a non-negative integer")
			}
		}
		for _, ko := range records(s.state, "objects") {
			include := false
			switch name {
			case "review_required":
				include = boolean(ko, "review_required")
			case "list_canonical":
				include = str(ko, "epistemic_status") == "canonical" && strings.Contains(str(ko, "scope"), scope)
			case "list_active_by_scope":
				include = !terminal(str(ko, "epistemic_status")) && strings.Contains(str(ko, "scope"), scope)
			case "query":
				include = (viewpoint == "" || contains(list(ko, "viewpoint_ids"), viewpoint)) && (strings.Contains(strings.ToLower(str(ko, "title")), query) || strings.Contains(strings.ToLower(str(ko, "content")), query))
			}
			if include && (name != "query" || len(out) < limit) {
				out = append(out, presentKO(ko, name != "review_required"))
			}
		}
		if originalName == "search_knowledge" {
			return cloneValue(record{"results": out, "count": len(out)})
		}
		return cloneValue(out)
	case "explain":
		id, err := requiredString(args, "ko_id")
		if err != nil {
			return nil, err
		}
		ko := find(s.state, "objects", id)
		if ko == nil {
			if originalName == "get_ko" {
				return nil, fmt.Errorf("KO %s not found", id)
			}
			return nil, nil
		}
		return cloneValue(presentKO(ko, false))
	case "succession_chain":
		id, err := requiredString(args, "ko_id")
		if err != nil {
			return nil, err
		}
		return successionChain(s.state, id)
	case "get_proposal":
		id, err := requiredString(args, "proposal_id")
		if err != nil {
			return nil, err
		}
		p := find(s.state, "proposals", id)
		if p == nil {
			return nil, fmt.Errorf("Proposal %s not found", id)
		}
		return cloneValue(p)
	case "get_evidence":
		id, err := requiredString(args, "evidence_id")
		if err != nil {
			return nil, err
		}
		ev := find(s.state, "evidence", id)
		if ev == nil {
			return nil, fmt.Errorf("Evidence %s not found", id)
		}
		return cloneValue(ev)
	case "list_evidence_for_ko":
		id, err := requiredString(args, "ko_id")
		if err != nil {
			return nil, err
		}
		out := []any{}
		for _, ev := range records(s.state, "evidence") {
			if str(ev, "claim_id") == id {
				out = append(out, ev)
			}
		}
		return cloneValue(out)
	case "list_proposals":
		out := []any{}
		for _, p := range records(s.state, "proposals") {
			if state := str(args, "state"); state == "" || state == str(p, "state") {
				out = append(out, p)
			}
		}
		return cloneValue(out)
	case "submit_proposal":
		typ, err := requiredString(args, "proposal_type")
		if err != nil {
			return nil, err
		}
		if !set("create_ko", "update_ko", "transition_status", "create_relation", "create_tension", "create_evidence", "promote_canonical", "supersede")[typ] {
			return nil, fmt.Errorf("invalid proposal_type: %s", typ)
		}
		p := record{}
		for k, v := range args {
			if k != "proposal_type" {
				p[k] = v
			}
		}
		id, err := newID()
		if err != nil {
			return nil, err
		}
		p["id"] = id
		p["type"] = typ
		p["state"] = "pending"
		p["rejection_reason"] = ""
		p["created_ko_id"] = ""
		p["created_evidence_id"] = ""
		p["created_tension_id"] = ""
		if err := validateProposalFields(p); err != nil {
			return nil, err
		}
		return s.change(ctx, func(next record) (any, error) {
			next["proposals"] = append(list(next, "proposals"), p)
			return record{"proposal_id": id}, nil
		})
	case "propose_ko", "propose_relation", "propose_evidence", "propose_tension", "propose_transition", "propose_promote_canonical", "propose_supersede", "propose_update_ko":
		p, err := makeProposal(name, args)
		if err != nil {
			return nil, err
		}
		return s.change(ctx, func(next record) (any, error) {
			next["proposals"] = append(list(next, "proposals"), p)
			return record{"proposal_id": str(p, "id")}, nil
		})
	case "execute_proposals":
		ids, err := stringListArg(args, "proposal_ids", true)
		if err != nil {
			return nil, err
		}
		return s.change(ctx, func(next record) (any, error) {
			for _, id := range ids {
				if find(next, "proposals", id) == nil {
					return nil, fmt.Errorf("Proposal %s not found", id)
				}
			}
			out := []any{}
			for _, id := range ids {
				p := find(next, "proposals", id)
				if defaultString(p, "state", "pending") == "pending" {
					if err := execute(next, p); err != nil {
						return nil, err
					}
				}
				out = append(out, proposalResult(p))
			}
			if originalName == "execute_proposal" {
				return out[0], nil
			}
			return out, nil
		})
	default:
		return nil, fmt.Errorf("unknown tool: %s", name)
	}
}

func (s *Service) change(ctx context.Context, f func(record) (any, error)) (any, error) {
	data, err := json.Marshal(s.state)
	if err != nil {
		return nil, err
	}
	next, err := decodeState(data)
	if err != nil {
		return nil, err
	}
	result, err := f(next)
	if err != nil {
		return nil, err
	}
	if err := rejectRemoteCredentials(next); err != nil {
		return nil, err
	}
	g, err := s.buildGraph(next)
	if err != nil {
		return nil, err
	}
	if err = ctx.Err(); err != nil {
		return nil, err
	}
	if s.opts.StatePath != "" {
		data, err = json.MarshalIndent(next, "", "  ")
		if err != nil {
			return nil, err
		}
		committed, err := s.write(s.opts.StatePath, append(data, '\n'))
		if err != nil {
			if committed {
				s.poisoned = fmt.Errorf("state replacement completed but durability could not be confirmed; restart required: %w", err)
				return nil, s.poisoned
			}
			return nil, fmt.Errorf("state write failed; no changes committed: %w", err)
		}
	}
	s.state, s.graph = next, g
	return cloneValue(result)
}

func atomicWrite(path string, data []byte) (committed bool, err error) {
	dir := filepath.Dir(path)
	f, err := os.CreateTemp(dir, ".superretometer-state-*")
	if err != nil {
		return false, err
	}
	name := f.Name()
	defer func() { _ = f.Close(); _ = os.Remove(name) }()
	if err = f.Chmod(0600); err != nil {
		return false, err
	}
	if _, err = f.Write(data); err != nil {
		return false, err
	}
	if err = f.Sync(); err != nil {
		return false, err
	}
	if err = f.Close(); err != nil {
		return false, err
	}
	if err = os.Rename(name, path); err != nil {
		return false, err
	}
	if err = syncDirectory(dir); err != nil {
		return true, err
	}
	return true, nil
}

func records(state record, key string) []record {
	out := []record{}
	for _, v := range list(state, key) {
		if r, ok := v.(map[string]any); ok {
			out = append(out, r)
		}
	}
	return out
}
func find(state record, key, id string) record {
	for _, r := range records(state, key) {
		if str(r, "id") == id {
			return r
		}
	}
	return nil
}
func str(r record, key string) string { v, _ := r[key].(string); return v }
func defaultString(r record, key, def string) string {
	v := str(r, key)
	if v == "" {
		return def
	}
	return v
}
func boolean(r record, key string) bool { v, _ := r[key].(bool); return v }
func list(r record, key string) []any {
	v, _ := r[key].([]any)
	if v == nil {
		return []any{}
	}
	return v
}
func contains(a []any, s string) bool {
	for _, v := range a {
		if v == s {
			return true
		}
	}
	return false
}
func terminal(s string) bool { return s == "superseded" || s == "invalidated" }
func cloneValue(v any) (any, error) {
	b, e := json.Marshal(v)
	if e != nil {
		return nil, e
	}
	d := json.NewDecoder(bytes.NewReader(b))
	d.UseNumber()
	var o any
	e = d.Decode(&o)
	return o, e
}
func requiredString(args record, key string) (string, error) {
	v, ok := args[key].(string)
	if !ok {
		return "", fmt.Errorf("%s must be a string", key)
	}
	return v, nil
}
func intArg(v any) (int, error) {
	switch n := v.(type) {
	case int:
		return n, nil
	case json.Number:
		i, e := n.Int64()
		return int(i), e
	case float64:
		if n == float64(int(n)) {
			return int(n), nil
		}
	}
	return 0, errors.New("not an integer")
}
func stringListArg(args record, key string, required bool) ([]string, error) {
	v, ok := args[key]
	if !ok {
		if required {
			return nil, fmt.Errorf("%s is required", key)
		}
		return []string{}, nil
	}
	if a, ok := v.([]string); ok {
		return a, nil
	}
	a, ok := v.([]any)
	if !ok {
		return nil, fmt.Errorf("%s must be an array of strings", key)
	}
	out := []string{}
	for _, x := range a {
		s, ok := x.(string)
		if !ok {
			return nil, fmt.Errorf("%s must be an array of strings", key)
		}
		out = append(out, s)
	}
	return out, nil
}
func anyStrings(a []string) []any {
	out := make([]any, len(a))
	for i, s := range a {
		out[i] = s
	}
	return out
}

func presentKO(ko record, summary bool) record {
	p, _ := ko["provenance"].(map[string]any)
	provenance := record{"source": "unknown", "author": "unknown", "timestamp": nil, "revision": 0}
	if p != nil {
		provenance = record{"source": defaultString(p, "source", "system"), "author": defaultString(p, "author", "unknown"), "timestamp": p["timestamp"], "revision": p["revision"]}
		if provenance["revision"] == nil {
			provenance["revision"] = 0
		}
	}
	r := record{"id": str(ko, "id"), "type": defaultString(ko, "type", "requirement"), "title": str(ko, "title"), "epistemic_status": defaultString(ko, "epistemic_status", "proposed"), "confidence": defaultString(ko, "confidence", "speculative"), "viewpoints": list(ko, "viewpoint_ids"), "scope": str(ko, "scope"), "assumptions": list(ko, "assumptions"), "valid_from": ko["valid_from"], "valid_to": ko["valid_to"], "supersedes_id": ko["supersedes_id"], "superseded_by_id": ko["superseded_by_id"], "provenance": provenance, "evidence_count": len(list(ko, "evidence_ids")), "truth_category": defaultString(ko, "truth_category", "assumption"), "anti_patterns": list(ko, "anti_patterns")}
	if !summary {
		r["content"] = ko["content"]
		r["relations"] = list(ko, "relations")
		r["tensions"] = list(ko, "tension_ids")
		r["review_required"] = boolean(ko, "review_required")
		r["review_reason"] = str(ko, "review_reason")
		validators := []any{}
		for _, v := range list(ko, "validators") {
			if x, ok := v.(map[string]any); ok {
				validators = append(validators, record{"id": str(x, "id"), "description": str(x, "description"), "what_would_falsify": str(x, "what_would_falsify"), "passes": x["passes"], "observation": str(x, "observation")})
			}
		}
		r["validators"] = validators
	}
	return r
}

func successionChain(state record, id string) (any, error) {
	seen := map[string]bool{}
	chain := []record{}
	for id != "" {
		if seen[id] {
			return nil, errors.New("cycle in succession chain")
		}
		seen[id] = true
		ko := find(state, "objects", id)
		if ko == nil {
			break
		}
		chain = append(chain, ko)
		id = str(ko, "supersedes_id")
	}
	for i, j := 0, len(chain)-1; i < j; i, j = i+1, j-1 {
		chain[i], chain[j] = chain[j], chain[i]
	}
	if len(chain) > 0 {
		id = str(chain[len(chain)-1], "superseded_by_id")
		for id != "" {
			if seen[id] {
				return nil, errors.New("cycle in succession chain")
			}
			seen[id] = true
			ko := find(state, "objects", id)
			if ko == nil {
				break
			}
			chain = append(chain, ko)
			id = str(ko, "superseded_by_id")
		}
	}
	out := []any{}
	for _, ko := range chain {
		out = append(out, presentKO(ko, true))
	}
	return cloneValue(out)
}

// Repository provenance may be durable audit data. Reject embedded credentials
// instead of silently rewriting a caller's graph or persisting access tokens.
// Other extension metadata is left untouched.
func rejectRemoteCredentials(value any) error {
	switch v := value.(type) {
	case map[string]any:
		for key, child := range v {
			if key == "repo_remote" || key == "repo_remote_raw" || key == "repo_remote_sanitized" {
				if remote, ok := child.(string); ok {
					u, err := url.Parse(remote)
					if err == nil && u.User != nil {
						_, password := u.User.Password()
						if password || u.Scheme == "http" || u.Scheme == "https" {
							return fmt.Errorf("%s contains embedded credentials; provide a credential-free repository URL", key)
						}
					}
				}
			}
			if err := rejectRemoteCredentials(child); err != nil {
				return err
			}
		}
	case []any:
		for _, child := range v {
			if err := rejectRemoteCredentials(child); err != nil {
				return err
			}
		}
	}
	return nil
}
