package service

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"time"
)

var koTypes = set("requirement", "observation", "hypothesis", "decision", "constraint", "model_result", "specification", "finding", "evidence", "conclusion", "domain_mapping")
var truths = set("physical_observation", "sourced_material_data", "conservation_law", "documented_decision", "assumption", "fitted_parameter", "model_derived", "validation_result", "mathematical_identity")
var confidences = set("speculative", "low", "medium", "high", "certain")
var relationTypes = set("supports", "contradicts", "refines", "depends_on", "validates", "supersedes", "derived_from", "constrains", "impacts", "fitted_on", "tested_against", "transferred_from", "equivalent_to")
var viewpoints = set("customer", "application", "functional", "conceptual", "realization")
var statuses = set("proposed", "tentative", "validated", "canonical", "superseded", "invalidated")
var transitions = map[string]map[string]bool{
	"proposed":   set("tentative", "validated", "invalidated", "superseded"),
	"tentative":  set("validated", "invalidated", "superseded"),
	"validated":  set("canonical", "superseded", "invalidated"),
	"canonical":  set("superseded"),
	"superseded": {}, "invalidated": {},
}

func set(items ...string) map[string]bool {
	m := map[string]bool{}
	for _, v := range items {
		m[v] = true
	}
	return m
}

func newID() (string, error) {
	b := make([]byte, 16)
	if _, e := rand.Read(b); e != nil {
		return "", e
	}
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	h := hex.EncodeToString(b)
	return h[:8] + "-" + h[8:12] + "-" + h[12:16] + "-" + h[16:20] + "-" + h[20:], nil
}

