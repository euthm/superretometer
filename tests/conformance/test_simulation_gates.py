"""Conformance tests for SimulationGatePolicy v0.6.

Tests the four gates, frozen baseline, and the sanitized self-falsification story.
"""
import hashlib
import pytest
from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus, ConfidenceLevel,
    RelationType, Provenance, FalsifiableValidator, Relation,
    GateStatus, ScopeDeclaration, SimulationProvenance, FrozenBaseline,
    SimulationGateReport,
)
from cognitive_harness.storage.inmemory import InMemoryStorage
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer
from cognitive_harness.analysis.simulation_gate_policy import SimulationGatePolicy


# ── Helpers ───────────────────────────────────────────────────────────────

def mk_sim_claim(ko_id, title, scope="", prov=None, scope_decl=None,
                 content=None, validators=None, relations=None,
                 truth_cat=TruthCategory.MODEL_DERIVED,
                 ep_status=EpistemicStatus.VALIDATED):
    """Create a simulation-bearing claim KO."""
    c = {}
    if prov:
        c["simulation_provenance"] = prov
    if scope_decl:
        c["scope_declaration"] = scope_decl
    if content:
        c.update(content)
    return KnowledgeObject(
        id=ko_id, type=KOType.CONCLUSION, title=title,
        content=c if c else None,
        truth_category=truth_cat, epistemic_status=ep_status,
        confidence=ConfidenceLevel.MEDIUM, viewpoint_ids=["conceptual"],
        provenance=Provenance(source="simulation", author="test", independent=False),
        scope=scope, relations=relations or [],
        validators=validators or [], evidence_ids=[],
    )


def mk_support(ko_id, title, truth_cat, source="test", independent=True):
    return KnowledgeObject(
        id=ko_id, type=KOType.MODEL_RESULT, title=title,
        content="", truth_category=truth_cat,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source=source, author="test", independent=independent),
        scope="test-scope",
    )


# ================================================================
# TEST 1: Result without reproducible provenance -> BLOCK
# ================================================================

def test_no_provenance(storage):
    policy = SimulationGatePolicy(storage)
    ko = mk_sim_claim("claim-no-prov", "Simulation shows X works")
    storage.create_ko(ko)
    report = policy.evaluate_gates("claim-no-prov")
    assert report.provenance.status == GateStatus.BLOCK, f"{report.provenance.reason}"
    assert not report.design_bearing


# ================================================================
# TEST 2: Incomplete provenance chain -> BLOCK
# ================================================================

def test_incomplete_provenance(storage):
    policy = SimulationGatePolicy(storage)
    prov = {
        "result_artifact": "/tmp/result.csv", "result_sha256": "abc123",
        "run_id": "run-1", "model_id": "model-1",
        "source_path": "models/thermal.mo", "source_commit": "",
    }
    storage.create_ko(mk_support("run-1", "Run", TruthCategory.MODEL_DERIVED))
    storage.create_ko(mk_support("model-1", "Model", TruthCategory.MODEL_DERIVED))
    storage.create_ko(mk_sim_claim("claim-inc-prov", "Thermal result", prov=prov))
    report = policy.evaluate_gates("claim-inc-prov")
    assert report.provenance.status == GateStatus.BLOCK


# ================================================================
# TEST 3: Broken provenance link -> BLOCK
# ================================================================

def test_broken_provenance_link(storage):
    policy = SimulationGatePolicy(storage)
    prov = {
        "result_artifact": "/tmp/result.csv", "result_sha256": "abc123",
        "run_id": "run-missing", "model_id": "model-exists",
        "source_path": "models/thermal.mo", "source_commit": "a1b2c3d",
    }
    storage.create_ko(mk_support("model-exists", "Model", TruthCategory.MODEL_DERIVED))
    storage.create_ko(mk_sim_claim("claim-broken", "Thermal result", prov=prov))
    report = policy.evaluate_gates("claim-broken")
    assert report.provenance.status == GateStatus.BLOCK


# ================================================================
# TEST 4: Claim outside model scope -> BLOCK
# ================================================================

