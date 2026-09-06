# FILE: tests/validation/test_external_validation.py
"""External validation of SimulationGatePolicy v0.6 against representative engineering cases.

Validates gate conclusions match engineering judgment for three domains:
  Domain 1 - Electromechanical motor (3 cases)
  Domain 2 - Thermal energy storage (3 cases)
  Domain 3 - Chemical reactor (2 cases)
  Negative controls (5 boundary cases)

Total: 13 cases, 0 mismatches expected.

PRINCIPLE: Do NOT modify policy to make cases pass.
Report mismatches with root cause before any fix.
"""
import logging
from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus, ConfidenceLevel,
    RelationType, Provenance, FalsifiableValidator, Relation,
)
from cognitive_harness.storage.inmemory import InMemoryStorage
from cognitive_harness.analysis.simulation_gate_policy import SimulationGatePolicy

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
log = logging.getLogger(__name__)


# ================================================================
# Helpers
# ================================================================

def mk_support(storage, ko_id, title, truth_cat, source="test",
               independent=True, relations=None, validators=None,
               evidence_ids=None):
    storage.create_ko(KnowledgeObject(
        id=ko_id, type=KOType.MODEL_RESULT, title=title,
        content="", truth_category=truth_cat,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source=source, author="validation", independent=independent),
        scope="test", relations=relations or [],
        validators=validators or [], evidence_ids=evidence_ids or [],
    ))
    return ko_id


def mk_claim(storage, ko_id, title, scope="", prov=None, scope_decl=None,
             validators=None, relations=None, content=None):
    c = {}
    if prov:
        c["simulation_provenance"] = prov
    if scope_decl:
        c["scope_declaration"] = scope_decl
    if content:
        c.update(content)
    
    # Direction-aware relation handling (v0.6.4):
    # SUPPORTS and VALIDATES are inbound to the claim (evidence -> claim).
    # DEPENDS_ON and DERIVED_FROM are outbound from the claim (claim -> prereq).
    claim_relations = []
    inbound_relations = []
    for rel in (relations or []):
        if rel.type in (RelationType.SUPPORTS, RelationType.VALIDATES):
            inbound_relations.append(rel)
        else:
            claim_relations.append(rel)
    
    storage.create_ko(KnowledgeObject(
        id=ko_id, type=KOType.CONCLUSION, title=title,
        content=c if c else None, truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.MEDIUM,
        viewpoint_ids=["conceptual"],
        provenance=Provenance(source="simulation", author="validation", independent=False),
        scope=scope, relations=claim_relations,
        validators=validators or [],
    ))
    # Create inbound relations: evidence -> SUPPORTS/VALIDATES -> claim
    for rel in inbound_relations:
        storage.create_relation(rel.to, ko_id, rel.type)
    return ko_id


def eval_gates(storage, policy, ko_id, label=""):
    report = policy.evaluate_gates(ko_id)
    return {
        "label": label or ko_id, "ko_id": ko_id,
        "provenance": report.provenance.status.value,
        "scope": report.scope.status.value,
        "reality": report.reality.status.value,
        "falsifiability": report.falsifiability.status.value,
        "design_bearing": report.design_bearing,
    }


def _prov(result_sha, run_id, model_id, params_id, src_path, src_commit):
    return {
        "result_artifact": f"/data/{run_id}.csv", "result_sha256": result_sha,
        "run_id": run_id, "model_id": model_id, "parameter_set_id": params_id,
        "source_path": src_path, "source_commit": src_commit,
    }


def _scope(domain, extent, incl, excl, boundary, allowed, disallowed):
    return {
        "modeled_domain": domain, "modeled_extent": extent,
        "included_components": incl, "excluded_components": excl,
        "system_boundary": boundary,
        "allowed_claim_classes": allowed, "disallowed_claim_classes": disallowed,
    }


# ================================================================
# DOMAIN 1 - Electromechanical Motor (3 cases)
# ================================================================