func makeProposal(name string, args record) (record, error) {
	id, err := newID()
	if err != nil {
		return nil, err
	}
	p := record{"id": id, "type": "", "proposer": str(args, "proposer"), "rationale": str(args, "rationale"), "state": "pending", "rejection_reason": "", "created_ko_id": "", "created_evidence_id": "", "created_tension_id": ""}
	for _, key := range []string{"proposer", "rationale"} {
		if v, ok := args[key]; ok {
			if _, ok = v.(string); !ok {
				return nil, fmt.Errorf("%s must be a string", key)
			}
		}
	}
	require := func(key, target string) error {
		v, e := requiredString(args, key)
		if e == nil {
			p[target] = v
		}
		return e
	}
	switch name {
	case "propose_ko":
		p["type"] = "create_ko"
		if err = require("title", "ko_title"); err != nil {
			return nil, err
		}
		typ := str(args, "ko_type")
		if typ != "" && !koTypes[typ] {
			return nil, fmt.Errorf("invalid ko_type: %s", typ)
		}
		truth := str(args, "truth_category")
		if truth != "" && !truths[truth] {
			return nil, fmt.Errorf("invalid truth_category: %s", truth)
		}
		confidence := defaultString(args, "confidence", "speculative")
		if !confidences[confidence] {
			return nil, fmt.Errorf("invalid confidence: %s", confidence)
		}
		vp, e := stringListArg(args, "viewpoints", false)
		if e != nil {
			return nil, e
		}
		for _, v := range vp {
			if !viewpoints[v] {
				return nil, fmt.Errorf("Not a valid CAFCR viewpoint: %q", v)
			}
		}
		assumptions, e := stringListArg(args, "assumptions", false)
		if e != nil {
			return nil, e
		}
		p["ko_type"] = typ
		p["ko_truth_category"] = truth
		p["ko_content"] = args["content"]
		p["ko_scope"] = str(args, "scope")
		p["ko_confidence"] = confidence
		p["ko_viewpoints"] = anyStrings(vp)
		p["ko_assumptions"] = anyStrings(assumptions)
		p["ko_valid_from"] = args["valid_from"]
		p["ko_valid_to"] = args["valid_to"]
	case "propose_relation":
		p["type"] = "create_relation"
		for _, key := range []string{"from_ko_id", "to_ko_id", "relation_type"} {
			if e := require(key, key); e != nil {
				return nil, e
			}
		}
		if !relationTypes[str(p, "relation_type")] {
			return nil, fmt.Errorf("invalid relation_type: %s", str(p, "relation_type"))
		}
	case "propose_evidence":
		p["type"] = "create_evidence"
		if err = require("claim_ko_id", "evidence_claim_id"); err != nil {
			return nil, err
		}
		p["evidence_observation"] = str(args, "observation")
		rt := defaultString(args, "relation_type", "supports")
		if rt != "supports" && rt != "contradicts" {
			return nil, fmt.Errorf("invalid evidence relation_type: %s", rt)
		}
		p["evidence_relation_type"] = rt
		if r, ok := args["records"]; ok {
			switch r.(type) {
			case []any, []string:
				p["evidence_records"] = r
			default:
				return nil, errors.New("records must be an array")
			}
		} else {
			p["evidence_records"] = []any{}
		}
	case "propose_tension":
		p["type"] = "create_tension"
		if err = require("title", "tension_title"); err != nil {
			return nil, err
		}
		p["tension_description"] = str(args, "description")
		ids, e := stringListArg(args, "ko_ids", false)
		if e != nil {
			return nil, e
		}
		p["tension_ko_ids"] = anyStrings(ids)
		vp, e := stringListArg(args, "viewpoints", false)
		if e != nil {
			return nil, e
		}
		for _, v := range vp {
			if !viewpoints[v] {
				return nil, fmt.Errorf("Not a valid CAFCR viewpoint: %q", v)
			}
		}
		p["tension_viewpoints"] = anyStrings(vp)
		priority := defaultString(args, "priority", "medium")
		if !set("blocker", "high", "medium", "low")[priority] {
			return nil, fmt.Errorf("invalid tension priority: %s", priority)
		}
		p["tension_priority"] = priority
	case "propose_transition":
		p["type"] = "transition_status"
		if err = require("ko_id", "target_ko_id"); err != nil {
			return nil, err
		}
		if err = require("target_status", "target_status"); err != nil {
			return nil, err
		}
		if !statuses[str(p, "target_status")] {
			return nil, fmt.Errorf("invalid target_status: %s", str(p, "target_status"))
		}
	case "propose_promote_canonical":
		p["type"] = "promote_canonical"
		if err = require("ko_id", "target_ko_id"); err != nil {
			return nil, err
		}
	case "propose_supersede":
		p["type"] = "supersede"
		if err = require("old_ko_id", "target_ko_id"); err != nil {
			return nil, err
		}
		if err = require("new_ko_id", "successor_ko_id"); err != nil {
			return nil, err
		}
	case "propose_update_ko":
		p["type"] = "update_ko"
		if err = require("ko_id", "target_ko_id"); err != nil {
			return nil, err
		}
		u, ok := args["updates"].(map[string]any)
		if !ok {
			return nil, errors.New("updates must be an object")
		}
		p["updates"] = u
	default:
		return nil, fmt.Errorf("unknown proposal tool: %s", name)
	}
	return p, nil
}

func reject(p record, reason string) { p["state"] = "rejected"; p["rejection_reason"] = reason }
func accept(p record)                { p["state"] = "accepted"; p["rejection_reason"] = "" }