def test_scope_exceeded(storage):
    policy = SimulationGatePolicy(storage)
    scope_decl = {
        "modeled_domain": "thermal", "modeled_extent": "50mm slab",
        "included_components": ["PCB substrate"],
        "excluded_components": ["active components"],
        "system_boundary": "PCB slab only (component-level)",
        "allowed_claim_classes": ["thermal_resistance_component"],
        "disallowed_claim_classes": ["full_board_thermal"],
    }
    prov = {
        "result_artifact": "/tmp/slab.csv", "result_sha256": "def456",
        "run_id": "run-slab", "model_id": "model-slab",
        "source_path": "models/slab.mo", "source_commit": "x7y8z9",
    }
    storage.create_ko(mk_support("run-slab", "Slab run", TruthCategory.MODEL_DERIVED))
    storage.create_ko(mk_support("model-slab", "Slab model", TruthCategory.MODEL_DERIVED))
    storage.create_ko(mk_sim_claim(
        "claim-out-scope", "Full board thermal performance",
        scope="full-board thermal system with active components",
        prov=prov, scope_decl=scope_decl,
    ))
    report = policy.evaluate_gates("claim-out-scope")
    assert report.scope.status == GateStatus.BLOCK, f"{report.scope.reason}"


# ================================================================
# TEST 5: No scope declaration -> BLOCK
# ================================================================

def test_no_scope(storage):
    policy = SimulationGatePolicy(storage)
    prov = {
        "result_artifact": "/tmp/r.csv", "result_sha256": "abc",
        "run_id": "run-5", "model_id": "model-5",
        "source_path": "m.mo", "source_commit": "c1",
    }
    storage.create_ko(mk_support("run-5", "Run", TruthCategory.MODEL_DERIVED))
    storage.create_ko(mk_support("model-5", "Model", TruthCategory.MODEL_DERIVED))
    storage.create_ko(mk_sim_claim("claim-no-scope", "No scope", prov=prov))
    report = policy.evaluate_gates("claim-no-scope")
    assert report.scope.status == GateStatus.BLOCK


# ================================================================
# TEST 6: One failed gate -> not design-bearing
# ================================================================

def test_one_gate_block(storage):
    policy = SimulationGatePolicy(storage)
    prov = {
        "result_artifact": "/tmp/r.csv", "result_sha256": "abc",
        "run_id": "run-6", "model_id": "model-6",
        "source_path": "m.mo", "source_commit": "c6",
    }
    scope_decl = {
        "modeled_domain": "thermal", "system_boundary": "component-level slab",
        "included_components": ["substrate"], "excluded_components": [],
        "allowed_claim_classes": ["thermal"], "disallowed_claim_classes": [],
    }
    storage.create_ko(mk_support("run-6", "Run", TruthCategory.MODEL_DERIVED))
    storage.create_ko(mk_support("model-6", "Model", TruthCategory.MODEL_DERIVED))
    storage.create_ko(mk_sim_claim(
        "claim-one-block", "Component thermal resistance",
        scope="component-level slab", prov=prov, scope_decl=scope_decl,
        validators=[],
    ))
    report = policy.evaluate_gates("claim-one-block")
    assert report.falsifiability.status == GateStatus.BLOCK
    assert not report.design_bearing


# ================================================================
# TEST 7: All four gates PASS -> design-bearing
# ================================================================

