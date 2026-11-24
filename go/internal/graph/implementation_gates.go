package graph

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"maps"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
)

type ImplementationGateReport struct {
	Claim          string     `json:"claim_ko_id"`
	Provenance     GateResult `json:"provenance"`
	Scope          GateResult `json:"scope"`
	Worktree       GateResult `json:"worktree"`
	Test           GateResult `json:"test"`
	Falsifiability GateResult `json:"falsifiability"`
	Dependency     GateResult `json:"dependency"`
	Freshness      GateResult `json:"freshness"`
	DesignBearing  bool       `json:"design_bearing"`
}

func (g *Graph) ImplementationGates(id string) ImplementationGateReport {
	o, exists := g.objects[id]
	if !exists {
		return ImplementationGateReport{Claim: id,
			Provenance: gate("provenance", "block", "Claim KO not found."), Scope: gate("scope", "block", "Claim KO not found."),
			Worktree: gate("worktree", "block", "Claim KO not found."), Test: gate("test", "block", "Claim KO not found."),
			Falsifiability: gate("falsifiability", "block", "Claim KO not found."), Dependency: gate("dependency", "block", "Claim KO not found."),
			Freshness: gate("freshness", "block", "Claim KO not found.")}
	}
	p := implementationProvenance(o)
	r := ImplementationGateReport{Claim: id,
		Provenance: implementationProvenanceGate(p), Scope: implementationScope(o, p),
		Worktree: implementationWorktree(p), Test: g.implementationTest(p),
		Falsifiability: implementationFalsifiability(o), Dependency: implementationDependency(p), Freshness: g.implementationFreshness(p)}
	r.DesignBearing = allPass(r.Provenance, r.Scope, r.Worktree, r.Test, r.Falsifiability, r.Dependency, r.Freshness)
	return r
}

var scpRemote = regexp.MustCompile(`^[^@/]+@([^:]+):(.+)$`)
var urlRemote = regexp.MustCompile(`^(?:https?|ssh|git)://(?:(?:[^@/]+)@)?([^/:]+)(?::\d+)?(/[^?#]+)?`)
var credentialRemote = regexp.MustCompile(`^(https?)://(?:[^@/]+)@(.+)$`)

// CanonicalRemote normalizes transport syntax, preserving owner/path case.
func CanonicalRemote(remote string) string {
	r := strings.TrimSuffix(strings.TrimRight(strings.TrimSpace(remote), "/"), ".git")
	if match := scpRemote.FindStringSubmatch(r); match != nil && !strings.Contains(r, "://") {
		return strings.TrimRight(strings.ToLower(match[1])+"/"+match[2], "/")
	}
	if match := urlRemote.FindStringSubmatch(r); match != nil {
		return strings.TrimRight(strings.ToLower(match[1])+match[2], "/")
	}
	if index := strings.Index(r, "/"); index > 0 {
		return strings.TrimRight(strings.ToLower(r[:index])+r[index:], "/")
	}
	return strings.TrimRight(strings.ToLower(r), "/")
}

func sanitizeRemote(remote string) string {
	r := strings.TrimSpace(remote)
	if match := credentialRemote.FindStringSubmatch(r); match != nil {
		return match[1] + "://" + match[2]
	}
	return r
}

func implementationProvenance(o Object) map[string]any {
	raw := nestedMap(content(o), "implementation_provenance")
	if raw == nil {
		return nil
	}
	p := maps.Clone(raw)
	sanitized, exists := raw["repo_remote_sanitized"]
	if !exists {
		sanitized = raw["repo_remote_raw"]
	}
	sanitizedText, _ := sanitized.(string)
	sanitizedText = sanitizeRemote(sanitizedText)
	canonical := stringValue(p, "repo_remote_canonical")
	compat := sanitizeRemote(stringValue(p, "repo_remote"))
	if sanitizedText != "" && canonical != "" && CanonicalRemote(sanitizedText) != canonical {
		// Conflicting repository identities must not leave an apparently complete
		// commit/test chain usable by any gate.
		return map[string]any{"repo_remote_sanitized": sanitizedText, "repo_remote_canonical": "", "commit": ""}
	}
	if sanitizedText == "" && canonical == "" && compat != "" {
		sanitizedText, canonical = compat, CanonicalRemote(compat)
	} else if canonical == "" && compat != "" {
		canonical = CanonicalRemote(compat)
	} else if canonical == "" && sanitizedText != "" {
		canonical = CanonicalRemote(sanitizedText)
	}
	p["repo_remote_canonical"], p["repo_remote_sanitized"], p["repo_remote"] = canonical, sanitizedText, compat
	p["submodule_pins"] = normalizedPins(nestedMap(raw, "submodule_pins"))
	p["tested_submodule_pins"] = normalizedPins(nestedMap(raw, "tested_submodule_pins"))
	return p
}

