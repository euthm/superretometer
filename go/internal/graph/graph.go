package graph

import (
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"time"
)

// Object contains the knowledge-object fields used by the graph reads.
type Object struct {
	ID             string      `json:"id"`
	Title          string      `json:"title"`
	Type           string      `json:"type"`
	Scope          string      `json:"scope"`
	Status         string      `json:"epistemic_status"`
	ReviewRequired bool        `json:"review_required"`
	Truth          string      `json:"truth_category"`
	Provenance     *Provenance `json:"provenance"`
	Derivation     *Derivation `json:"derivation"`
	EvidenceIDs    []string    `json:"evidence_ids"`
	Relations      []Relation  `json:"relations"`
}

type Relation struct {
	To   string `json:"to"`
	Type string `json:"type"`
}

type Reference struct {
	ID    string `json:"id"`
	Title string `json:"title"`
}

type Orientation struct {
	Timestamp      time.Time `json:"timestamp"`
	Total          int       `json:"total_kos"`
	Conclusions    int       `json:"conclusions"`
	Canonical      int       `json:"canonical"`
	ReviewRequired int       `json:"review_required"`
}

// Graph is an immutable in-memory snapshot. Incoming edges preserve object
// order, as in the Python storage implementation.
type Graph struct {
	objects  map[string]Object
	incoming map[string][]Relation
	datasets map[string]Dataset
	evidence map[string]bool
}

func Load(reader io.Reader) (*Graph, error) {
	var snapshot struct {
		Objects  []Object  `json:"objects"`
		Datasets []Dataset `json:"datasets"`
		Evidence []struct {
			ID string `json:"id"`
		} `json:"evidence"`
	}
	decoder := json.NewDecoder(reader)
	if err := decoder.Decode(&snapshot); err != nil {
		return nil, fmt.Errorf("decode graph snapshot: %w", err)
	}
	if snapshot.Objects == nil {
		return nil, fmt.Errorf("graph snapshot requires an objects array")
	}
	if err := decoder.Decode(new(json.RawMessage)); err != io.EOF {
		return nil, fmt.Errorf("graph snapshot must contain one JSON document")
	}
	g := &Graph{
		objects:  make(map[string]Object, len(snapshot.Objects)),
		incoming: make(map[string][]Relation),
		datasets: make(map[string]Dataset, len(snapshot.Datasets)),
		evidence: make(map[string]bool, len(snapshot.Evidence)),
	}
	for _, dataset := range snapshot.Datasets {
		if _, exists := g.datasets[dataset.ID]; dataset.ID == "" || exists {
			return nil, fmt.Errorf("empty or duplicate dataset ID %q", dataset.ID)
		}
		g.datasets[dataset.ID] = dataset
	}
	for _, evidence := range snapshot.Evidence {
		if evidence.ID == "" || g.evidence[evidence.ID] {
			return nil, fmt.Errorf("empty or duplicate evidence ID %q", evidence.ID)
		}
		g.evidence[evidence.ID] = true
	}
	for _, object := range snapshot.Objects {
		if object.ID == "" {
			return nil, fmt.Errorf("knowledge object has an empty ID")
		}
		if _, exists := g.objects[object.ID]; exists {
			return nil, fmt.Errorf("duplicate knowledge object ID %q", object.ID)
		}
		if object.Truth == "" {
			object.Truth = "assumption"
		}
		g.objects[object.ID] = object
		for _, edge := range object.Relations {
			if edge.To == "" || edge.Type == "" {
				return nil, fmt.Errorf("knowledge object %q has an incomplete relation", object.ID)
			}
			g.incoming[edge.To] = append(g.incoming[edge.To], Relation{To: object.ID, Type: edge.Type})
		}
	}
	return g, nil
}

func (g *Graph) Orientation(scope string, now time.Time) Orientation {
	result := Orientation{Timestamp: now.UTC(), Total: len(g.objects)}
	for _, object := range g.objects {
		if object.Type == "conclusion" {
			result.Conclusions++
		}
		if object.Status == "canonical" && strings.Contains(object.Scope, scope) {
			result.Canonical++
		}
		if object.ReviewRequired {
			result.ReviewRequired++
		}
	}
	return result
}

func (g *Graph) JustificationPath(root string) []Reference {
	return g.walk(root, true, g.justificationNeighbors)
}

func (g *Graph) justificationNeighbors(id string, enqueue func(string)) {
	for _, edge := range g.objects[id].Relations {
		switch edge.Type {
		case "depends_on", "derived_from", "fitted_on", "tested_against", "transferred_from":
			enqueue(edge.To)
		}
	}
	for _, edge := range g.incoming[id] {
		if edge.Type == "supports" || edge.Type == "validates" {
			enqueue(edge.To)
		}
	}
}

// ImpactSet follows downstream direction. The root is included only if it is
// reached again through a cycle, matching InMemoryStorage.compute_impact_set.
func (g *Graph) ImpactSet(root string) []Reference {
	return g.walk(root, false, func(id string, enqueue func(string)) {
		for _, edge := range g.incoming[id] {
			if edge.Type == "depends_on" || edge.Type == "derived_from" {
				enqueue(edge.To)
			}
		}
		for _, edge := range g.objects[id].Relations {
			switch edge.Type {
			case "supports", "validates", "constrains", "impacts":
				enqueue(edge.To)
			}
		}
	})
}

func (g *Graph) walk(root string, includeRoot bool, visit func(string, func(string))) []Reference {
	queue := make([]string, 0)
	result := make([]Reference, 0)
	seen := make(map[string]bool)
	enqueue := func(id string) {
		if !seen[id] {
			seen[id] = true
			queue = append(queue, id)
			result = append(result, Reference{ID: id, Title: g.objects[id].Title})
		}
	}
	if includeRoot {
		enqueue(root)
	} else {
		visit(root, enqueue)
	}
	for i := 0; i < len(queue); i++ {
		visit(queue[i], enqueue)
	}
	return result
}