def test_all_gates_pass(storage):
    policy = SimulationGatePolicy(storage)
    prov = {
        "result_artifact": "/tmp/r.csv", "result_sha256": "abc",
        "run_id": "run-7", "model_id": "model-7",
        "parameter_set_id": "params-7",
        "source_path": "m.mo", "source_commit": "c7",
    }
    scope_decl = {
        "modeled_domain": "thermal", "system_boundary": "component-level slab",
        "included_components": ["substrate"], "excluded_components": [],
        "allowed_claim_classes": ["thermal"], "disallowed_claim_classes": [],
    }
    vals = [FalsifiableValidator(
        description="Thermal R vs analytical",
        what_would_falsify="R_sim differs from R_analytical by more than 5%",
        passes=True, observation="R_sim = 2.1 K/W, R_ana = 2.13 K/W",
    )]
    storage.create_ko(mk_support("run-7", "Run", TruthCategory.MODEL_DERIVED))
    storage.create_ko(mk_support("model-7", "Model", TruthCategory.MODEL_DERIVED))
    storage.create_ko(mk_support("params-7", "Params", TruthCategory.DOCUMENTED_DECISION))
    # Independent evidence KOs (for Reality gate)
    storage.create_ko(KnowledgeObject(
        id="ev-e1", type=KOType.EVIDENCE_ITEM, title="Independent thermal measurement",
        content="", truth_category=TruthCategory.PHYSICAL_OBSERVATION,
        epistemic_status=EpistemicStatus.VALIDATED, confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="lab-A", author="thermo-lab", independent=True),
        scope="component-level slab", evidence_ids=["ev-rec-1"],
    ))
    storage.add_evidence("ev-rec-1", "ev-e1", "verified", "R = 2.1 K/W", [])
    storage.create_ko(KnowledgeObject(
        id="ev-law", type=KOType.CONSTRAINT, title="Energy conservation",
        content="", truth_category=TruthCategory.CONSERVATION_LAW,
        epistemic_status=EpistemicStatus.CANONICAL, confidence=ConfidenceLevel.CERTAIN,
        provenance=Provenance(source="physics", author="physics", independent=True),
        scope="component-level slab",
    ))
    storage.create_ko(mk_sim_claim(
        "claim-all-pass", "Component thermal validated",
        scope="component-level slab", prov=prov, scope_decl=scope_decl,
        validators=vals,
        relations=[
            Relation(to="ev-e1", type=RelationType.SUPPORTS),
            Relation(to="ev-law", type=RelationType.SUPPORTS),
        ],
    ))
    report = policy.evaluate_gates("claim-all-pass")
    assert report.provenance.status == GateStatus.PASS, f"{report.provenance.reason}"
    assert report.scope.status == GateStatus.PASS, f"{report.scope.reason}"
    assert report.falsifiability.status == GateStatus.PASS, f"{report.falsifiability.reason}"
    assert report.design_bearing


# ================================================================
# TEST 8: Frozen baseline cannot be silently mutated
# ================================================================

def test_frozen_baseline_immutable(storage):
    policy = SimulationGatePolicy(storage)
    prov = {
        "result_artifact": "/tmp/base.csv", "result_sha256": "sha_orig",
        "run_id": "run-b", "model_id": "model-b",
        "source_path": "m.mo", "source_commit": "cB",
    }
    scope_decl = {
        "system_boundary": "test scope", "included_components": ["test"],
        "excluded_components": [], "allowed_claim_classes": ["test"],
        "disallowed_claim_classes": [],
    }
    storage.create_ko(mk_support("run-b", "Run", TruthCategory.MODEL_DERIVED))
    storage.create_ko(mk_support("model-b", "Model", TruthCategory.MODEL_DERIVED))
    storage.create_ko(mk_sim_claim(
        "claim-baseline", "Baseline result", scope="test scope",
        prov=prov, scope_decl=scope_decl,
        validators=[FalsifiableValidator(description="Base", what_would_falsify="Error > 10%", passes=True)],
    ))
    baseline = policy.create_frozen_baseline(
        claim_ko_id="claim-baseline", model_id="model-b",
        source_commit="cB", parameter_set_id="",
        run_command="simulate m.mo", result_artifact="/tmp/base.csv",
        result_sha256="sha_orig",
    )
    assert baseline.immutable is True
    assert policy.verify_baseline_integrity(baseline)
    baseline.immutable = False
    assert not policy.verify_baseline_integrity(baseline)


# ================================================================
# TEST 9: Changed source/hash -> new baseline version
# ================================================================

