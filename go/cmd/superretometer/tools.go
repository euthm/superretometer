package main

type toolDefinition struct {
	Name, Description                 string
	Schema                            map[string]any
	ReadOnly, Destructive, Idempotent bool
}

func schema(properties map[string]any, required ...string) map[string]any {
	s := map[string]any{"type": "object", "properties": properties, "additionalProperties": false}
	if len(required) > 0 {
		s["required"] = required
	}
	return s
}

func textField() map[string]any    { return map[string]any{"type": "string"} }
func stringsField() map[string]any { return map[string]any{"type": "array", "items": textField()} }
func enumField(values ...string) map[string]any {
	return map[string]any{"type": "string", "enum": values}
}

func toolDefinitions() []toolDefinition {
	id := func(key string) map[string]any { return schema(map[string]any{key: textField()}, key) }
	proposal := func(fields map[string]any, required ...string) map[string]any {
		fields["proposer"], fields["rationale"] = textField(), textField()
		return schema(fields, required...)
	}
	koTypes := enumField("requirement", "observation", "hypothesis", "decision", "constraint", "model_result", "specification", "finding", "evidence", "conclusion", "domain_mapping")
	truths := enumField("physical_observation", "sourced_material_data", "conservation_law", "documented_decision", "assumption", "fitted_parameter", "model_derived", "validation_result", "mathematical_identity")
	confidence := enumField("speculative", "low", "medium", "high", "certain")
	status := enumField("proposed", "tentative", "validated", "canonical", "superseded", "invalidated")
	relation := enumField("supports", "contradicts", "refines", "depends_on", "validates", "supersedes", "derived_from", "constrains", "impacts", "fitted_on", "tested_against", "transferred_from", "equivalent_to")
	warrant := schema(map[string]any{"conclusion_ko_id": textField(), "ko_id": textField()})
	warrant["anyOf"] = []any{map[string]any{"required": []string{"conclusion_ko_id"}}, map[string]any{"required": []string{"ko_id"}}}
	defs := []toolDefinition{
		{Name: "orientation", Description: "Return current counts and review status of the knowledge graph", Schema: schema(map[string]any{"scope": textField()}), ReadOnly: true},
		{Name: "check_warrant", Description: "Compute structural warrant, provenance independence, assumptions and contradictions for a conclusion", Schema: warrant, ReadOnly: true},
		{Name: "justification_path", Description: "Follow the direction-aware upstream justification chain", Schema: id("ko_id"), ReadOnly: true},
		{Name: "scan_anti_patterns", Description: "Scan the complete graph for structural epistemic anti-patterns", Schema: schema(map[string]any{}), ReadOnly: true},
		{Name: "open_tensions", Description: "List unresolved tensions and their linked knowledge objects", Schema: schema(map[string]any{}), ReadOnly: true},
		{Name: "review_required", Description: "List full knowledge records marked for review", Schema: schema(map[string]any{}), ReadOnly: true},
		{Name: "impact_set", Description: "Find downstream knowledge objects affected by a change", Schema: id("ko_id"), ReadOnly: true},
		{Name: "propose_ko", Description: "Submit a pending knowledge-object proposal; does not execute or establish independent evidence", Schema: proposal(map[string]any{
			"title": textField(), "ko_type": koTypes, "content": map[string]any{}, "scope": textField(), "truth_category": truths,
			"confidence": confidence, "viewpoints": stringsField(), "assumptions": stringsField(), "valid_from": textField(), "valid_to": textField(),
		}, "title")},
		{Name: "propose_relation", Description: "Submit a pending relation proposal", Schema: proposal(map[string]any{
			"from_ko_id": textField(), "to_ko_id": textField(), "relation_type": relation,
		}, "from_ko_id", "to_ko_id", "relation_type")},
		{Name: "propose_evidence", Description: "Submit evidence for explicit execution; new evidence remains pending, not verified", Schema: proposal(map[string]any{
			"claim_ko_id": textField(), "observation": textField(), "records": map[string]any{"type": "array", "items": map[string]any{}}, "relation_type": enumField("supports", "contradicts"),
		}, "claim_ko_id")},
		{Name: "propose_tension", Description: "Submit a pending tension proposal", Schema: proposal(map[string]any{
			"title": textField(), "description": textField(), "ko_ids": stringsField(), "viewpoints": stringsField(), "priority": enumField("blocker", "high", "medium", "low"),
		}, "title")},
		{Name: "check_simulation_gates", Description: "Evaluate provenance, scope, reality and falsifiability for a simulation claim", Schema: id("ko_id"), ReadOnly: true},
		{Name: "check_implementation_gates", Description: "Evaluate all seven implementation gates; filesystem freshness requires a configured trusted repository root", Schema: id("ko_id"), ReadOnly: true},
		{Name: "get_ko", Description: "Read a knowledge object by stable ID", Schema: id("ko_id"), ReadOnly: true},
		{Name: "search_knowledge", Description: "Search titles and text content in the local graph", Schema: schema(map[string]any{
			"query": textField(), "viewpoint": textField(), "limit": map[string]any{"type": "integer", "minimum": 0, "maximum": 1000},
		}, "query"), ReadOnly: true},
		{Name: "get_evidence", Description: "Read an evidence record, including its status and source records", Schema: id("evidence_id"), ReadOnly: true},
		{Name: "list_evidence_for_ko", Description: "List evidence attached to a knowledge object", Schema: id("ko_id"), ReadOnly: true},
		{Name: "get_proposal", Description: "Inspect a pending, accepted or rejected proposal", Schema: id("proposal_id"), ReadOnly: true},
		{Name: "list_proposals", Description: "List persisted proposals, optionally filtered by state", Schema: schema(map[string]any{
			"state": enumField("pending", "accepted", "rejected", "partially_accepted"),
		}), ReadOnly: true},
		{Name: "execute_proposal", Description: "Explicitly validate and execute one pending proposal; returns its accepted/rejected result. Repeating a completed proposal does not execute it again", Schema: id("proposal_id"), Destructive: true, Idempotent: true},
		{Name: "execute_proposals", Description: "Explicitly validate and execute the supplied proposal IDs; canonical protection and evidence rules apply", Schema: schema(map[string]any{
			"proposal_ids": stringsField(),
		}, "proposal_ids"), Destructive: true, Idempotent: true},
		{Name: "propose_transition", Description: "Propose an epistemic lifecycle transition for deterministic validation", Schema: proposal(map[string]any{
			"ko_id": textField(), "target_status": status,
		}, "ko_id", "target_status")},
		{Name: "propose_promote_canonical", Description: "Propose promotion of a validated object; requires verified evidence and confidence at least medium", Schema: proposal(map[string]any{"ko_id": textField()}, "ko_id")},
		{Name: "propose_supersede", Description: "Propose replacing an object with a successor while preserving identity and history", Schema: proposal(map[string]any{
			"old_ko_id": textField(), "new_ko_id": textField(),
		}, "old_ko_id", "new_ko_id")},
		{Name: "propose_update_ko", Description: "Propose field updates to a non-canonical knowledge object; stable identity cannot change", Schema: proposal(map[string]any{
			"ko_id": textField(), "updates": map[string]any{"type": "object"},
		}, "ko_id", "updates")},
		{Name: "succession_chain", Description: "Read the preserved succession history from oldest to newest", Schema: id("ko_id"), ReadOnly: true},
		{Name: "list_canonical", Description: "List canonical knowledge objects, optionally filtered by scope", Schema: schema(map[string]any{"scope": textField()}), ReadOnly: true},
		{Name: "list_active_by_scope", Description: "List non-terminal knowledge objects whose scope contains the given string", Schema: schema(map[string]any{"scope": textField()}, "scope"), ReadOnly: true},
		{Name: "submit_proposal", Description: "Submit a structured pending proposal using canonical Proposal fields. Execution is a separate explicit operation", Schema: proposal(map[string]any{
			"proposal_type": enumField("create_ko", "update_ko", "transition_status", "create_relation", "create_tension", "create_evidence", "promote_canonical", "supersede"),
			"ko_title":      textField(), "ko_type": koTypes, "ko_content": map[string]any{}, "ko_truth_category": truths,
			"ko_scope": textField(), "ko_assumptions": stringsField(), "ko_viewpoints": stringsField(), "ko_confidence": confidence,
			"ko_valid_from": textField(), "ko_valid_to": textField(), "target_ko_id": textField(), "target_status": status,
			"updates": map[string]any{"type": "object"}, "from_ko_id": textField(), "to_ko_id": textField(), "relation_type": relation,
			"evidence_claim_id": textField(), "evidence_observation": textField(), "evidence_records": map[string]any{"type": "array", "items": map[string]any{}},
			"evidence_relation_type": enumField("supports", "contradicts"), "successor_ko_id": textField(),
			"tension_title": textField(), "tension_description": textField(), "tension_ko_ids": stringsField(), "tension_viewpoints": stringsField(), "tension_priority": enumField("blocker", "high", "medium", "low"),
		}, "proposal_type")},
	}
	return defs
}
