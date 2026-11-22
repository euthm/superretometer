package graph

import "strings"

type Warrant struct {
	Conclusion     string        `json:"conclusion_ko_id"`
	Status         string        `json:"warrant_status"`
	Supporting     []string      `json:"supporting_kos"`
	Independent    []string      `json:"independent_kos"`
	Dependent      []string      `json:"dependent_kos"`
	Assumptions    []string      `json:"conditional_assumptions"`
	Cycles         [][]string    `json:"cycles"`
	Contradictions []string      `json:"contradicting_kos"`
	Independence   *Independence `json:"independence"`
	Diagnoses      []Diagnosis   `json:"anti_pattern_diagnoses"`
}

type Independence struct {
	EvidenceCount int                 `json:"evidence_count"`
	RootCount     int                 `json:"independent_root_count"`
	RootSets      map[string][]string `json:"root_sets"`
	Shared        map[string][]string `json:"shared_ancestors"`
}

func (g *Graph) CheckWarrant(id string) Warrant {
	w := Warrant{
		Conclusion: id, Status: "unresolved", Supporting: []string{}, Independent: []string{},
		Dependent: []string{}, Assumptions: []string{}, Cycles: [][]string{},
		Contradictions: []string{}, Diagnoses: []Diagnosis{},
	}
	root, exists := g.objects[id]
	if !exists {
		return w
	}

	adjacency := make(map[string][]string)
	for _, ref := range g.walk(id, true, func(id string, enqueue func(string)) {
		neighbors := g.warrantUpstream(id)
		adjacency[id] = neighbors
		for _, neighbor := range neighbors {
			enqueue(neighbor)
		}
	}) {
		w.Supporting = append(w.Supporting, ref.ID)
	}
	w.Cycles = findCycles(w.Supporting, adjacency)

	roots := make(map[string]stringSet, len(w.Supporting))
	for _, premise := range w.Supporting {
		roots[premise] = g.trace([]string{premise}, nil, false).roots
	}
	w.Independence = independence(id, roots)

	var missing []string
	for _, premise := range w.Supporting {
		o, exists := g.objects[premise]
		if !exists {
			w.Dependent = append(w.Dependent, premise)
			missing = append(missing, premise)
			continue
		}
		var defect *Diagnosis
		if d := o.Derivation; d != nil {
			switch d.Type {
			case "fitted":
				defect = g.checkFit(o, id)
			case "validated":
				defect = checkValidation(o, roots)
			case "transferred":
				defect = g.checkTransfer(o)
			}
		}
		if defect != nil {
			w.Diagnoses = append(w.Diagnoses, *defect)
		}
		if premise == id {
			continue
		}
		if g.grounded(o, roots, defect) {
			w.Independent = append(w.Independent, premise)
			continue
		}
		w.Dependent = append(w.Dependent, premise)
		switch o.Truth {
		case "assumption":
			w.Assumptions = append(w.Assumptions, o.ID+": "+o.Title)
		case "documented_decision":
			w.Assumptions = append(w.Assumptions, o.ID+": "+o.Title+" (documented decision, not independent evidence)")
		}
	}
	for _, cycle := range w.Cycles {
		w.Diagnoses = append(w.Diagnoses, diagnosis("circular_dependency", cycle, cycle, nil,
			"Cycle in justification graph: "+strings.Join(cycle, " -> "),
			"Break the cycle by providing at least one independently sourced premise."))
	}
	for _, premise := range w.Supporting {
		if o, exists := g.objects[premise]; exists {
			if defect := g.checkPhysicalConstraint(o, w.Supporting); defect != nil {
				w.Diagnoses = append(w.Diagnoses, *defect)
			}
		}
	}
	for _, edge := range g.incoming[id] {
		if edge.Type == "contradicts" {
			o := g.objects[edge.To]
			pattern := "contradicted"
			if o.Truth == "conservation_law" {
				pattern = "physically_unrealizable"
			}
			w.Contradictions = append(w.Contradictions, o.ID)
			w.Diagnoses = append(w.Diagnoses, diagnosis(pattern, []string{o.ID}, nil, nil,
				"Contradicted by "+o.ID+": "+o.Title, ""))
		}
	}

	if len(w.Supporting) == 1 {
		requiresEvidence := root.Truth == "physical_observation" || root.Truth == "sourced_material_data"
		if root.Provenance == nil || !root.Provenance.Independent || (requiresEvidence && !g.hasEvidence(root)) {
			w.Dependent = append(w.Dependent, id)
		}
	}

	switch {
	case len(w.Diagnoses) > 0 || len(missing) > 0:
		w.Status = "unwarranted"
		for _, premise := range missing {
			w.Assumptions = append(w.Assumptions, "Missing premise: "+premise+" (not found in storage)")
		}
	case len(w.Dependent) > 0:
		w.Status = "conditionally_warranted"
		for _, premise := range w.Dependent {
			switch g.objects[premise].Truth {
			case "assumption", "documented_decision":
			default:
				w.Status = "unwarranted"
			}
		}
	default:
		w.Status = "warranted"
		for _, root := range g.sharedSupportRoots(id, roots) {
			w.Status = "conditionally_warranted"
			w.Assumptions = append(w.Assumptions, "SUPPORTS premises share provenance root: "+root)
		}
	}
	if w.Status == "unwarranted" && len(w.Diagnoses) == 0 && len(w.Assumptions) == 0 {
		for _, premise := range w.Dependent {
			w.Assumptions = append(w.Assumptions, "No independent grounding established for "+premise+": "+g.objects[premise].Title)
		}
	}
	return w
}