func normalizedPins(raw map[string]any) map[string]any {
	result := map[string]any{}
	for name, value := range raw {
		pin, ok := value.(map[string]any)
		if !ok {
			continue
		}
		p := maps.Clone(pin)
		remote, exists := p["remote"]
		if !exists {
			remote = p["repo_remote_sanitized"]
		}
		text, _ := remote.(string)
		p["repo_remote_sanitized"] = sanitizeRemote(text)
		if stringValue(p, "repo_remote_canonical") == "" && text != "" {
			p["repo_remote_canonical"] = CanonicalRemote(text)
		}
		result[name] = p
	}
	return result
}

func implementationProvenanceGate(p map[string]any) GateResult {
	if p == nil {
		return gate("provenance", "block", "No implementation provenance attached. Cannot trace claim to commit.")
	}
	missing := []string{}
	for _, key := range []string{"repo_remote_canonical", "commit"} {
		if stringValue(p, key) == "" {
			missing = append(missing, key)
		}
	}
	if len(missing) > 0 {
		return gate("provenance", "block", "Provenance chain incomplete. Missing: "+strings.Join(missing, ", ")+".")
	}
	commit, canonical := stringValue(p, "commit"), stringValue(p, "repo_remote_canonical")
	evidence := []string{commit, canonical}
	if branch := stringValue(p, "branch"); branch != "" {
		evidence = append(evidence, "branch: "+branch)
	}
	return gate("provenance", "pass", fmt.Sprintf("Complete provenance chain: %s @%s", canonical, commit), evidence...)
}

func implementationScope(o Object, p map[string]any) GateResult {
	if p == nil {
		return gate("scope", "block", "No implementation provenance to check scope against.")
	}
	allowed := stringList(content(o), "declared_remotes")
	for _, value := range append(stringList(nestedMap(content(o), "scope_declaration"), "included_components"), o.Scope) {
		if strings.HasPrefix(value, "git@") || strings.HasPrefix(value, "https://") || strings.HasPrefix(value, "git://") {
			allowed = append(allowed, value)
		}
	}
	if len(allowed) == 0 {
		return gate("scope", "unknown", "No remotes declared in scope. Cannot evaluate remote match.")
	}
	canonical := stringValue(p, "repo_remote_canonical")
	if canonical == "" {
		return gate("scope", "block", "Provenance has no canonical remote. Cannot match against scope.")
	}
	for _, remote := range allowed {
		if canonical == CanonicalRemote(remote) {
			return gate("scope", "pass", fmt.Sprintf("Provenance canonical remote '%s' matches scope-declared remote.", canonical), canonical)
		}
	}
	return gate("scope", "block", fmt.Sprintf("Remote mismatch: provenance canonical '%s' not in scope-declared remotes: %s. Implementation claim cannot be design-bearing.", canonical, pyStrings(allowed)))
}

func implementationWorktree(p map[string]any) GateResult {
	if p == nil {
		return gate("worktree", "block", "No implementation provenance to check worktree state.")
	}
	clean, observed := p["worktree_clean"].(bool)
	if observed && clean {
		return gate("worktree", "pass", fmt.Sprintf("Clean worktree: commit %s… represents exact code state.", prefix(stringValue(p, "commit"), 8)), stringValue(p, "commit"))
	}
	if observed {
		if diff := stringValue(p, "worktree_diff_sha256"); diff != "" {
			return gate("worktree", "unknown", fmt.Sprintf("Dirty worktree with diff snapshot (%s…). State is identified but not a clean commit — cannot PASS.", prefix(diff, 8)))
		}
		return gate("worktree", "block", "Dirty worktree without diff hash. Tested code state cannot be reproducibly identified.")
	}
	return gate("worktree", "unknown", "Worktree state not observed. Cannot establish code-state reproducibility.")
}

var timestampTZ = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$`)
var timestampNaive = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$`)