def test_motor_geometry_sourced_not_independent():
    log.info("\n== D1-C1: Motor geometry (sourced, not independent) ==")
    st = InMemoryStorage()
    pol = SimulationGatePolicy(st)
    mk_support(st, "d1r", "Run", TruthCategory.MODEL_DERIVED)
    mk_support(st, "d1m", "Model", TruthCategory.MODEL_DERIVED)
    mk_support(st, "d1p", "Params", TruthCategory.DOCUMENTED_DECISION)
    mk_support(st, "d1cad", "Vendor CAD", TruthCategory.SOURCED_MATERIAL_DATA,
               source="vendor-cad", independent=False)
    mk_claim(st, "d1c", "Pole area from vendor CAD",
             scope="motor stator geometry",
             prov=_prov("sha_g", "d1r", "d1m", "d1p", "models/motor.mo", "v2"),
             scope_decl=_scope("electromechanical", "motor stator",
                               ["stator", "pole arc"], ["rotor"],
                               "motor stator geometry", ["geometry"], ["full_performance"]),
             validators=[FalsifiableValidator(description="Pole area check",
                 what_would_falsify="CAD differs from measured by > 1%", passes=True)],
             relations=[Relation(to="d1cad", type=RelationType.SUPPORTS)])
    r = eval_gates(st, pol, "d1c")
    log.info(f"  P={r['provenance']}, S={r['scope']}, R={r['reality']}, F={r['falsifiability']}, DB={r['design_bearing']}")
    assert r["provenance"] == "pass"
    assert r["scope"] == "pass"
    assert r["falsifiability"] == "pass"
    assert r["reality"] == "block"
    assert not r["design_bearing"]
    log.info("  PASS")
    return r


def test_motor_physically_unrealizable():
    log.info("\n== D1-C2: Motor physically unrealizable ==")
    st = InMemoryStorage()
    pol = SimulationGatePolicy(st)
    mk_support(st, "d1r", "Run", TruthCategory.MODEL_DERIVED)
    mk_support(st, "d1m", "Model", TruthCategory.MODEL_DERIVED)
    mk_support(st, "d1p", "Params", TruthCategory.DOCUMENTED_DECISION)
    mk_support(st, "d1cont", "Continuity law", TruthCategory.CONSERVATION_LAW,
               source="physics", independent=True)
    mk_support(st, "d1prof", "Discontinuous L(theta)", TruthCategory.MODEL_DERIVED,
               source="model", independent=True,
               relations=[Relation(to="d1cont", type=RelationType.CONTRADICTS)])
    mk_claim(st, "d1c", "Inductance profile valid",
             scope="motor inductance profile",
             prov=_prov("sha_i", "d1r", "d1m", "d1p", "models/motor.mo", "v2"),
             scope_decl=_scope("electromagnetic", "inductance profile",
                               ["inductance"], [], "motor inductance profile", ["inductance"], []),
             validators=[FalsifiableValidator(description="Continuity",
                 what_would_falsify="Jump > 10%", passes=False,
                 observation="Jump: 88.9% discontinuity")],
             relations=[Relation(to="d1prof", type=RelationType.DEPENDS_ON),
                        Relation(to="d1cont", type=RelationType.DEPENDS_ON)])
    r = eval_gates(st, pol, "d1c")
    log.info(f"  P={r['provenance']}, S={r['scope']}, R={r['reality']}, F={r['falsifiability']}, DB={r['design_bearing']}")
    assert r["reality"] in ("block", "unknown")
    assert not r["design_bearing"]
    log.info("  PASS")
    return r