func execute(state, p record) error {
	if err := validateProposalFields(p); err != nil {
		reject(p, err.Error())
		return nil
	}
	switch str(p, "type") {
	case "create_ko":
		return createKO(state, p)
	case "create_relation":
		from, to, typ := str(p, "from_ko_id"), str(p, "to_ko_id"), str(p, "relation_type")
		if from == "" || to == "" || typ == "" {
			reject(p, "from_ko_id, to_ko_id, and relation_type required")
			return nil
		}
		if !relationTypes[typ] {
			reject(p, "Invalid relation type: "+typ)
			return nil
		}
		ko := find(state, "objects", from)
		if ko == nil || find(state, "objects", to) == nil {
			reject(p, "Relation creation failed (KO not found)")
			return nil
		}
		ko["relations"] = append(list(ko, "relations"), record{"to": to, "type": typ})
		accept(p)
	case "create_evidence":
		return createEvidence(state, p)
	case "create_tension":
		return createTension(state, p)
	case "transition_status":
		ko := find(state, "objects", str(p, "target_ko_id"))
		if ko == nil {
			reject(p, "KO "+str(p, "target_ko_id")+" not found")
			return nil
		}
		if reason := validateTransition(state, ko, str(p, "target_status")); reason != "" {
			reject(p, reason)
			return nil
		}
		ko["epistemic_status"] = str(p, "target_status")
		accept(p)
	case "promote_canonical":
		ko := find(state, "objects", str(p, "target_ko_id"))
		if ko == nil {
			reject(p, "KO "+str(p, "target_ko_id")+" not found")
			return nil
		}
		if str(ko, "epistemic_status") != "validated" {
			reject(p, "Only VALIDATED KOs can be promoted to canonical; current: EpistemicStatus."+enumName(defaultString(ko, "epistemic_status", "proposed")))
			return nil
		}
		if reason := validateTransition(state, ko, "canonical"); reason != "" {
			reject(p, reason)
			return nil
		}
		ko["epistemic_status"] = "canonical"
		accept(p)
	case "update_ko":
		return updateKO(state, p)
	case "supersede":
		return supersede(state, p)
	default:
		reject(p, "Unknown proposal type: "+str(p, "type"))
	}
	return nil
}

func createKO(state, p record) error {
	if str(p, "ko_title") == "" {
		reject(p, "ko_title is required")
		return nil
	}
	typ := defaultString(p, "ko_type", "hypothesis")
	truth := defaultString(p, "ko_truth_category", "assumption")
	confidence := defaultString(p, "ko_confidence", "speculative")
	if !koTypes[typ] || !truths[truth] || !confidences[confidence] {
		reject(p, "Invalid KO type, truth category, or confidence")
		return nil
	}
	for _, v := range list(p, "ko_viewpoints") {
		s, ok := v.(string)
		if !ok || !viewpoints[s] {
			reject(p, fmt.Sprintf("Not a valid CAFCR viewpoint: %v", v))
			return nil
		}
	}
	id, e := newID()
	if e != nil {
		return e
	}
	ko := record{"id": id, "type": typ, "title": str(p, "ko_title"), "content": p["ko_content"], "truth_category": truth, "viewpoint_ids": list(p, "ko_viewpoints"), "provenance": record{"source": "proposal", "author": str(p, "proposer"), "timestamp": time.Now().UTC().Format(time.RFC3339Nano), "revision": 1, "independent": false, "derived_from": nil}, "derivation": nil, "epistemic_status": "proposed", "confidence": confidence, "valid_from": nil, "valid_to": nil, "assumptions": list(p, "ko_assumptions"), "scope": str(p, "ko_scope"), "supersedes_id": nil, "superseded_by_id": nil, "evidence_ids": []any{}, "tension_ids": []any{}, "relations": []any{}, "anti_patterns": []any{}, "validators": []any{}, "review_required": false, "review_reason": ""}
	state["objects"] = append(list(state, "objects"), ko)
	p["created_ko_id"] = id
	accept(p)
	return nil
}

func createEvidence(state, p record) error {
	claim := str(p, "evidence_claim_id")
	if claim == "" {
		reject(p, "evidence_claim_id required")
		return nil
	}
	ko := find(state, "objects", claim)
	if ko == nil {
		reject(p, "Claim KO "+claim+" not found")
		return nil
	}
	rt := defaultString(p, "evidence_relation_type", "supports")
	if rt != "supports" && rt != "contradicts" {
		reject(p, "Invalid evidence relation_type: "+rt)
		return nil
	}
	id, e := newID()
	if e != nil {
		return e
	}
	ev := record{"id": id, "claim_id": claim, "status": "pending", "observation": str(p, "evidence_observation"), "records": list(p, "evidence_records"), "relation_type": rt}
	state["evidence"] = append(list(state, "evidence"), ev)
	ko["evidence_ids"] = append(list(ko, "evidence_ids"), id)
	if rt == "contradicts" {
		state["objects"] = append(list(state, "objects"), record{"id": id, "type": "evidence", "title": "Evidence for " + claim, "content": ev, "truth_category": "assumption", "epistemic_status": "proposed", "provenance": record{"source": "evidence", "author": "system", "timestamp": time.Now().UTC().Format(time.RFC3339Nano), "revision": 1, "independent": nil, "derived_from": nil}, "derivation": nil, "confidence": "speculative", "viewpoint_ids": []any{}, "valid_from": nil, "valid_to": nil, "assumptions": []any{}, "scope": "", "supersedes_id": nil, "superseded_by_id": nil, "evidence_ids": []any{}, "tension_ids": []any{}, "anti_patterns": []any{}, "validators": []any{}, "review_required": false, "review_reason": "", "relations": []any{record{"to": claim, "type": "contradicts"}}})
	}
	p["created_evidence_id"] = id
	accept(p)
	return nil
}