func (g *Graph) implementationTest(p map[string]any) GateResult {
	if p == nil {
		return gate("test", "block", "No implementation provenance to verify test.")
	}
	for _, check := range [][2]string{
		{"validator_ko_id", "No validator_ko_id. No CH evidence KO linked to this claim."},
		{"test_run_id", "No test_run_id. External runner identity missing."},
		{"test_command", "No test_command. Test execution command not recorded."},
		{"test_result_sha256", "No test_result_sha256. Test result artifact not captured."},
	} {
		if stringValue(p, check[0]) == "" {
			return gate("test", "unknown", check[1])
		}
	}
	validator, commit, tested := stringValue(p, "validator_ko_id"), stringValue(p, "commit"), stringValue(p, "tested_commit")
	if _, exists := g.objects[validator]; !exists {
		return gate("test", "unknown", fmt.Sprintf("validator_ko_id '%s' not found in graph. Evidence KO must exist.", validator))
	}
	if tested == "" {
		return gate("test", "unknown", "No tested_commit. Cannot verify tests ran against claim commit.")
	}
	if tested != commit {
		return gate("test", "block", fmt.Sprintf("tested_commit '%s…' != claim commit '%s…'. Tests ran against different revision.", prefix(tested, 8), prefix(commit, 8)))
	}
	if explicitlyFalse(p, "worktree_clean") {
		if stringValue(p, "tested_worktree_diff_sha256") == "" {
			return gate("test", "block", "Dirty worktree but no tested_worktree_diff_sha256. Cannot verify tests ran against same dirty state.")
		}
		if stringValue(p, "tested_worktree_diff_sha256") != stringValue(p, "worktree_diff_sha256") {
			return gate("test", "block", "tested_worktree_diff != claim worktree_diff. Tests ran against different code state.")
		}
	}
	if value, exists := p["test_exit_code"]; !exists || value == nil {
		return gate("test", "unknown", "test_exit_code not recorded. Cannot determine pass/fail.")
	}
	exit, valid := integerValue(p["test_exit_code"])
	if !valid {
		return gate("test", "block", "test_exit_code is not an integer. Cannot determine pass/fail.")
	}
	if exit != 0 {
		return gate("test", "block", fmt.Sprintf("test_exit_code=%d. Tests did not pass.", exit))
	}
	timestamp := stringValue(p, "test_timestamp")
	if timestamp == "" {
		return gate("test", "unknown", "test_timestamp not recorded. Incomplete validation provenance.")
	}
	if !timestampTZ.MatchString(timestamp) {
		if timestampNaive.MatchString(timestamp) {
			return gate("test", "unknown", fmt.Sprintf("test_timestamp '%s' lacks timezone offset. Not portable across machines — incomplete provenance.", timestamp))
		}
		return gate("test", "block", fmt.Sprintf("test_timestamp '%s' is not valid ISO 8601.", timestamp))
	}
	return gate("test", "pass", fmt.Sprintf("Complete test evidence: run %s, command '%s', exit 0, tested against %s…", stringValue(p, "test_run_id"), stringValue(p, "test_command"), prefix(tested, 8)),
		stringValue(p, "test_run_id"), validator, prefix(stringValue(p, "test_result_sha256"), 16)+"…", "exit_code: 0")
}

func implementationFalsifiability(o Object) GateResult {
	if len(o.Validators) == 0 {
		return gate("falsifiability", "unknown", "No validators on claim. UNGROUNDED.")
	}
	for _, v := range o.Validators {
		if v.WhatWouldFalsify != "" {
			return gate("falsifiability", "pass", "Falsifier declared: "+prefix(v.WhatWouldFalsify, 100), v.ID)
		}
	}
	return gate("falsifiability", "unknown", "Validators exist but none declare what would falsify. Cannot establish falsifiability.")
}

func implementationDependency(p map[string]any) GateResult {
	if p == nil {
		return gate("dependency", "block", "No provenance.")
	}
	claim, tested := nestedMap(p, "submodule_pins"), nestedMap(p, "tested_submodule_pins")
	if len(claim) == 0 {
		return gate("dependency", "pass", "No submodules declared. Not applicable.")
	}
	if len(tested) == 0 {
		return gate("dependency", "unknown", fmt.Sprintf("Claim declares %d submodule(s) but no tested_submodule_pins. Cannot verify dependency state.", len(claim)))
	}
	claimNames, testedNames := slices.Sorted(maps.Keys(claim)), slices.Sorted(maps.Keys(tested))
	if !slices.Equal(claimNames, testedNames) {
		missing, extra := stringSet{}, stringSet{}
		for _, name := range claimNames {
			if _, ok := tested[name]; !ok {
				missing[name] = true
			}
		}
		for _, name := range testedNames {
			if _, ok := claim[name]; !ok {
				extra[name] = true
			}
		}
		details := []string{}
		if len(missing) > 0 {
			details = append(details, "missing tested pins: "+rootLabels(missing))
		}
		if len(extra) > 0 {
			details = append(details, "unexpected tested pins: "+rootLabels(extra))
		}
		return gate("dependency", "block", "Submodule sets differ: "+strings.Join(details, "; ")+".")
	}
	evidence := []string{}
	for _, name := range claimNames {
		c, t := nestedMap(claim, name), nestedMap(tested, name)
		cr, tr := stringValue(c, "repo_remote_canonical"), stringValue(t, "repo_remote_canonical")
		cc, tc := stringValue(c, "commit"), stringValue(t, "commit")
		if cr != "" && tr != "" && cr != tr {
			return gate("dependency", "block", fmt.Sprintf("Submodule '%s': canonical remote mismatch (%s vs %s).", name, cr, tr))
		}
		if cc != "" && tc != "" && cc != tc {
			return gate("dependency", "block", fmt.Sprintf("Submodule '%s': commit mismatch (%s vs %s).", name, prefix(cc, 8), prefix(tc, 8)))
		}
		evidence = append(evidence, name+": "+cr+"@"+prefix(cc, 8))
	}
	return gate("dependency", "pass", fmt.Sprintf("All %d submodule(s) verified consistent.", len(claimNames)), evidence...)
}