def test_motor_loss_coefficients_grounded():
    log.info("\n== D1-C3: Motor loss coefficients (grounded) ==")
    st = InMemoryStorage()
    pol = SimulationGatePolicy(st)
    mk_support(st, "d1r", "Run", TruthCategory.MODEL_DERIVED)
    mk_support(st, "d1m", "Model", TruthCategory.MODEL_DERIVED)
    mk_support(st, "d1p", "Params", TruthCategory.DOCUMENTED_DECISION)
    mk_support(st, "d1steel", "Steel datasheet", TruthCategory.SOURCED_MATERIAL_DATA,
               source="steel_mfr", independent=True)
    mk_claim(st, "d1c", "Loss coefficients validated (R2=0.997)",
             scope="motor iron loss coefficients",
             prov=_prov("sha_l", "d1r", "d1m", "d1p", "models/motor.mo", "v2"),
             scope_decl=_scope("iron loss", "iron loss coefficients",
                               ["loss fit"], [], "motor iron loss coefficients", ["iron_loss"], []),
             validators=[FalsifiableValidator(description="Fit quality",
                 what_would_falsify="R2 < 0.95", passes=True,
                 observation="R2 = 0.997, 133 points")],
             relations=[Relation(to="d1steel", type=RelationType.SUPPORTS)])
    r = eval_gates(st, pol, "d1c")
    log.info(f"  P={r['provenance']}, S={r['scope']}, R={r['reality']}, F={r['falsifiability']}, DB={r['design_bearing']}")
    assert r["provenance"] == "pass"
    assert r["scope"] == "pass"
    assert r["falsifiability"] == "pass"
    assert r["reality"] == "pass"
    log.info("  PASS")
    return r


# ================================================================
# DOMAIN 2 - Thermal Energy Storage (3 cases)
# ================================================================

def test_thermal_local_claim():
    log.info("\n== D2-C1: Thermal storage (local claim) ==")
    st = InMemoryStorage()
    pol = SimulationGatePolicy(st)
    mk_support(st, "d2r", "Run", TruthCategory.MODEL_DERIVED)
    mk_support(st, "d2m", "Model", TruthCategory.MODEL_DERIVED)
    mk_support(st, "d2p", "Params", TruthCategory.DOCUMENTED_DECISION)
    mk_support(st, "d2pcm", "PCM datasheet", TruthCategory.SOURCED_MATERIAL_DATA,
               source="material-datasheet", independent=True)
    mk_claim(st, "d2c", "Capacity per unit validated",
             scope="thermal storage single unit",
             prov=_prov("sha_tl", "d2r", "d2m", "d2p", "models/thermal.mo", "v1"),
             scope_decl=_scope("thermal capacity", "single unit slab",
                               ["pcm slab", "thermal resistance"],
                               ["full stack", "discharge channel"],
                               "thermal storage single unit",
                               ["capacity_per_unit"], ["full_system_efficiency"]),
             validators=[FalsifiableValidator(description="Capacity vs analytical",
                 what_would_falsify="Differs by > 5%", passes=True)],
             relations=[Relation(to="d2pcm", type=RelationType.SUPPORTS)])
    r = eval_gates(st, pol, "d2c")
    log.info(f"  P={r['provenance']}, S={r['scope']}, R={r['reality']}, F={r['falsifiability']}, DB={r['design_bearing']}")
    assert r["provenance"] == "pass"
    assert r["scope"] == "pass"
    assert r["falsifiability"] == "pass"
    log.info("  PASS")
    return r


def test_thermal_scope_exceeded():
    log.info("\n== D2-C2: Thermal storage (scope exceeded) ==")
    st = InMemoryStorage()
    pol = SimulationGatePolicy(st)
    mk_support(st, "d2r", "Run", TruthCategory.MODEL_DERIVED)
    mk_support(st, "d2m", "Model", TruthCategory.MODEL_DERIVED)
    mk_support(st, "d2p", "Params", TruthCategory.DOCUMENTED_DECISION)
    mk_claim(st, "d2c", "Full system efficiency 85%",
             scope="full thermal storage system",
             prov=_prov("sha_tf", "d2r", "d2m", "d2p", "models/thermal.mo", "v1"),
             scope_decl=_scope("thermal capacity", "single unit slab",
                               ["pcm slab"], ["full stack"],
                               "thermal storage single unit",
                               ["capacity_per_unit"], ["full_system_efficiency"]),
             validators=[FalsifiableValidator(description="Full system eta",
                 what_would_falsify="eta < 80%", passes=True)])
    r = eval_gates(st, pol, "d2c")
    log.info(f"  P={r['provenance']}, S={r['scope']}, R={r['reality']}, F={r['falsifiability']}, DB={r['design_bearing']}")
    assert r["scope"] == "block"
    assert not r["design_bearing"]
    log.info("  PASS")
    return r