def test_new_baseline_on_change(storage):
    policy = SimulationGatePolicy(storage)
    prov = {
        "result_artifact": "/tmp/v1.csv", "result_sha256": "sha_v1",
        "run_id": "run-9", "model_id": "model-9",
        "source_path": "m.mo", "source_commit": "cV1",
    }
    scope_decl = {
        "system_boundary": "test", "included_components": ["test"],
        "excluded_components": [], "allowed_claim_classes": ["test"],
        "disallowed_claim_classes": [],
    }
    storage.create_ko(mk_support("run-9", "Run", TruthCategory.MODEL_DERIVED))
    storage.create_ko(mk_support("model-9", "Model", TruthCategory.MODEL_DERIVED))
    storage.create_ko(mk_sim_claim(
        "claim-v1", "V1 result", scope="test", prov=prov, scope_decl=scope_decl,
        validators=[FalsifiableValidator(description="V1", what_would_falsify="Err > 10%", passes=True)],
    ))
    b1 = policy.create_frozen_baseline(
        claim_ko_id="claim-v1", model_id="model-9",
        source_commit="cV1", parameter_set_id="",
        run_command="sim v1.mo", result_artifact="/tmp/v1.csv", result_sha256="sha_v1",
    )
    b2 = FrozenBaseline(
        baseline_id="bl-v2", version=2, model_id="model-9",
        source_commit="cV2", parameter_set_id="", run_command="sim v2.mo",
        result_artifact="/tmp/v2.csv", result_sha256="sha_v2",
        gate_report=b1.gate_report, allowed_claims=b1.allowed_claims, immutable=True,
    )
    assert b1.baseline_id != b2.baseline_id
    assert b2.version > b1.version
    assert b1.result_sha256 != b2.result_sha256
    assert policy.verify_baseline_integrity(b2)


# ================================================================
# TEST 10: Invariant invalid for system boundary -> BLOCK
# ================================================================

def test_invalid_invariant(storage):
    policy = SimulationGatePolicy(storage)
    scope_decl = {
        "modeled_domain": "chemical", "modeled_extent": "reactor with recycle loop",
        "system_boundary": "reactor + recycle line (with reaction at boundary)",
        "included_components": ["reactor", "recycle line"],
        "excluded_components": ["feed preheater"],
        "allowed_claim_classes": ["conversion"],
        "disallowed_claim_classes": ["feed_composition"],
    }
    prov = {
        "result_artifact": "/tmp/reactor.csv", "result_sha256": "r123",
        "run_id": "run-r", "model_id": "model-r",
        "source_path": "m.mo", "source_commit": "cR",
    }
    storage.create_ko(mk_support("run-r", "Run", TruthCategory.MODEL_DERIVED))
    storage.create_ko(mk_support("model-r", "Model", TruthCategory.MODEL_DERIVED))
    ko_content = {"invariant_valid_for_boundary": False}
    vals = [FalsifiableValidator(
        description="Carbon balance: Cin = Cout",
        what_would_falsify="Carbon in != Carbon out",
        passes=True,
    )]
    storage.create_ko(mk_sim_claim(
        "claim-bad-inv", "Reactor conversion",
        scope="reactor + recycle line", prov=prov, scope_decl=scope_decl,
        content=ko_content, validators=vals,
    ))
    report = policy.evaluate_gates("claim-bad-inv")
    assert report.falsifiability.status == GateStatus.BLOCK, f"{report.falsifiability.reason}"
    assert not report.design_bearing


# ================================================================
# TEST 11: Self-falsification example (sanitized Arx story)
# ================================================================

