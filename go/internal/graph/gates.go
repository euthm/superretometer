package graph

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

// GateResult preserves the three-valued contract: unknown never counts as pass.
type GateResult struct {
	Name     string   `json:"gate"`
	Status   string   `json:"status"`
	Reason   string   `json:"reason"`
	Evidence []string `json:"evidence"`
}

func gate(name, status, reason string, evidence ...string) GateResult {
	return GateResult{name, status, reason, append([]string{}, evidence...)}
}

type SimulationGateReport struct {
	Claim          string     `json:"claim_ko_id"`
	Provenance     GateResult `json:"provenance"`
	Scope          GateResult `json:"scope"`
	Reality        GateResult `json:"reality"`
	Falsifiability GateResult `json:"falsifiability"`
	DesignBearing  bool       `json:"design_bearing"`
	Timestamp      string     `json:"timestamp"`
}

// The reference simulation report's public to_dict omits per-gate evidence;
// implementation reports include it. Keep the two established wire contracts.
func (r SimulationGateReport) MarshalJSON() ([]byte, error) {
	type simulationGate struct {
		Name   string `json:"gate"`
		Status string `json:"status"`
		Reason string `json:"reason"`
	}
	convert := func(g GateResult) simulationGate { return simulationGate{g.Name, g.Status, g.Reason} }
	return json.Marshal(struct {
		Claim          string         `json:"claim_ko_id"`
		Provenance     simulationGate `json:"provenance"`
		Scope          simulationGate `json:"scope"`
		Reality        simulationGate `json:"reality"`
		Falsifiability simulationGate `json:"falsifiability"`
		DesignBearing  bool           `json:"design_bearing"`
		Timestamp      string         `json:"timestamp"`
	}{r.Claim, convert(r.Provenance), convert(r.Scope), convert(r.Reality), convert(r.Falsifiability), r.DesignBearing, r.Timestamp})
}

func allPass(gates ...GateResult) bool {
	for _, result := range gates {
		if result.Status != "pass" {
			return false
		}
	}
	return true
}

func (g *Graph) SimulationGates(id string) SimulationGateReport {
	warrant := g.CheckWarrant(id)
	r := SimulationGateReport{
		Claim: id, Timestamp: time.Now().UTC().Format(time.RFC3339Nano),
		Provenance: g.simulationProvenance(id), Scope: g.simulationScope(id),
		Reality: simulationReality(warrant), Falsifiability: g.simulationFalsifiability(id, warrant.Supporting),
	}
	r.DesignBearing = allPass(r.Provenance, r.Scope, r.Reality, r.Falsifiability)
	return r
}

func (g *Graph) simulationProvenance(id string) GateResult {
	o, exists := g.objects[id]
	if !exists {
		return gate("provenance", "block", "Claim KO not found.")
	}
	p := nestedMap(content(o), "simulation_provenance")
	if p == nil {
		return gate("provenance", "block", "No simulation provenance attached. Cannot trace result to source commit.")
	}
	missing := []string{}
	for _, key := range []string{"result_artifact", "result_sha256", "run_id", "model_id", "source_path", "source_commit"} {
		if stringValue(p, key) == "" {
			missing = append(missing, key)
		}
	}
	if len(missing) > 0 {
		return gate("provenance", "block", "Provenance chain incomplete. Missing: "+strings.Join(missing, ", ")+".")
	}
	broken := []string{}
	for _, link := range [][2]string{{"run_id", "run record"}, {"model_id", "model"}, {"parameter_set_id", "parameter set"}} {
		if ref := stringValue(p, link[0]); ref != "" {
			if _, exists := g.objects[ref]; !exists {
				broken = append(broken, link[1]+" ("+ref+")")
			}
		}
	}
	if len(broken) > 0 {
		return gate("provenance", "block", "Broken provenance links: "+strings.Join(broken, ", ")+".")
	}
	return gate("provenance", "pass", "Complete provenance chain traceable to source commit.", stringValue(p, "result_sha256"), stringValue(p, "source_commit"))
}

func (g *Graph) simulationScope(id string) GateResult {
	o, exists := g.objects[id]
	if !exists {
		return gate("scope", "block", "Claim KO not found.")
	}
	s := nestedMap(content(o), "scope_declaration")
	boundary := stringValue(s, "system_boundary")
	if boundary == "" {
		return gate("scope", "block", "No scope declaration. Cannot verify claim is within model scope.")
	}
	if o.Scope != "" && !scopeCompatible(o.Scope, s) {
		return gate("scope", "block", fmt.Sprintf("Claim scope '%s' exceeds model scope '%s'.", o.Scope, boundary))
	}
	for _, disallowed := range stringList(s, "disallowed_claim_classes") {
		if o.Type == disallowed {
			return gate("scope", "block", fmt.Sprintf("Claim type '%s' is disallowed by model scope.", o.Type))
		}
	}
	return gate("scope", "pass", "Claim within declared scope: "+boundary, boundary)
}