def test_thermal_placeholder_param():
    log.info("\n== D2-C3: Thermal storage (placeholder parameter) ==")
    st = InMemoryStorage()
    pol = SimulationGatePolicy(st)
    mk_support(st, "d2r", "Run", TruthCategory.MODEL_DERIVED)
    mk_support(st, "d2m", "Model", TruthCategory.MODEL_DERIVED)
    mk_support(st, "d2p", "Params", TruthCategory.DOCUMENTED_DECISION)
    mk_support(st, "d2ua_m", "UA measured", TruthCategory.SOURCED_MATERIAL_DATA,
               source="envelope-calc", independent=True)
    mk_support(st, "d2ua_ph", "UA_loss = 4.0 (PLACEHOLDER)", TruthCategory.ASSUMPTION,
               source="model-placeholder", independent=False)
    mk_claim(st, "d2c", "Standing loss: 32K decay over 24h",
             scope="thermal store standing loss",
             prov=_prov("sha_t24", "d2r", "d2m", "d2p", "models/thermal.mo", "v1"),
             scope_decl=_scope("thermal loss", "standing loss 24h",
                               ["pcm stack", "insulation"], ["discharge channel"],
                               "thermal store standing loss",
                               ["standing_loss"], ["cycle_efficiency"]),
             validators=[FalsifiableValidator(description="24h decay vs envelope",
                 what_would_falsify="Differs by > 5K", passes=True)],
             relations=[Relation(to="d2ua_m", type=RelationType.SUPPORTS),
                        Relation(to="d2ua_ph", type=RelationType.DEPENDS_ON)])
    r = eval_gates(st, pol, "d2c")
    log.info(f"  P={r['provenance']}, S={r['scope']}, R={r['reality']}, F={r['falsifiability']}, DB={r['design_bearing']}")
    assert r["provenance"] == "pass"
    assert r["scope"] == "pass"
    assert r["falsifiability"] == "pass"
    assert r["reality"] == "unknown"
    assert not r["design_bearing"]
    log.info("  PASS")
    return r


# ================================================================
# DOMAIN 3 - Chemical Reactor (2 cases)
# ================================================================

def test_reactor_baseline_all_pass():
    log.info("\n== D3-C1: Chemical reactor baseline ==")
    st = InMemoryStorage()
    pol = SimulationGatePolicy(st)
    mk_support(st, "d3r", "Run", TruthCategory.MODEL_DERIVED)
    mk_support(st, "d3m", "Model", TruthCategory.MODEL_DERIVED)
    mk_support(st, "d3p", "Params", TruthCategory.DOCUMENTED_DECISION)
    mk_support(st, "d3law", "Carbon conservation", TruthCategory.CONSERVATION_LAW,
               source="stoichiometry", independent=True)
    mk_support(st, "d3mm", "Molar mass validated", TruthCategory.PHYSICAL_OBSERVATION,
               source="root-cause", independent=True, evidence_ids=["ev-d3"])
    st.add_evidence("ev-d3", "d3mm", "verified", "M = 23.4 g/mol", [])
    mk_claim(st, "d3c", "Reactor carbon balance validated",
             scope="reactor + catalyst bed (steady state)",
             prov=_prov("sha_rv1", "d3r", "d3m", "d3p", "api/spec_gate.py", "commit_v1"),
             scope_decl=_scope("chemical reaction", "reactor at design-basis",
                               ["reactor", "cut model", "catalyst bed"],
                               ["feed preheater"],
                               "reactor + catalyst bed (steady state)",
                               ["carbon_balance", "conversion"],
                               ["full_plant_balance"]),
             validators=[
                 FalsifiableValidator(description="Carbon balance",
                     what_would_falsify="Gap > 0.1%", passes=True,
                     observation="Gap = 0.01%"),
                 FalsifiableValidator(description="Mass conservation",
                     what_would_falsify="product + light + heavy != input",
                     passes=True, observation="Error < 1e-10"),
             ],
             relations=[Relation(to="d3law", type=RelationType.SUPPORTS),
                        Relation(to="d3mm", type=RelationType.SUPPORTS)])
    r = eval_gates(st, pol, "d3c")
    log.info(f"  P={r['provenance']}, S={r['scope']}, R={r['reality']}, F={r['falsifiability']}, DB={r['design_bearing']}")
    assert r["provenance"] == "pass"
    assert r["scope"] == "pass"
    assert r["falsifiability"] == "pass"
    assert r["reality"] == "pass"
    log.info("  PASS")
    return r