func createTension(state, p record) error {
	if str(p, "tension_title") == "" {
		reject(p, "tension_title required")
		return nil
	}
	id, e := newID()
	if e != nil {
		return e
	}
	t := record{"id": id, "title": str(p, "tension_title"), "description": str(p, "tension_description"), "ko_ids": list(p, "tension_ko_ids"), "viewpoint_ids": list(p, "tension_viewpoints"), "priority": defaultString(p, "tension_priority", "medium"), "status": "open", "thread_ids": []any{}, "resolution_ko_id": ""}
	state["tensions"] = append(list(state, "tensions"), t)
	for _, v := range list(p, "tension_ko_ids") {
		if id, ok := v.(string); ok {
			if ko := find(state, "objects", id); ko != nil {
				ko["tension_ids"] = append(list(ko, "tension_ids"), str(t, "id"))
			}
		}
	}
	p["created_tension_id"] = id
	accept(p)
	return nil
}

func validateTransition(state, ko record, target string) string {
	return validateTransitionFrom(state, ko, defaultString(ko, "epistemic_status", "proposed"), target)
}

func validateTransitionFrom(state, ko record, current, target string) string {
	if target == "" {
		return "target_status is required"
	}
	if target == "superseded" {
		return "Supersession requires a linked successor; use propose_supersede instead of a bare status update"
	}
	if !transitions[current][target] {
		return "Invalid transition: EpistemicStatus." + enumName(current) + " → EpistemicStatus." + enumName(target)
	}
	// Confidence is an ordered enum, not a lexical comparison of its labels.
	if target == "canonical" && !set("medium", "high", "certain")[defaultString(ko, "confidence", "speculative")] {
		return "Cannot promote to canonical with ConfidenceLevel." + enumName(defaultString(ko, "confidence", "speculative")) + " confidence; need >= MEDIUM"
	}
	if target == "validated" || target == "canonical" {
		verified := false
		for _, ev := range records(state, "evidence") {
			if str(ev, "claim_id") == str(ko, "id") && str(ev, "status") == "verified" && contains(list(ko, "evidence_ids"), str(ev, "id")) {
				verified = true
				break
			}
		}
		if !verified {
			return "No verified evidence; cannot validate"
		}
	}
	return ""
}