func scopeCompatible(claim string, s map[string]any) bool {
	boundary := stringValue(s, "system_boundary")
	if claim == "" || boundary == "" {
		return false
	}
	if strings.Contains(boundary, claim) {
		return true
	}
	for _, excluded := range stringList(s, "excluded_components") {
		if strings.Contains(claim, excluded) {
			return false
		}
	}
	for _, included := range stringList(s, "included_components") {
		if included == claim {
			return true
		}
	}
	return stringValue(s, "modeled_domain") != "" && stringValue(s, "modeled_domain") == claim
}

func simulationReality(w Warrant) GateResult {
	switch w.Status {
	case "warranted":
		return gate("reality", "pass", "All carrying quantities independently grounded.")
	case "conditionally_warranted":
		return gate("reality", "unknown", "Explicitly assumed, not independently grounded: "+pyStrings(w.Assumptions), w.Assumptions...)
	case "unwarranted":
		patterns, evidence := []string{}, []string{}
		for _, d := range w.Diagnoses {
			patterns = append(patterns, d.Pattern)
			evidence = append(evidence, d.Condition)
		}
		if len(patterns) > 0 {
			return gate("reality", "block", "Structural defects in grounding: "+pyStrings(patterns), evidence...)
		}
		conditions := w.Assumptions
		if len(conditions) == 0 {
			conditions = w.Dependent
		}
		return gate("reality", "block", "Carrying quantities lack independent grounding: "+pyStrings(conditions), w.Assumptions...)
	default:
		return gate("reality", "unknown", "Insufficient graph information for warrant evaluation.")
	}
}

func (g *Graph) simulationFalsifiability(id string, path []string) GateResult {
	o, exists := g.objects[id]
	if !exists {
		return gate("falsifiability", "block", "Claim KO not found.")
	}
	hasFalsifier := false
	for _, pid := range path {
		for _, v := range g.objects[pid].Validators {
			if v.WhatWouldFalsify != "" {
				hasFalsifier = true
				break
			}
		}
		if hasFalsifier {
			break
		}
	}
	if !hasFalsifier {
		return gate("falsifiability", "block", "No falsifiable validators declared. A check that cannot fail cannot increase epistemic confidence.")
	}
	boundary := stringValue(nestedMap(content(o), "scope_declaration"), "system_boundary")
	if boundary != "" {
		issue := ""
		if explicitlyFalse(content(o), "invariant_valid_for_boundary") {
			issue = fmt.Sprintf("KO declares invariant invalid for system boundary '%s'", boundary)
		} else if d := o.Derivation; d != nil {
			for _, upID := range d.Upstream {
				if up, exists := g.objects[upID]; exists && explicitlyFalse(content(up), "invariant_valid_for_boundary") {
					issue = fmt.Sprintf("Upstream KO %s (%s) declares invariant invalid for boundary '%s'", upID, up.Title, boundary)
					break
				}
			}
		}
		if issue != "" {
			return gate("falsifiability", "block", "Invalid invariant for system boundary: "+issue, issue)
		}
	}
	return gate("falsifiability", "pass", "Falsifiable validators declared. Invariants valid for system boundary.")
}

func content(o Object) map[string]any { value, _ := o.Content.(map[string]any); return value }
func nestedMap(m map[string]any, key string) map[string]any {
	value, _ := m[key].(map[string]any)
	return value
}
func stringValue(m map[string]any, key string) string { value, _ := m[key].(string); return value }
func stringList(m map[string]any, key string) []string {
	result := []string{}
	switch values := m[key].(type) {
	case []any:
		for _, value := range values {
			if text, ok := value.(string); ok {
				result = append(result, text)
			}
		}
	case []string:
		result = append(result, values...)
	}
	return result
}
func explicitlyFalse(m map[string]any, key string) bool {
	value, ok := m[key].(bool)
	return ok && !value
}
func pyStrings(values []string) string {
	quoted := make([]string, len(values))
	for i, value := range values {
		quoted[i] = pyQuote(value)
	}
	return "[" + strings.Join(quoted, ", ") + "]"
}
