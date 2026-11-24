package graph

// ScanAntiPatterns inspects every object in this complete in-memory snapshot.
// It follows the reference detector's global contract: fitted, validated,
// transferred and conservation-constraint checks apply to all KO types, including
// isolated objects. Cycles are diagnosed in CheckWarrant's justification graph.
// Normally attached evidence is not a self-reference defect (Issue #12).
func (g *Graph) ScanAntiPatterns() []Diagnosis {
	result := []Diagnosis{}
	roots := make(map[string]stringSet, len(g.objects))
	constraints := []string{}
	for _, id := range g.order {
		roots[id] = g.trace([]string{id}, nil, false).roots
		if g.objects[id].Truth == "conservation_law" {
			constraints = append(constraints, id)
		}
	}
	for _, id := range g.order {
		o := g.objects[id]
		var defect *Diagnosis
		if d := o.Derivation; d != nil {
			switch d.Type {
			case "transferred":
				defect = g.checkTransfer(o)
			case "fitted":
				defect = g.checkFit(o, id)
			case "validated":
				// Upstream IDs may reference objects absent from the snapshot.
				// The reference traces those IDs as roots too.
				for _, upstream := range d.Upstream {
					if _, exists := roots[upstream]; !exists {
						roots[upstream] = g.trace([]string{upstream}, nil, false).roots
					}
				}
				defect = checkValidation(o, roots)
			}
		}
		if defect != nil {
			result = append(result, *defect)
		}
		if defect := g.checkPhysicalConstraint(o, constraints); defect != nil {
			result = append(result, *defect)
		}
	}
	return result
}