// WithFreshnessRoots returns a graph view permitting freshness reads under
// explicitly trusted local directories. Snapshot contents cannot grant access.
func (g *Graph) WithFreshnessRoots(roots []string) *Graph {
	result := *g
	result.freshnessRoots = append([]string{}, roots...)
	return &result
}

func (g *Graph) implementationFreshness(p map[string]any) GateResult {
	if p == nil {
		return gate("freshness", "block", "No provenance.")
	}
	digest, paths := stringValue(p, "blob_digest"), stringList(p, "blob_paths")
	if digest == "" || len(paths) == 0 {
		return gate("freshness", "unknown", "No blob_digest or blob_paths recorded. Cannot verify code freshness against commit.")
	}
	if stringValue(p, "repo_path") == "" {
		return gate("freshness", "unknown", "Could not compute blob digest: Repo path does not exist: .")
	}
	if len(g.freshnessRoots) == 0 {
		return gate("freshness", "unknown", "Local repository access is not configured. Cannot verify code freshness.")
	}
	computed, err := g.blobDigest(stringValue(p, "repo_path"), paths)
	if err != nil {
		return gate("freshness", "unknown", "Could not compute blob digest: "+err.Error()+".")
	}
	if computed != digest {
		return gate("freshness", "block", fmt.Sprintf("Code drift detected: stored digest %s… does not match computed %s… for paths %s.", prefix(digest, 12), prefix(computed, 12), pyStrings(paths)))
	}
	evidence := []string{}
	for _, path := range paths {
		evidence = append(evidence, path+": included")
	}
	return gate("freshness", "pass", fmt.Sprintf("Code freshness verified for %d path(s).", len(paths)), evidence...)
}

func (g *Graph) blobDigest(repoPath string, paths []string) (string, error) {
	info, err := os.Stat(repoPath)
	if err != nil || !info.IsDir() {
		return "", fmt.Errorf("Repo path does not exist: %s", repoPath)
	}
	repo, err := filepath.EvalSymlinks(repoPath)
	if err != nil {
		return "", err
	}
	repo, err = filepath.Abs(repo)
	if err != nil {
		return "", err
	}
	allowed := false
	for _, root := range g.freshnessRoots {
		resolved, err := filepath.EvalSymlinks(root)
		if err != nil {
			continue
		}
		resolved, err = filepath.Abs(resolved)
		if err == nil && contained(resolved, repo) {
			allowed = true
			break
		}
	}
	if !allowed {
		return "", fmt.Errorf("repository is outside configured repository roots")
	}
	// Root.Open enforces containment again during the actual open, avoiding a
	// symlink replacement race between the checks below and reading file bytes.
	rootFS, err := os.OpenRoot(repo)
	if err != nil {
		return "", err
	}
	defer rootFS.Close()
	hash := sha256.New()
	ordered := slices.Clone(paths)
	slices.Sort(ordered)
	for _, path := range ordered {
		if filepath.IsAbs(path) || !contained(repo, filepath.Join(repo, path)) {
			return "", fmt.Errorf("blob path is outside repository: %s", path)
		}
		full := filepath.Join(repo, path)
		resolved, err := filepath.EvalSymlinks(full)
		if os.IsNotExist(err) {
			continue
		} // Reference hashes existing regular files.
		if err != nil {
			return "", err
		}
		if !contained(repo, resolved) {
			return "", fmt.Errorf("blob path resolves outside repository: %s", path)
		}
		fileInfo, err := os.Stat(resolved)
		if err != nil {
			return "", err
		}
		if !fileInfo.Mode().IsRegular() {
			continue
		}
		file, err := rootFS.Open(path)
		if err != nil {
			return "", err
		}
		_, copyErr := io.Copy(hash, file)
		closeErr := file.Close()
		if copyErr != nil {
			return "", copyErr
		}
		if closeErr != nil {
			return "", closeErr
		}
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func contained(root, path string) bool {
	rel, err := filepath.Rel(root, path)
	return err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))
}

func prefix(value string, count int) string {
	runes := []rune(value)
	if len(runes) > count {
		return string(runes[:count])
	}
	return value
}

func integerValue(value any) (int64, bool) {
	switch v := value.(type) {
	case json.Number:
		number, err := v.Int64()
		return number, err == nil
	case float64:
		number := int64(v)
		return number, float64(number) == v
	case int:
		return int64(v), true
	case int64:
		return v, true
	default:
		return 0, false
	}
}