def test_reactor_rejected_invariant():
    log.info("\n== D3-C2: Chemical reactor rejected invariant ==")
    st = InMemoryStorage()
    pol = SimulationGatePolicy(st)
    mk_support(st, "d3r", "Run", TruthCategory.MODEL_DERIVED)
    mk_support(st, "d3m", "Model", TruthCategory.MODEL_DERIVED)
    mk_support(st, "d3p", "Params", TruthCategory.DOCUMENTED_DECISION)
    mk_claim(st, "d3c", "Recycle loop: Cin = Cout",
             scope="reactor + catalyst bed (steady state)",
             prov=_prov("sha_rc", "d3r", "d3m", "d3p", "api/tailgas.py", "commit_v1"),
             scope_decl=_scope("chemical reaction", "reactor only",
                               ["reactor"], ["recycle loop"],
                               "reactor + catalyst bed (steady state)",
                               ["carbon_balance"], ["recycle_loop_balance"]),
             validators=[FalsifiableValidator(description="Cin = Cout",
                 what_would_falsify="Cin != Cout", passes=True,
                 observation="Trivially true by construction")],
             content={"invariant_valid_for_boundary": False})
    r = eval_gates(st, pol, "d3c")
    log.info(f"  P={r['provenance']}, S={r['scope']}, R={r['reality']}, F={r['falsifiability']}, DB={r['design_bearing']}")
    assert r["falsifiability"] == "block"
    assert not r["design_bearing"]
    log.info("  PASS")
    return r


# ================================================================
# NEGATIVE CONTROLS (5)
# ================================================================

def nc1_orphan():
    log.info("\n== NC1: Orphan ==")
    st = InMemoryStorage()
    pol = SimulationGatePolicy(st)
    st.create_ko(KnowledgeObject(
        id="nc1", type=KOType.MODEL_RESULT, title="Orphan",
        content="", truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.TENTATIVE, confidence=ConfidenceLevel.LOW,
        provenance=Provenance(source="unknown", author="unknown", independent=False),
        scope="unknown"))
    r = eval_gates(st, pol, "nc1")
    log.info(f"  P={r['provenance']}, DB={r['design_bearing']}")
    assert r["provenance"] == "block"
    assert not r["design_bearing"]
    log.info("  PASS")
    return r


def nc2_out_of_scope():
    log.info("\n== NC2: Out of scope ==")
    st = InMemoryStorage()
    pol = SimulationGatePolicy(st)
    mk_support(st, "r", "Run", TruthCategory.MODEL_DERIVED)
    mk_support(st, "m", "Model", TruthCategory.MODEL_DERIVED)
    mk_support(st, "p", "Params", TruthCategory.DOCUMENTED_DECISION)
    mk_claim(st, "c", "Full board thermal",
             scope="full-board system",
             prov=_prov("abc", "r", "m", "p", "m.mo", "c1"),
             scope_decl=_scope("component", "component slab",
                               ["substrate"], ["active"],
                               "component slab", ["component_thermal"], ["full_board"]),
             validators=[FalsifiableValidator(description="R", what_would_falsify="R off > 10%", passes=True)])
    r = eval_gates(st, pol, "c")
    log.info(f"  S={r['scope']}, DB={r['design_bearing']}")
    assert r["scope"] == "block"
    assert not r["design_bearing"]
    log.info("  PASS")
    return r


