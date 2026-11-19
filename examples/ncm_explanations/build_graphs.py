# FILE: examples/ncm_explanations/build_graphs.py
"""Build two synthetic graphs with identical claims but different provenance topology.

Graph A (shared_root): Three supporting statements all derive from one simulation.
Graph B (independent): Three supporting statements derive from three independent measurements.

Both graphs share the same conclusion KO and the same three supporting KO texts.
The difference is purely structural: provenance roots.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus,
    ConfidenceLevel, RelationType, Provenance, Relation,
    DerivationType, DerivationRelation,
)
from cognitive_harness.storage.inmemory import InMemoryStorage
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer


def build_shared_root_graph() -> InMemoryStorage:
    """Graph A: all three supporting statements derive from one simulation run."""
    s = InMemoryStorage()

    # Single simulation source
    sim = KnowledgeObject(
        id="sim-run-1",
        type=KOType.MODEL_RESULT,
        title="Thermal simulation run — single source",
        content="Finite-element thermal simulation of core assembly at nominal load. "
                "Peak temperature 312 K, average gradient 4.2 K/mm, max stress 285 MPa.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="sim-engine", author="thermal-team", independent=True),
    )
    s.create_ko(sim)

    # Three statements derived from the same simulation
    stmt1 = KnowledgeObject(
        id="stmt-temp",
        type=KOType.FINDING,
        title="Peak temperature within limit",
        content="Simulation reports peak temperature 312 K, below 320 K limit.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="sim-engine", author="thermal-team"),
        derivation=DerivationRelation(
            derivation_type=DerivationType.MODELED,
            upstream_ko_ids=["sim-run-1"],
        ),
        relations=[Relation(to="sim-run-1", type=RelationType.DERIVED_FROM)],
    )
    stmt2 = KnowledgeObject(
        id="stmt-gradient",
        type=KOType.FINDING,
        title="Thermal gradient acceptable",
        content="Average thermal gradient 4.2 K/mm, below 5.0 K/mm threshold.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="sim-engine", author="thermal-team"),
        derivation=DerivationRelation(
            derivation_type=DerivationType.MODELED,
            upstream_ko_ids=["sim-run-1"],
        ),
        relations=[Relation(to="sim-run-1", type=RelationType.DERIVED_FROM)],
    )
    stmt3 = KnowledgeObject(
        id="stmt-stress",
        type=KOType.FINDING,
        title="Stress below yield",
        content="Maximum stress 285 MPa, below 350 MPa yield strength.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="sim-engine", author="thermal-team"),
        derivation=DerivationRelation(
            derivation_type=DerivationType.MODELED,
            upstream_ko_ids=["sim-run-1"],
        ),
        relations=[Relation(to="sim-run-1", type=RelationType.DERIVED_FROM)],
    )
    s.create_ko(stmt1)
    s.create_ko(stmt2)
    s.create_ko(stmt3)

    # Conclusion supported by all three
    conc = KnowledgeObject(
        id="conc-thermal-safe",
        type=KOType.CONCLUSION,
        title="Core assembly thermally safe at nominal load",
        content="All thermal and stress metrics within acceptable limits based on simulation.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="analysis", author="review-team"),
    )
    s.create_ko(conc)

    # SUPPORTS edges: findings -> conclusion
    s.create_relation("stmt-temp", "conc-thermal-safe", RelationType.SUPPORTS)
    s.create_relation("stmt-gradient", "conc-thermal-safe", RelationType.SUPPORTS)
    s.create_relation("stmt-stress", "conc-thermal-safe", RelationType.SUPPORTS)

    return s


def build_independent_graph() -> InMemoryStorage:
    """Graph B: three supporting statements from three independent measurements."""
    s = InMemoryStorage()

    # Three independent measurement sources
    meas1 = KnowledgeObject(
        id="meas-thermocouple",
        type=KOType.OBSERVATION,
        title="Thermocouple reading — independent source A",
        content="Type-K thermocouple at core center: 310 K ± 2 K. "
                "Calibrated against NIST reference standard.",
        truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="thermocouple-array", author="metrology-lab", independent=True),
    )
    meas2 = KnowledgeObject(
        id="meas-ir-camera",
        type=KOType.OBSERVATION,
        title="IR camera surface profile — independent source B",
        content="Infrared thermal imaging shows average gradient 3.8 K/mm "
                "across visible surface. Camera calibrated per ISO 18434-1.",
        truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="ir-imaging-system", author="optics-lab", independent=True),
    )
    meas3 = KnowledgeObject(
        id="meas-strain-gauge",
        type=KOType.OBSERVATION,
        title="Strain gauge reading — independent source C",
        content="Ro-Rose strain gauge at critical section: equivalent stress 278 MPa. "
                "Calibrated per ASTM E2055.",
        truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="strain-gauge-array", author="mechanical-lab", independent=True),
    )
    s.create_ko(meas1)
    s.create_ko(meas2)
    s.create_ko(meas3)

    # Three statements derived from independent measurements
    # Use SOURCED_MATERIAL_DATA so grounding check passes (non-system source + independent provenance)
    stmt1 = KnowledgeObject(
        id="stmt-temp",
        type=KOType.FINDING,
        title="Peak temperature within limit",
        content="Simulation reports peak temperature 312 K, below 320 K limit.",
        truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="thermocouple-array", author="review-team", independent=True),
        relations=[Relation(to="meas-thermocouple", type=RelationType.DERIVED_FROM)],
    )
    stmt2 = KnowledgeObject(
        id="stmt-gradient",
        type=KOType.FINDING,
        title="Thermal gradient acceptable",
        content="Average thermal gradient 4.2 K/mm, below 5.0 K/mm threshold.",
        truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="ir-imaging-system", author="review-team", independent=True),
        relations=[Relation(to="meas-ir-camera", type=RelationType.DERIVED_FROM)],
    )
    stmt3 = KnowledgeObject(
        id="stmt-stress",
        type=KOType.FINDING,
        title="Stress below yield",
        content="Maximum stress 285 MPa, below 350 MPa yield strength.",
        truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="strain-gauge-array", author="review-team", independent=True),
        relations=[Relation(to="meas-strain-gauge", type=RelationType.DERIVED_FROM)],
    )
    s.create_ko(stmt1)
    s.create_ko(stmt2)
    s.create_ko(stmt3)

    # Conclusion supported by all three (same text as Graph A)
    conc = KnowledgeObject(
        id="conc-thermal-safe",
        type=KOType.CONCLUSION,
        title="Core assembly thermally safe at nominal load",
        content="All thermal and stress metrics within acceptable limits based on simulation.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="analysis", author="review-team"),
    )
    s.create_ko(conc)

    # SUPPORTS edges: findings -> conclusion
    s.create_relation("stmt-temp", "conc-thermal-safe", RelationType.SUPPORTS)
    s.create_relation("stmt-gradient", "conc-thermal-safe", RelationType.SUPPORTS)
    s.create_relation("stmt-stress", "conc-thermal-safe", RelationType.SUPPORTS)

    return s


def compute_and_export(storage: InMemoryStorage, label: str) -> dict:
    """Run warrant analysis and export a structured record."""
    wa = WarrantAnalyzer(storage)
    result = wa.compute_warrant("conc-thermal-safe")
    jp = wa.storage.get_justification_path("conc-thermal-safe")

    # Collect evidence root IDs for each supporting KO
    evidence_roots = {}
    if result.independence:
        for ev_id in result.independence.evidence_ids:
            roots = result.independence.root_sets.get(ev_id, set())
            evidence_roots[ev_id] = sorted(roots)

    # Gather anti-pattern diagnoses
    diagnoses = []
    for d in result.anti_pattern_diagnoses:
        diagnoses.append({
            "pattern": d.pattern.value,
            "offending_ko_ids": d.offending_ko_ids,
            "violated_condition": d.violated_condition,
        })

    return {
        "label": label,
        "conclusion_id": "conc-thermal-safe",
        "warrant_status": result.warrant_status.value,
        "supporting_kos": result.supporting_kos,
        "independent_kos": result.independent_kos,
        "dependent_kos": result.dependent_kos,
        "justification_path": jp,
        "independence": {
            "evidence_count": result.independence.evidence_count if result.independence else 0,
            "independent_root_count": result.independence.independent_root_count if result.independence else 0,
            "root_sets": evidence_roots,
            "shared_ancestors": {
                k: sorted(v) for k, v in (result.independence.shared_ancestors or {}).items()
            },
        },
        "anti_pattern_diagnoses": diagnoses,
        "conditional_assumptions": result.conditional_assumptions,
        # All KO IDs in the graph (for boundary test)
        "all_ko_ids": sorted([ko.id for ko in storage.list_all_kos()]),
    }
