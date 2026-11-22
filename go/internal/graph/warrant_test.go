package graph

import (
	"slices"
	"strings"
	"testing"
)

func TestFittedPremiseRequiresIndependentDatasetLineage(t *testing.T) {
	cases := []struct {
		name       string
		testSource string
		parents    string
		status     string
		pattern    string
	}{
		{"disjoint", "observation-b", "[]", "warranted", ""},
		{"overlap", "observation-a", "[]", "unwarranted", "calibrated_to_conclusion"},
		{"circular", "claim", "[]", "unwarranted", "calibrated_to_conclusion"},
		{"partial lineage", "observation-b", `["missing-parent"]`, "unwarranted", "missing_independent_validation"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			snapshot := `{
				"objects": [
					{"id":"claim","relations":[{"to":"fit","type":"depends_on"}]},
					{"id":"fit","truth_category":"fitted_parameter","provenance":{"source":"model","independent":true},
					 "derivation":{"derivation_type":"fitted","training_dataset_id":"train","test_dataset_id":"test"}},
					{"id":"observation-a","provenance":{"source":"  Study A  "}},
					{"id":"observation-b","provenance":{"source":"Study B"}}
				],
				"datasets": [
					{"id":"train","source_ko_id":"observation-a"},
					{"id":"test","source_ko_id":"` + tc.testSource + `","derived_from_dataset_ids":` + tc.parents + `}
				]
			}`
			g, err := Load(strings.NewReader(snapshot))
			if err != nil {
				t.Fatal(err)
			}
			w := g.CheckWarrant("claim")
			if w.Status != tc.status {
				t.Fatalf("status = %q, want %q: %+v", w.Status, tc.status, w)
			}
			if tc.pattern == "" {
				if len(w.Diagnoses) != 0 || !slices.Equal(w.Independent, []string{"fit"}) ||
					!slices.Equal(w.Independence.RootSets["fit"], []string{"study a", "study b"}) {
					t.Fatalf("unexpected warrant: %+v", w)
				}
			} else if len(w.Diagnoses) != 1 || w.Diagnoses[0].Pattern != tc.pattern ||
				!slices.Equal(w.Dependent, []string{"fit"}) {
				t.Fatalf("unexpected rejection: %+v", w)
			}
		})
	}
}