def nc3_ungrounded():
    log.info("\n== NC3: Ungrounded carrying quantity ==")
    st = InMemoryStorage()
    pol = SimulationGatePolicy(st)
    mk_support(st, "r", "Run", TruthCategory.MODEL_DERIVED)
    mk_support(st, "m", "Model", TruthCategory.MODEL_DERIVED)
    mk_support(st, "p", "Params", TruthCategory.DOCUMENTED_DECISION)
    mk_support(st, "a", "Unverified coefficient", TruthCategory.ASSUMPTION,
               source="placeholder", independent=False)
    mk_claim(st, "c", "Thermal resistance verified",
             scope="component slab",
             prov=_prov("abc", "r", "m", "p", "m.mo", "c3"),
             scope_decl=_scope("thermal", "component slab",
                               ["substrate"], [], "component slab", ["thermal"], []),
             validators=[FalsifiableValidator(description="R", what_would_falsify="R off > 5%", passes=True)],
             relations=[Relation(to="a", type=RelationType.DEPENDS_ON)])
    r = eval_gates(st, pol, "c")
    log.info(f"  R={r['reality']}, DB={r['design_bearing']}")
    assert r["reality"] == "unknown"
    assert not r["design_bearing"]
    log.info("  PASS")
    return r


def nc4_invalid_invariant():
    log.info("\n== NC4: Invalid invariant ==")
    st = InMemoryStorage()
    pol = SimulationGatePolicy(st)
    mk_support(st, "r", "Run", TruthCategory.MODEL_DERIVED)
    mk_support(st, "m", "Model", TruthCategory.MODEL_DERIVED)
    mk_support(st, "p", "Params", TruthCategory.DOCUMENTED_DECISION)
    mk_claim(st, "c", "Carbon: Cin = Cout",
             scope="reactor (steady state)",
             prov=_prov("abc", "r", "m", "p", "m.mo", "c4"),
             scope_decl=_scope("chemical", "reactor",
                               ["reactor"], ["recycle"],
                               "reactor (steady state)", ["conversion"], ["recycle_balance"]),
             validators=[FalsifiableValidator(description="Cin=Cout", what_would_falsify="Cin!=Cout", passes=True)],
             content={"invariant_valid_for_boundary": False})
    r = eval_gates(st, pol, "c")
    log.info(f"  F={r['falsifiability']}, DB={r['design_bearing']}")
    assert r["falsifiability"] == "block"
    assert not r["design_bearing"]
    log.info("  PASS")
    return r


def nc5_all_valid():
    log.info("\n== NC5: All gates valid (positive control) ==")
    st = InMemoryStorage()
    pol = SimulationGatePolicy(st)
    mk_support(st, "r", "Run", TruthCategory.MODEL_DERIVED)
    mk_support(st, "m", "Model", TruthCategory.MODEL_DERIVED)
    mk_support(st, "p", "Params", TruthCategory.DOCUMENTED_DECISION)
    mk_support(st, "ev", "Independent measurement", TruthCategory.PHYSICAL_OBSERVATION,
               source="lab-A", independent=True, evidence_ids=["ev1"])
    st.add_evidence("ev1", "ev", "verified", "R = 2.1 K/W", [])
    mk_support(st, "law", "Energy conservation", TruthCategory.CONSERVATION_LAW,
               source="physics", independent=True)
    mk_claim(st, "c", "Thermal validated",
             scope="component slab",
             prov=_prov("abc", "r", "m", "p", "m.mo", "c5"),
             scope_decl=_scope("thermal", "component slab",
                               ["substrate"], [], "component slab", ["thermal"], []),
             validators=[FalsifiableValidator(description="R vs analytical",
                 what_would_falsify="Differs by > 5%", passes=True,
                 observation="R_sim=2.1, R_ana=2.13")],
             relations=[Relation(to="ev", type=RelationType.SUPPORTS),
                        Relation(to="law", type=RelationType.SUPPORTS)])
    r = eval_gates(st, pol, "c")
    log.info(f"  P={r['provenance']}, S={r['scope']}, R={r['reality']}, F={r['falsifiability']}, DB={r['design_bearing']}")
    assert r["provenance"] == "pass"
    assert r["scope"] == "pass"
    assert r["falsifiability"] == "pass"
    assert r["reality"] == "pass"
    log.info("  PASS")
    return r


# ================================================================
# MAIN
# ================================================================

