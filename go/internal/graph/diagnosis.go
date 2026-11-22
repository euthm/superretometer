package graph

import (
	"fmt"
	"maps"
	"strings"
)

type Diagnosis struct {
	Pattern         string   `json:"pattern"`
	Offending       []string `json:"offending_ko_ids"`
	Path            []string `json:"justification_path"`
	ProvenanceRoots []string `json:"provenance_roots"`
	Condition       string   `json:"violated_condition"`
	MissingEvidence string   `json:"suggested_missing_evidence"`
}

func diagnosis(pattern string, offending, path []string, roots stringSet, condition, hint string) Diagnosis {
	return Diagnosis{
		Pattern: pattern, Offending: offending, Path: append([]string{}, path...),
		ProvenanceRoots: append([]string{}, roots.sorted()...), Condition: condition, MissingEvidence: hint,
	}
}

func (g *Graph) checkFit(o Object, conclusion string) *Diagnosis {
	d := o.Derivation
	train, test := g.datasetLineage(d.Training), g.datasetLineage(d.Test)
	missing := func(path []string, condition, hint string) *Diagnosis {
		result := diagnosis("missing_independent_validation", []string{o.ID}, path, nil, condition, hint)
		return &result
	}
	calibrated := func(ids []string, shared stringSet, condition, hint string) *Diagnosis {
		result := diagnosis("calibrated_to_conclusion", ids, nil, shared, condition, hint)
		return &result
	}
	circular := []string{o.ID, conclusion}
	switch {
	case train.objects[conclusion]:
		result := calibrated(circular, nil, fmt.Sprintf("Training dataset for %s traces back to conclusion %s. Parameter was fitted on data derived from the claim it is supposed to support.", o.ID, conclusion),
			"Fit the parameter on independent observations, not on the conclusion or data derived from it.")
		result.Path = circular
		return result
	case test.objects[conclusion]:
		result := calibrated(circular, nil, fmt.Sprintf("Test dataset for %s traces back to conclusion %s. Validation is circular: the test data is derived from the claim being tested.", o.ID, conclusion),
			"Use a test dataset from independent observations, not derived from the conclusion.")
		result.Path = circular
		return result
	case d.Test == "":
		return missing([]string{o.ID}, "Fitted parameter has no independent test dataset.", "Add a test dataset that is disjoint from the training dataset.")
	case test.objects == nil:
		return missing([]string{o.ID}, "Test dataset not found in storage.", "Register the test dataset.")
	case train.objects == nil:
		return missing([]string{o.ID}, "Training dataset not found in storage.", "Register the training dataset.")
	case len(train.errors)+len(test.errors) > 0 || len(train.roots) == 0 || len(test.roots) == 0:
		var failures []string
		for _, err := range train.errors {
			failures = append(failures, "training: "+err)
		}
		for _, err := range test.errors {
			failures = append(failures, "test: "+err)
		}
		if len(train.roots) == 0 {
			failures = append(failures, "training: no provenance roots")
		}
		if len(test.roots) == 0 {
			failures = append(failures, "test: no provenance roots")
		}
		return missing(nil, "Dataset lineage is incomplete: "+strings.Join(failures, "; ")+". Independence of the train/test split cannot be established.",
			"Give each dataset a source_ko_id (or derived_from_dataset_ids) so its provenance roots can be compared.")
	}
	if shared := train.roots.overlap(test.roots); len(shared) > 0 {
		return calibrated([]string{o.ID}, shared, "Training and test datasets share provenance roots: "+rootLabels(shared)+". Parameter was fitted and tested on overlapping observations.",
			"Use a test dataset with disjoint provenance roots from the training set.")
	}
	return nil
}

func checkValidation(o Object, roots map[string]stringSet) *Diagnosis {
	upstream := o.Derivation.Upstream
	all := make(stringSet)
	for _, id := range upstream {
		maps.Copy(all, roots[id])
	}
	if len(all) == 1 {
		result := diagnosis("tautological_validation", append([]string{o.ID}, upstream...), upstream, all,
			"All validated quantities trace to a single source: "+all.sorted()[0]+". This is an identity check, not an independent measurement.",
			"Include at least one quantity measured or derived from an independent source.")
		return &result
	}
	seen := make(stringSet)
	for i, a := range upstream {
		if seen[a] || len(roots[a]) == 0 {
			continue
		}
		seen[a] = true
		for _, b := range upstream[i+1:] {
			if !seen[b] && maps.Equal(roots[a], roots[b]) {
				result := diagnosis("tautological_validation", []string{o.ID, a, b}, []string{a, b}, roots[a],
					fmt.Sprintf("Quantities %s and %s share identical provenance roots: %s. Comparing them is a tautological check.", a, b, rootLabels(roots[a])),
					"Compare quantities derived from different provenance roots.")
				return &result
			}
		}
	}
	return nil
}

func (g *Graph) checkTransfer(o Object) *Diagnosis {
	d := o.Derivation
	transfer := func(ids []string, condition, hint string) *Diagnosis {
		result := diagnosis("unsupported_transfer", ids, nil, nil, condition, hint)
		return &result
	}
	if d.Mapping == "" {
		ids, source := []string{o.ID}, "unknown"
		if d.DomainSource != "" {
			ids, source = append(ids, d.DomainSource), d.DomainSource
		}
		return transfer(ids, fmt.Sprintf("KO %s was transferred from domain source %s but no domain mapping KO justifies the transfer.", o.ID, source),
			"Create a DomainMapping KO with EQUIVALENT_TO relations connecting source and target domains, including assumptions and invariants.")
	}
	mapping, exists := g.objects[d.Mapping]
	if !exists {
		return transfer([]string{o.ID}, "Domain mapping KO "+d.Mapping+" not found in storage.",
			"Create the referenced DomainMapping KO.")
	}
	if mapping.Derivation == nil || len(mapping.Derivation.Upstream) == 0 {
		return transfer([]string{o.ID, d.Mapping}, "Domain mapping KO "+d.Mapping+" exists but has no upstream evidence.",
			"Add assumptions or invariants to the domain mapping with independent provenance.")
	}
	return nil
}

func (g *Graph) checkPhysicalConstraint(o Object, path []string) *Diagnosis {
	for _, edge := range o.Relations {
		other := g.objects[edge.To]
		if edge.Type == "contradicts" && other.Truth == "conservation_law" {
			result := diagnosis("physically_unrealizable", []string{o.ID, other.ID}, nil, nil,
				fmt.Sprintf("KO %s contradicts conservation law/constraint %s: %s", o.ID, other.ID, other.Title),
				"Correct the model to satisfy the physical constraint.")
			return &result
		}
	}
	for _, id := range path {
		other := g.objects[id]
		if id == o.ID || other.Truth != "conservation_law" {
			continue
		}
		for _, edge := range other.Relations {
			if edge.Type == "contradicts" && edge.To == o.ID {
				result := diagnosis("physically_unrealizable", []string{id, o.ID}, nil, nil,
					fmt.Sprintf("Constraint %s (%s) contradicts %s.", id, other.Title, o.ID),
					"Resolve the contradiction with the physical constraint.")
				return &result
			}
		}
	}
	return nil
}
