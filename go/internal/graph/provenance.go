package graph

import (
	"fmt"
	"maps"
	"slices"
	"strings"
)

type Provenance struct {
	Source      string  `json:"source"`
	Independent bool    `json:"independent"`
	Author      string  `json:"author,omitempty"`
	Timestamp   string  `json:"timestamp,omitempty"`
	Revision    int     `json:"revision,omitempty"`
	DerivedFrom *string `json:"derived_from,omitempty"`
}

type Derivation struct {
	Type         string   `json:"derivation_type"`
	Upstream     []string `json:"upstream_ko_ids"`
	Training     string   `json:"training_dataset_id"`
	Test         string   `json:"test_dataset_id"`
	DomainSource string   `json:"domain_source_ko_id"`
	Mapping      string   `json:"domain_mapping_ko_id"`
}

type Dataset struct {
	ID      string   `json:"id"`
	Source  string   `json:"source_ko_id"`
	Parents []string `json:"derived_from_dataset_ids"`
}

type stringSet map[string]bool

func (s stringSet) sorted() []string {
	return slices.Sorted(maps.Keys(s))
}

func (s stringSet) overlap(other stringSet) stringSet {
	result := make(stringSet)
	for id := range s {
		if other[id] {
			result[id] = true
		}
	}
	return result
}

type lineage struct {
	objects stringSet
	roots   stringSet
	errors  []string
}

func (g *Graph) trace(objects []string, datasets []Dataset, strict bool) lineage {
	result := lineage{objects: make(stringSet), roots: make(stringSet)}
	seenDatasets := make(stringSet)
	for len(objects) > 0 || len(datasets) > 0 {
		for len(objects) > 0 {
			id := objects[0]
			objects = objects[1:]
			if result.objects[id] {
				continue
			}
			result.objects[id] = true
			o, exists := g.objects[id]
			if !exists {
				if strict {
					result.errors = append(result.errors, fmt.Sprintf("source KO %s not found", pyQuote(id)))
				}
				result.roots[id] = true
				continue
			}
			upstream := false
			if d := o.Derivation; d != nil {
				objects = append(objects, d.Upstream...)
				upstream = len(d.Upstream) > 0
				for _, id := range []string{d.Training, d.Test} {
					if id == "" {
						continue
					}
					ds, exists := g.datasets[id]
					if exists && (strict || ds.Source != "" || len(ds.Parents) > 0) {
						upstream = true
						datasets = append(datasets, ds)
					} else if strict && !exists {
						result.errors = append(result.errors, fmt.Sprintf("dataset %s not found", pyQuote(id)))
					}
				}
			}
			for _, edge := range o.Relations {
				if edge.Type == "derived_from" || edge.Type == "transferred_from" {
					upstream = true
					objects = append(objects, edge.To)
				}
			}
			if upstream {
				continue
			}
			root := id
			if o.Provenance != nil && o.Provenance.Source != "" {
				root = strings.Join(strings.Fields(strings.ToLower(o.Provenance.Source)), " ")
				if strict && root == "" {
					result.errors = append(result.errors, fmt.Sprintf("source KO %s has a blank source label", pyQuote(id)))
				}
			} else if strict {
				result.errors = append(result.errors, fmt.Sprintf("source KO %s has no source label", pyQuote(id)))
			}
			result.roots[root] = true
		}
		for len(datasets) > 0 {
			ds := datasets[0]
			datasets = datasets[1:]
			if seenDatasets[ds.ID] {
				continue
			}
			seenDatasets[ds.ID] = true
			if ds.Source != "" {
				objects = append(objects, ds.Source)
			} else if strict && len(ds.Parents) == 0 {
				result.errors = append(result.errors, fmt.Sprintf("dataset %s has no lineage", pyQuote(ds.ID)))
			}
			for _, parent := range ds.Parents {
				if ancestor, exists := g.datasets[parent]; exists {
					datasets = append(datasets, ancestor)
				} else if strict {
					result.errors = append(result.errors, fmt.Sprintf("parent dataset %s not found", pyQuote(parent)))
				}
			}
		}
	}
	return result
}

func (g *Graph) datasetLineage(id string) lineage {
	if ds, exists := g.datasets[id]; exists {
		return g.trace(nil, []Dataset{ds}, true)
	}
	return lineage{}
}

func pyQuote(value string) string {
	if strings.Contains(value, "'") && !strings.Contains(value, `"`) {
		return fmt.Sprintf("%q", value)
	}
	value = strings.NewReplacer(`\`, `\\`, "'", `\'`, "\n", `\n`, "\r", `\r`, "\t", `\t`).Replace(value)
	return "'" + value + "'"
}

func rootLabels(roots stringSet) string {
	labels := roots.sorted()
	for i, label := range labels {
		labels[i] = pyQuote(label)
	}
	return "{" + strings.Join(labels, ", ") + "}"
}