def test_self_falsification(storage):
    """The harness must be able to discover that its own diagnosis was wrong."""
    policy = SimulationGatePolicy(storage)
    analyzer = WarrantAnalyzer(storage)

    storage.create_ko(KnowledgeObject(
        id="sf-model", type=KOType.MODEL_RESULT, title="Process model v3.2",
        content="", truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.VALIDATED, confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="model-repo", author="eng", independent=True),
        scope="reactor + catalyst bed (steady state)",
    ))
    storage.create_ko(KnowledgeObject(
        id="sf-params", type=KOType.DECISION, title="Design-basis parameters",
        content="", truth_category=TruthCategory.DOCUMENTED_DECISION,
        epistemic_status=EpistemicStatus.VALIDATED, confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="spec", author="eng", independent=True),
        scope="reactor + catalyst bed (steady state)",
    ))
    storage.create_ko(KnowledgeObject(
        id="sf-run", type=KOType.OBSERVATION, title="Steady-state simulation run",
        content="", truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.VALIDATED, confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="solver", author="sim", independent=True),
        scope="reactor + catalyst bed (steady state)",
    ))

    # H1 falsified
    storage.create_ko(KnowledgeObject(
        id="sf-h1", type=KOType.HYPOTHESIS,
        title="H1: Flow normalization uses wrong reference basis",
        content="Hypothesis falsified by evidence.",
        truth_category=TruthCategory.ASSUMPTION,
        epistemic_status=EpistemicStatus.INVALIDATED,
        confidence=ConfidenceLevel.LOW,
        provenance=Provenance(source="diagnosis", author="harness", independent=True),
        scope="reactor + catalyst bed (steady state)",
        validators=[FalsifiableValidator(
            description="Check normalization basis",
            what_would_falsify="Flows already normalized to operating conditions",
            passes=False, observation="Verified correct: T=523K, P=5MPa",
        )],
    ))
    storage.add_evidence("ev-h1", "sf-h1", "verified", "H1 falsified", [])

    # H2 falsified
    storage.create_ko(KnowledgeObject(
        id="sf-h2", type=KOType.HYPOTHESIS,
        title="H2: Mass flow formula uses wrong molar mass",
        content="Hypothesis falsified by evidence.",
        truth_category=TruthCategory.ASSUMPTION,
        epistemic_status=EpistemicStatus.INVALIDATED,
        confidence=ConfidenceLevel.LOW,
        provenance=Provenance(source="diagnosis", author="harness", independent=True),
        scope="reactor + catalyst bed (steady state)",
        validators=[FalsifiableValidator(
            description="Check mass flow formula",
            what_would_falsify="Formula already uses correct molar mass",
            passes=False, observation="Verified correct: weighted avg molar mass",
        )],
    ))
    storage.add_evidence("ev-h2", "sf-h2", "verified", "H2 falsified", [])

    # Root cause
    storage.create_ko(KnowledgeObject(
        id="sf-root", type=KOType.FINDING,
        title="Root cause: analysis tool used wrong reference basis",
        content="Analysis tool used wrong molar mass. Model was correct.",
        truth_category=TruthCategory.PHYSICAL_OBSERVATION,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="root-cause-analysis", author="eng", independent=True),
        scope="reactor + catalyst bed (steady state)", evidence_ids=["ev-root"],
    ))
    storage.add_evidence("ev-root", "sf-root", "verified", "Tool molar mass wrong", [])

    # Correct invariant
    storage.create_ko(KnowledgeObject(
        id="sf-inv", type=KOType.CONSTRAINT,
        title="Carbon balance: internal reactor boundary (correct)",
        content="C_in = C_out + C_byproduct. Gap = 0.01%.",
        truth_category=TruthCategory.CONSERVATION_LAW,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.CERTAIN,
        provenance=Provenance(source="stoichiometry", author="chem", independent=True),
        scope="reactor + catalyst bed (steady state)",
        validators=[FalsifiableValidator(
            description="Carbon mass balance for reactor boundary",
            what_would_falsify="Carbon gap > 0.1% with correct molar mass",
            passes=True, observation="Gap = 0.01%",
        )],
    ))

    # Final conclusion
    sha = hashlib.sha256(b"sf_output").hexdigest()
    storage.create_ko(KnowledgeObject(
        id="sf-conc", type=KOType.CONCLUSION,
        title="Process carbon balance validated at design-basis",
        content={
            "simulation_provenance": {
                "result_artifact": "/data/sf.csv", "result_sha256": sha,
                "run_id": "sf-run", "parameter_set_id": "sf-params",
                "model_id": "sf-model", "source_path": "models/Reactor.mo",
                "source_commit": "a1b2c3d4", "source_version": "v3.2",
            },
            "scope_declaration": {
                "modeled_domain": "chemical reaction",
                "modeled_extent": "reactor at design-basis throughput",
                "included_components": ["reactor", "catalyst bed"],
                "excluded_components": ["feed preheater", "product separation"],
                "system_boundary": "reactor + catalyst bed (steady state)",
                "allowed_claim_classes": ["carbon_balance", "conversion", "selectivity"],
                "disallowed_claim_classes": ["full_plant_balance", "energy_consumption"],
            },
        },
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="simulation", author="eng", independent=False),
        scope="reactor + catalyst bed (steady state)",
        validators=[FalsifiableValidator(
            description="Carbon balance closes to < 0.1%",
            what_would_falsify="Carbon gap > 0.1% with correct molar mass",
            passes=True, observation="Gap = 0.01%",
        )],
        relations=[
            Relation(to="sf-model", type=RelationType.DEPENDS_ON),
            Relation(to="sf-params", type=RelationType.DEPENDS_ON),
            Relation(to="sf-inv", type=RelationType.DEPENDS_ON),
            Relation(to="sf-root", type=RelationType.DEPENDS_ON),
        ],
    ))

    # Verify H1/H2 falsified
    assert storage.get_ko("sf-h1").epistemic_status == EpistemicStatus.INVALIDATED
    assert storage.get_ko("sf-h2").epistemic_status == EpistemicStatus.INVALIDATED

    # Verify gates
    report = policy.evaluate_gates("sf-conc")
    assert report.provenance.status == GateStatus.PASS, f"{report.provenance.reason}"
    assert report.scope.status == GateStatus.PASS, f"{report.scope.reason}"
    assert report.falsifiability.status == GateStatus.PASS, f"{report.falsifiability.reason}"

    # Verify baseline
    baseline = policy.create_frozen_baseline(
        claim_ko_id="sf-conc", model_id="sf-model",
        source_commit="a1b2c3d4", parameter_set_id="sf-params",
        run_command="simulate Reactor.mo", result_artifact="/data/sf.csv",
        result_sha256=sha,
    )
    assert baseline.immutable
    assert policy.verify_baseline_integrity(baseline)


