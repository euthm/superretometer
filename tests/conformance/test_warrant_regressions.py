# FILE: tests/conformance/test_warrant_regressions.py
"""Regression tests for warrant-analysis and harness defects fixed in v0.7.1.

Scope: structural warrant semantics (cycle reporting, traversal depth,
grounding classification, explainability, provenance-root overlap) plus the
falsifiability of the verification layer itself — the examples, the external
validation runner, and the negative controls must all be able to fail.
Each test names the defect it pins so a reintroduction is self-describing.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus, ConfidenceLevel,
    RelationType, Provenance, Relation, DerivationRelation, DerivationType,
    Dataset, WarrantStatus,
)
from cognitive_harness.storage.inmemory import InMemoryStorage
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer
from cognitive_harness.analysis.simulation_gate_policy import SimulationGatePolicy
from cognitive_harness.analysis.implementation_gate_policy import canonical_remote

REPO_ROOT = Path(__file__).resolve().parents[2]


def mk(ko_id, title, truth_cat, **kw):
    kw.setdefault("provenance", Provenance(source=ko_id, author="test", independent=True))
    return KnowledgeObject(id=ko_id, title=title, truth_category=truth_cat, **kw)


# ── Cycle reporting ────────────────────────────────────────────────────────

def test_cycles_are_reported_on_the_result(storage):
    """WarrantResult.cycles was always empty: _collect_justification_path kept a
    DFS 'in_stack' inside a BFS, discarding each node in the same iteration, so
    the cycle branch was unreachable."""
    storage.create_ko(mk("a", "A", TruthCategory.MODEL_DERIVED))
    storage.create_ko(mk("b", "B", TruthCategory.MODEL_DERIVED))
    storage.create_relation("a", "b", RelationType.SUPPORTS)
    storage.create_relation("b", "a", RelationType.SUPPORTS)

    result = WarrantAnalyzer(storage).compute_warrant("a")

    assert result.warrant_status == WarrantStatus.UNWARRANTED
    assert result.cycles, "a detected cycle must appear on the result, not only in diagnoses"
    assert any(d.pattern.value == "circular_dependency" for d in result.anti_pattern_diagnoses)


def test_deep_acyclic_chain_does_not_exhaust_the_stack(storage):
    """Graph depth is an input; recursion depth must not be. The recursive DFS
    in _find_cycles_in_path raised RecursionError on a valid 2000-node chain."""
    n = 2000
    for i in range(n):
        storage.create_ko(mk(f"n{i}", f"n{i}", TruthCategory.MODEL_DERIVED))
    for i in range(n - 1):
        storage.create_relation(f"n{i+1}", f"n{i}", RelationType.SUPPORTS)

    result = WarrantAnalyzer(storage).compute_warrant("n0")

    assert result.cycles == []
    assert len(result.supporting_kos) == n


# ── Grounding classification ───────────────────────────────────────────────

def test_documented_decision_conditions_rather_than_grounds(storage):
    """A decision was filed under independent_kos even when it failed
    _has_independent_grounding, so a physical claim resting on a meeting note
    computed as WARRANTED."""
    storage.create_ko(mk("decision", "We decided the beam is adequate",
                         TruthCategory.DOCUMENTED_DECISION,
                         provenance=Provenance(source="meeting-notes", author="pm",
                                               independent=False)))
    storage.create_ko(mk("claim", "Beam will not fail under design load",
                         TruthCategory.MODEL_DERIVED))
    storage.create_relation("decision", "claim", RelationType.SUPPORTS)

    result = WarrantAnalyzer(storage).compute_warrant("claim")

    assert result.warrant_status == WarrantStatus.CONDITIONALLY_WARRANTED
    assert "decision" not in result.independent_kos
    assert any("decision" in c for c in result.conditional_assumptions)


def test_unwarranted_is_always_explainable(storage):
    """Two datasets with no traceable lineage intersect to the empty set, which
    read as a clean train/test split: UNWARRANTED with no diagnosis at all, and
    a reality gate rendering 'Structural defects in grounding: []'."""
    storage.create_dataset(Dataset(id="train"))
    storage.create_dataset(Dataset(id="test"))
    storage.create_ko(mk("param", "fitted parameter", TruthCategory.MODEL_DERIVED,
                         derivation=DerivationRelation(
                             derivation_type=DerivationType.FITTED,
                             training_dataset_id="train", test_dataset_id="test")))
    storage.create_ko(mk("claim", "conclusion from fitted parameter",
                         TruthCategory.MODEL_DERIVED))
    storage.create_relation("param", "claim", RelationType.SUPPORTS)

    result = WarrantAnalyzer(storage).compute_warrant("claim")

    assert result.warrant_status == WarrantStatus.UNWARRANTED
    assert result.anti_pattern_diagnoses, "untraceable dataset lineage must be diagnosed"
    assert any(d.pattern.value == "calibrated_to_conclusion"
               for d in result.anti_pattern_diagnoses)

    gate = SimulationGatePolicy(storage)._gate_reality("claim")
    assert gate.status.value == "block"
    assert "[]" not in gate.reason, f"unexplained block: {gate.reason}"


# ── Provenance-root overlap ────────────────────────────────────────────────

def _two_premises(storage, roots_a, roots_b):
    for rid in set(roots_a) | set(roots_b):
        storage.create_ko(mk(rid, rid, TruthCategory.PHYSICAL_OBSERVATION,
                             evidence_ids=[f"ev-{rid}"]))
    for name, roots in (("a", roots_a), ("b", roots_b)):
        storage.create_ko(mk(name, name, TruthCategory.MODEL_DERIVED,
                             derivation=DerivationRelation(
                                 derivation_type=DerivationType.MODELED,
                                 upstream_ko_ids=list(roots))))
    storage.create_ko(mk("claim", "conclusion", TruthCategory.MODEL_DERIVED))
    storage.create_relation("a", "claim", RelationType.SUPPORTS)
    storage.create_relation("b", "claim", RelationType.SUPPORTS)
    return WarrantAnalyzer(storage).compute_warrant("claim")


def test_partial_root_overlap_weakens_warrant(storage):
    """Sharing was tested with set equality, so {R1,R2} vs {R1,R3} compared
    unequal and the common root R1 was invisible."""
    result = _two_premises(storage, ["R1", "R2"], ["R1", "R3"])

    assert result.warrant_status == WarrantStatus.CONDITIONALLY_WARRANTED
    assert any("R1" in c for c in result.conditional_assumptions)


def test_extra_upstream_node_cannot_clear_a_shared_root(storage):
    """Under set equality, adding one unrelated upstream node to a single
    premise flipped CONDITIONALLY_WARRANTED to WARRANTED while the shared root
    was still shared."""
    assert _two_premises(storage, ["R1"], ["R1"]).warrant_status == \
        WarrantStatus.CONDITIONALLY_WARRANTED

    storage2 = InMemoryStorage()
    result = _two_premises(storage2, ["R1"], ["R1", "R9"])
    assert result.warrant_status == WarrantStatus.CONDITIONALLY_WARRANTED
    assert any("R1" in c for c in result.conditional_assumptions)


def test_validated_grounding_requires_disjoint_roots(storage):
    """The VALIDATED branch compared root_sets[0] != root_sets[1]: it accepted
    overlapping sets ({R} vs {R,S}) and ignored every upstream past the second,
    while the FITTED branch already required disjointness."""
    storage.create_ko(mk("R", "R", TruthCategory.PHYSICAL_OBSERVATION, evidence_ids=["e"]))
    storage.create_ko(mk("S", "S", TruthCategory.PHYSICAL_OBSERVATION, evidence_ids=["e"]))
    storage.create_ko(mk("q1", "q1", TruthCategory.MODEL_DERIVED,
                         derivation=DerivationRelation(
                             derivation_type=DerivationType.MODELED, upstream_ko_ids=["R"])))
    storage.create_ko(mk("q2", "q2", TruthCategory.MODEL_DERIVED,
                         derivation=DerivationRelation(
                             derivation_type=DerivationType.MODELED,
                             upstream_ko_ids=["R", "S"])))
    validation = mk("v", "q1 agrees with q2", TruthCategory.MODEL_DERIVED,
                    derivation=DerivationRelation(
                        derivation_type=DerivationType.VALIDATED,
                        upstream_ko_ids=["q1", "q2"]))
    storage.create_ko(validation)

    analyzer = WarrantAnalyzer(storage)
    assert analyzer._trace_provenance_roots("q1") & analyzer._trace_provenance_roots("q2")
    assert analyzer._has_independent_grounding(validation, ["v", "q1", "q2"]) is False


# ── Repository identity ────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "https://github.com/euthm/foo.git",
    "https://github.com/euthm/foo.git/",
    "https://github.com/euthm/foo/",
    "git@github.com:euthm/foo.git",
    "ssh://git@github.com/euthm/foo.git/",
])
def test_canonical_remote_is_stable_under_trailing_slash(raw):
    """A trailing slash blocked the .git strip, so '.../foo.git/' canonicalized
    to 'github.com/euthm/foo.git' and stopped matching the same repository."""
    assert canonical_remote(raw) == "github.com/euthm/foo"


# ── The verification layer must be able to fail ────────────────────────────

def test_check_warrant_exposes_its_conditions(storage):
    """CONDITIONALLY_WARRANTED is defined as the status that exposes its
    conditions, but the MCP payload returned only the bare verdict."""
    from cognitive_harness.mcp.server import MCPServer

    server = MCPServer.__new__(MCPServer)
    server.storage = storage
    server.wa = WarrantAnalyzer(storage)
    _two_premises(storage, ["R1"], ["R1"])

    payload = server._handle_check_warrant({"conclusion_ko_id": "claim"})

    assert payload["warrant_status"] == "conditionally_warranted"
    assert payload["conditional_assumptions"], "conditions must reach the caller"
    assert payload["independence"]["shared_ancestors"]


# Each example gets a mutation that inverts the outcome it claims, so the
# check proves the assertion binds rather than merely that one is present.
EXAMPLE_MUTATIONS = [
    # claims WARRANTED — remove the evidence's independence
    ("minimal", "independent=True", "independent=False"),
    # claims UNWARRANTED on one non-independent FEA result — make it independent
    ("structural_engineering", "independent=False", "independent=True"),
    # claims an UNSUPPORTED_TRANSFER among its defects — remove the transfer
    ("engineering_model", "DerivationType.TRANSFERRED", "DerivationType.MATHEMATICAL"),
]


@pytest.mark.parametrize("name,old,new", EXAMPLE_MUTATIONS)
def test_examples_assert_their_expected_outcome(name, old, new, tmp_path):
    """CI runs the examples, so without assertions that step passed on any
    output at all and only a crash could fail it. Verified both ways: the
    example holds, and a mutated graph makes it fail rather than print."""
    source = (REPO_ROOT / "examples" / name / "run.py").read_text()
    assert "assert " in source, f"examples/{name}/run.py states no expectation"
    assert old in source, f"mutation target {old!r} missing from examples/{name}/run.py"

    env = {"PYTHONPATH": str(REPO_ROOT), "PATH": "/usr/bin:/bin"}
    ok = subprocess.run([sys.executable, f"examples/{name}/run.py"],
                        cwd=REPO_ROOT, capture_output=True, text=True, env=env)
    assert ok.returncode == 0, ok.stderr

    broken = tmp_path / "run.py"
    broken.write_text(source.replace(old, new))
    bad = subprocess.run([sys.executable, str(broken)], cwd=REPO_ROOT,
                         capture_output=True, text=True, env=env)
    assert bad.returncode != 0, f"examples/{name}/run.py cannot fail"
    assert "AssertionError" in bad.stderr


def test_external_validation_negative_controls_are_collected():
    """NC1-NC5 were named nc*_ rather than test_nc*_, so pytest never collected
    them: 8 of 13 scenarios ran under CI."""
    import tests.validation.test_external_validation as module

    for name in ("test_nc1_orphan", "test_nc2_out_of_scope", "test_nc3_ungrounded",
                 "test_nc4_invalid_invariant", "test_nc5_all_valid"):
        assert hasattr(module, name), f"{name} is not collectable by pytest"


def test_external_validation_runner_reports_failure_in_its_exit_code():
    """run_validation() swallowed every exception and always exited 0, so a
    regression in the negative controls could not fail a build."""
    import tests.validation.test_external_validation as module

    assert module.run_validation() == 0, "all 13 scenarios should currently agree"

    env = {"PYTHONPATH": ".", "PATH": "/usr/bin:/bin"}
    completed = subprocess.run(
        [sys.executable, "tests/validation/test_external_validation.py"],
        cwd=REPO_ROOT, capture_output=True, text=True, env=env,
    )
    assert completed.returncode == 0

    # Flip one expectation and confirm the runner actually reports it. Without
    # this the test would only ever exercise the passing path.
    induced = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, '.');"
         "import tests.validation.test_external_validation as m;"
         "m.EXPECTED['NC1: orphan'] = ('pass', 'pass', 'pass', 'pass', True);"
         "sys.exit(1 if m.run_validation() else 0)"],
        cwd=REPO_ROOT, capture_output=True, text=True, env=env,
    )
    assert induced.returncode == 1, "a mismatched expectation must fail the runner"


def test_mcp_entry_points_are_runnable():
    """transports/mcp/server.py is the command documented in AGENTS.md but had
    no __main__ guard, so it imported and exited 0 without starting a server."""
    assert "__main__" in (REPO_ROOT / "transports/mcp/server.py").read_text()