func (g *Graph) warrantUpstream(id string) []string {
	o, exists := g.objects[id]
	if !exists {
		return nil
	}
	var next []string
	g.justificationNeighbors(id, func(neighbor string) { next = append(next, neighbor) })
	if o.Derivation != nil {
		next = append(next, o.Derivation.Upstream...)
	}
	return next
}

func findCycles(order []string, adjacency map[string][]string) [][]string {
	type frame struct {
		id   string
		next int
	}
	cycles := [][]string{}
	visited := make(stringSet)
	active := make(map[string]int)
	for _, id := range order {
		if visited[id] {
			continue
		}
		stack := []frame{{id: id}}
		active[id] = 0
		visited[id] = true
		for len(stack) > 0 {
			top := &stack[len(stack)-1]
			neighbors := adjacency[top.id]
			if top.next == len(neighbors) {
				delete(active, top.id)
				stack = stack[:len(stack)-1]
				continue
			}
			next := neighbors[top.next]
			top.next++
			if start, cyclic := active[next]; cyclic {
				cycle := make([]string, 0, len(stack)-start+1)
				for _, node := range stack[start:] {
					cycle = append(cycle, node.id)
				}
				cycles = append(cycles, append(cycle, next))
			} else if !visited[next] {
				visited[next] = true
				active[next] = len(stack)
				stack = append(stack, frame{id: next})
			}
		}
	}
	return cycles
}

func independence(conclusion string, roots map[string]stringSet) *Independence {
	result := &Independence{
		EvidenceCount: len(roots) - 1,
		RootSets:      make(map[string][]string, len(roots)), Shared: make(map[string][]string),
	}
	all := make(stringSet)
	ancestors := make(map[string]stringSet)
	for id, sources := range roots {
		result.RootSets[id] = append([]string{}, sources.sorted()...)
		for source := range sources {
			if id != conclusion {
				all[source] = true
			}
			if ancestors[source] == nil {
				ancestors[source] = make(stringSet)
			}
			ancestors[source][id] = true
		}
	}
	for source, ids := range ancestors {
		if len(ids) > 1 {
			result.Shared[source] = ids.sorted()
		}
	}
	result.RootCount = len(all)
	return result
}

func (g *Graph) sharedSupportRoots(id string, roots map[string]stringSet) []string {
	seen, shared := make(stringSet), make(stringSet)
	for _, edge := range g.incoming[id] {
		if edge.Type != "supports" || edge.To == id {
			continue
		}
		for root := range roots[edge.To] {
			if seen[root] {
				shared[root] = true
			}
			seen[root] = true
		}
	}
	return shared.sorted()
}

func (g *Graph) grounded(o Object, roots map[string]stringSet, defect *Diagnosis) bool {
	if o.Provenance == nil || !o.Provenance.Independent {
		return false
	}
	if o.Truth == "conservation_law" || o.Truth == "mathematical_identity" {
		return true
	}
	d := o.Derivation
	if d != nil {
		switch d.Type {
		case "fitted":
			return defect == nil
		case "transferred":
			return d.Mapping != ""
		}
	}
	switch o.Truth {
	case "physical_observation":
		return g.hasEvidence(o)
	case "sourced_material_data":
		return o.Provenance.Source != "system"
	}
	if d != nil {
		switch d.Type {
		case "validated":
			for i, a := range d.Upstream {
				for _, b := range d.Upstream[i+1:] {
					if len(roots[a]) > 0 && len(roots[b]) > 0 && len(roots[a].overlap(roots[b])) == 0 {
						return true
					}
				}
			}
			return false
		case "modeled":
			return len(d.Upstream) > 0
		}
	}
	return true
}

func (g *Graph) hasEvidence(o Object) bool {
	for _, id := range o.EvidenceIDs {
		if g.evidence[id] {
			return true
		}
	}
	return false
}