func updateKO(state, p record) error {
	ko := find(state, "objects", str(p, "target_ko_id"))
	if ko == nil {
		reject(p, "KO "+str(p, "target_ko_id")+" not found")
		return nil
	}
	if str(ko, "epistemic_status") == "canonical" {
		reject(p, "Cannot update canonical KO directly; use SUPERSEDE")
		return nil
	}
	updates, ok := p["updates"].(map[string]any)
	if !ok {
		reject(p, "updates must be an object")
		return nil
	}
	if _, ok := updates["id"]; ok {
		reject(p, "KO identity cannot be updated")
		return nil
	}
	for _, key := range []string{"supersedes_id", "superseded_by_id"} {
		if _, ok := updates[key]; ok {
			reject(p, "Succession links cannot be updated directly; use SUPERSEDE")
			return nil
		}
	}
	if _, ok := updates["tension_ids"]; ok {
		reject(p, "Tension links cannot be updated directly; use a tension proposal")
		return nil
	}
	for key, value := range updates {
		switch key {
		case "type":
			if v, ok := value.(string); !ok || !koTypes[v] {
				reject(p, "Invalid KO type")
				return nil
			}
		case "confidence":
			if v, ok := value.(string); !ok || !confidences[v] {
				reject(p, "Invalid confidence")
				return nil
			}
		case "truth_category":
			if v, ok := value.(string); !ok || !truths[v] {
				reject(p, "Invalid truth category")
				return nil
			}
		}
	}
	allowed := set("type", "title", "content", "truth_category", "viewpoint_ids", "provenance", "derivation", "epistemic_status", "confidence", "valid_from", "valid_to", "assumptions", "scope", "supersedes_id", "superseded_by_id", "evidence_ids", "tension_ids", "relations", "anti_patterns", "validators", "review_required", "review_reason")
	candidate := record{}
	for key, value := range ko {
		candidate[key] = value
	}
	for key, v := range updates {
		if allowed[key] {
			candidate[key] = v
		}
	}
	if values, exists := updates["evidence_ids"]; exists {
		ids, err := stringListArg(record{"evidence_ids": values}, "evidence_ids", true)
		if err != nil {
			reject(p, err.Error())
			return nil
		}
		for _, id := range ids {
			ev := find(state, "evidence", id)
			if ev == nil || str(ev, "claim_id") != str(ko, "id") {
				reject(p, "Evidence IDs must reference evidence for this KO")
				return nil
			}
		}
	}
	if values, exists := updates["relations"]; exists {
		relations, ok := values.([]any)
		if !ok {
			reject(p, "relations must be an array")
			return nil
		}
		for _, value := range relations {
			r, ok := value.(map[string]any)
			if !ok || !relationTypes[str(r, "type")] || find(state, "objects", str(r, "to")) == nil {
				reject(p, "Updated relations require a known relation type and existing target KO")
				return nil
			}
		}
	}
	if target, exists := updates["epistemic_status"]; exists {
		v, ok := target.(string)
		if !ok {
			reject(p, "epistemic_status must be a string")
			return nil
		}
		if reason := validateTransitionFrom(state, candidate, defaultString(ko, "epistemic_status", "proposed"), v); reason != "" {
			reject(p, reason)
			return nil
		}
	}
	// Apply only after every resulting-field invariant has passed.
	for key, v := range candidate {
		ko[key] = v
	}
	accept(p)
	return nil
}

func supersede(state, p record) error {
	oldID, newID := str(p, "target_ko_id"), str(p, "successor_ko_id")
	old, newKO := find(state, "objects", oldID), find(state, "objects", newID)
	if old == nil {
		reject(p, "Target KO "+oldID+" not found")
		return nil
	}
	if newKO == nil {
		reject(p, "Successor KO "+newID+" not found")
		return nil
	}
	current := defaultString(old, "epistemic_status", "proposed")
	if !transitions[current]["superseded"] {
		reject(p, "Invalid transition: EpistemicStatus."+enumName(current)+" → EpistemicStatus.SUPERSEDED")
		return nil
	}
	if oldID == newID {
		reject(p, "A KO cannot supersede itself")
		return nil
	}
	if terminal(str(newKO, "epistemic_status")) {
		reject(p, "Successor KO cannot be terminal")
		return nil
	}
	// Do not create a cycle or overwrite an already established succession.
	if next := str(old, "superseded_by_id"); next != "" && next != newID {
		reject(p, "Target KO already has a successor")
		return nil
	}
	if prev := str(newKO, "supersedes_id"); prev != "" && prev != oldID {
		reject(p, "Successor KO already supersedes another KO")
		return nil
	}
	seen := map[string]bool{}
	for id := newID; id != ""; {
		if id == oldID || seen[id] {
			reject(p, "Supersession would create a cycle")
			return nil
		}
		seen[id] = true
		k := find(state, "objects", id)
		if k == nil {
			break
		}
		id = str(k, "superseded_by_id")
	}
	old["epistemic_status"] = "superseded"
	old["superseded_by_id"] = newID
	newKO["supersedes_id"] = oldID
	newKO["relations"] = append(list(newKO, "relations"), record{"to": oldID, "type": "supersedes"})
	impacted := impactIDs(state, oldID)
	reason := fmt.Sprintf("Superseded KO %s... (%s); successor is %s...", prefix(oldID, 8), prefix(str(old, "title"), 50), prefix(newID, 8))
	for _, id := range impacted {
		if ko := find(state, "objects", id); ko != nil && !terminal(str(ko, "epistemic_status")) && !boolean(ko, "review_required") {
			ko["review_required"] = true
			ko["review_reason"] = reason
		}
	}
	accept(p)
	return nil
}