EXPECTED = {
    "D1-C1: motor geometry (sourced, not independent)":   ("pass", "pass", "block", "pass", False),
    "D1-C2: motor inductance (unrealizable)":             ("pass", "pass", "block", "pass", False),
    "D1-C3: motor loss coefficients (grounded)":          ("pass", "pass", "pass", "pass", True),
    "D2-C1: thermal storage (local claim)":               ("pass", "pass", "pass", "pass", True),
    "D2-C2: thermal storage (scope exceeded)":            ("pass", "block", "*", "*", False),
    "D2-C3: thermal storage (placeholder param)":         ("pass", "pass", "unknown", "pass", False),
    "D3-C1: reactor baseline (all pass)":                 ("pass", "pass", "pass", "pass", True),
    "D3-C2: reactor rejected invariant":                  ("pass", "pass", "*", "block", False),
    "NC1: orphan":                                        ("block", "*", "*", "*", False),
    "NC2: out of scope":                                  ("pass", "block", "*", "*", False),
    "NC3: ungrounded carrying qty":                       ("pass", "pass", "unknown", "pass", False),
    "NC4: scope-invalid invariant":                       ("pass", "pass", "*", "block", False),
    "NC5: all gates valid":                               ("pass", "pass", "pass", "pass", True),
}


def run_validation():
    log.info("=" * 72)
    log.info("EXTERNAL VALIDATION OF SIMULATION GATE POLICY v0.6")
    log.info("13 cases: 3 domains x N cases + 5 negative controls")
    log.info("=" * 72)

    test_funcs = [
        ("D1-C1: motor geometry (sourced, not independent)", test_motor_geometry_sourced_not_independent),
        ("D1-C2: motor inductance (unrealizable)", test_motor_physically_unrealizable),
        ("D1-C3: motor loss coefficients (grounded)", test_motor_loss_coefficients_grounded),
        ("D2-C1: thermal storage (local claim)", test_thermal_local_claim),
        ("D2-C2: thermal storage (scope exceeded)", test_thermal_scope_exceeded),
        ("D2-C3: thermal storage (placeholder param)", test_thermal_placeholder_param),
        ("D3-C1: reactor baseline (all pass)", test_reactor_baseline_all_pass),
        ("D3-C2: reactor rejected invariant", test_reactor_rejected_invariant),
        ("NC1: orphan", nc1_orphan),
        ("NC2: out of scope", nc2_out_of_scope),
        ("NC3: ungrounded carrying qty", nc3_ungrounded),
        ("NC4: scope-invalid invariant", nc4_invalid_invariant),
        ("NC5: all gates valid", nc5_all_valid),
    ]

    results = {}
    passed = failed = 0
    for name, func in test_funcs:
        try:
            results[name] = func()
            passed += 1
        except Exception as e:
            failed += 1
            log.error(f"  FAIL [{name}]: {e}")
            import traceback; traceback.print_exc()

    log.info("\n" + "=" * 72)
    print(f"\n{'Case':40s} {'Expected':35s} {'Actual':35s} {'Match'}")
    print("-" * 115)
    mismatches = 0
    for name in EXPECTED:
        ep, es, er, ef, edb = EXPECTED[name]
        if name not in results:
            print(f"{name:40s} {'(expected)':35s} {'SKIPPED':35s} NO")
            mismatches += 1
            continue
        r = results[name]
        ap, as_, ar, af = r["provenance"], r["scope"], r["reality"], r["falsifiability"]
        exp_s = f"p={ep},s={es},r={er},f={ef}"
        act_s = f"p={ap},s={as_},r={ar},f={af}"
        ok = True
        for exp_g, act_g in [(ep, ap), (es, as_), (er, ar), (ef, af)]:
            if exp_g != "*" and exp_g != act_g:
                ok = False
        if edb != r["design_bearing"]:
            ok = False
        if not ok:
            mismatches += 1
        print(f"{name:40s} {exp_s:35s} {act_s:35s} {'YES' if ok else 'NO'}")

    log.info("\n" + "=" * 72)
    log.info(f"RESULTS: {passed} passed, {failed} failed, {passed + failed} total")
    if mismatches == 0:
        log.info("NO MISMATCHES - v0.6 generalizes correctly across 3 domains")
    else:
        log.info(f"MISMATCHES: {mismatches}")
    log.info("=" * 72)


if __name__ == "__main__":
    run_validation()