# ================================================================
# TEST 12: Orphaned result -> BLOCK
# ================================================================

def test_orphaned_result(storage):
    policy = SimulationGatePolicy(storage)
    storage.create_ko(KnowledgeObject(
        id="orphaned", type=KOType.MODEL_RESULT, title="Orphaned result",
        content="No model, no params, no commit.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.TENTATIVE,
        confidence=ConfidenceLevel.LOW,
        provenance=Provenance(source="unknown", author="unknown", independent=False),
        scope="unknown",
    ))
    report = policy.evaluate_gates("orphaned")
    assert report.provenance.status == GateStatus.BLOCK
    assert not report.design_bearing


# ================================================================
# TEST 13: Valid invariant for boundary -> PASS
# ================================================================

def test_valid_invariant(storage):
    policy = SimulationGatePolicy(storage)
    scope_decl = {
        "modeled_domain": "thermal", "system_boundary": "steady-state heat exchanger",
        "included_components": ["tube side", "shell side"],
        "excluded_components": [],
        "allowed_claim_classes": ["heat_transfer"],
        "disallowed_claim_classes": [],
    }
    prov = {
        "result_artifact": "/tmp/hx.csv", "result_sha256": "hx123",
        "run_id": "run-hx", "model_id": "model-hx",
        "source_path": "m.mo", "source_commit": "cH",
    }
    storage.create_ko(mk_support("run-hx", "Run", TruthCategory.MODEL_DERIVED))
    storage.create_ko(mk_support("model-hx", "Model", TruthCategory.MODEL_DERIVED))
    vals = [FalsifiableValidator(
        description="Energy balance: Q_tube = -Q_shell",
        what_would_falsify="Energy balance gap > 1%",
        passes=True, observation="Gap = 0.02%",
    )]
    storage.create_ko(mk_sim_claim(
        "claim-good-inv", "HX validated",
        scope="steady-state heat exchanger", prov=prov, scope_decl=scope_decl,
        validators=vals,
    ))
    report = policy.evaluate_gates("claim-good-inv")
    assert report.falsifiability.status == GateStatus.PASS, f"{report.falsifiability.reason}"