func impactIDs(state record, id string) []string {
	seen := map[string]bool{}
	out := []string{}
	queue := []string{id}
	add := func(id string) {
		if !seen[id] {
			seen[id] = true
			out = append(out, id)
			queue = append(queue, id)
		}
	}
	for len(queue) > 0 {
		current := queue[0]
		queue = queue[1:]
		for _, ko := range records(state, "objects") {
			for _, v := range list(ko, "relations") {
				r, ok := v.(map[string]any)
				if ok && (str(r, "type") == "depends_on" || str(r, "type") == "derived_from") && str(r, "to") == current {
					add(str(ko, "id"))
				}
			}
		}
		if ko := find(state, "objects", current); ko != nil {
			for _, v := range list(ko, "relations") {
				r, ok := v.(map[string]any)
				if ok && set("supports", "validates", "constrains", "impacts")[str(r, "type")] {
					add(str(r, "to"))
				}
			}
		}
	}
	return out
}
func proposalResult(p record) record {
	return record{"id": str(p, "id"), "type": str(p, "type"), "state": str(p, "state"), "rejection_reason": str(p, "rejection_reason"), "created_ko_id": str(p, "created_ko_id"), "created_evidence_id": str(p, "created_evidence_id"), "created_tension_id": str(p, "created_tension_id")}
}
func prefix(s string, n int) string {
	r := []rune(s)
	if len(r) > n {
		return string(r[:n])
	}
	return s
}
func enumName(s string) string {
	out := []byte(s)
	for i, c := range out {
		if c >= 'a' && c <= 'z' {
			out[i] = c - 'a' + 'A'
		}
	}
	return string(out)
}

// The generic proposal interface accepts the canonical dataclass field names,
// but does not let untyped JSON turn invalid enum values into safe defaults.
func validateProposalFields(p record) error {
	optional := set("ko_type", "ko_truth_category", "target_status", "relation_type", "ko_valid_from", "ko_valid_to")
	for _, key := range []string{"proposer", "rationale", "ko_type", "ko_title", "ko_truth_category", "ko_scope", "ko_confidence", "ko_valid_from", "ko_valid_to", "target_ko_id", "target_status", "from_ko_id", "to_ko_id", "relation_type", "tension_title", "tension_description", "tension_priority", "evidence_claim_id", "evidence_observation", "evidence_relation_type", "successor_ko_id"} {
		if v, exists := p[key]; exists {
			if v == nil && optional[key] {
				continue
			}
			if _, ok := v.(string); !ok {
				return fmt.Errorf("%s must be a string", key)
			}
		}
	}
	for key, values := range map[string]map[string]bool{"ko_type": koTypes, "ko_truth_category": truths, "ko_confidence": confidences, "target_status": statuses, "relation_type": relationTypes, "evidence_relation_type": set("supports", "contradicts"), "tension_priority": set("blocker", "high", "medium", "low")} {
		if v := str(p, key); v != "" && !values[v] {
			return fmt.Errorf("invalid %s: %s", key, v)
		}
	}
	for _, key := range []string{"ko_viewpoints", "ko_assumptions", "tension_ko_ids", "tension_viewpoints"} {
		values, err := stringListArg(p, key, false)
		if err != nil {
			return err
		}
		if key == "ko_viewpoints" || key == "tension_viewpoints" {
			for _, v := range values {
				if !viewpoints[v] {
					return fmt.Errorf("Not a valid CAFCR viewpoint: %q", v)
				}
			}
		}
	}
	if v, ok := p["evidence_records"]; ok {
		switch v.(type) {
		case []any, []string:
		default:
			return errors.New("evidence_records must be an array")
		}
	}
	if v, ok := p["updates"]; ok {
		if _, ok := v.(map[string]any); !ok {
			return errors.New("updates must be an object")
		}
	}
	return nil
}
