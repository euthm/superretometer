"""Direction-semantics test suite (v0.6.4).

Tests that FAIL on v0.6.3 and PASS after the direction-aware fix.

Core bug in v0.6.3:
  create_relation(from_id, to_id, type) stores only on from_id.
  WarrantAnalyzer follows only outgoing edges.
  Therefore evidence -> SUPPORTS -> conclusion is invisible to warrant traversal.
"""
import pytest
from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus,
    ConfidenceLevel, RelationType, Provenance, Relation,
    DerivationType, DerivationRelation, JUSTIFICATION_INBOUND,
    JUSTIFICATION_OUTBOUND,
)
from cognitive_harness.storage.inmemory import InMemoryStorage
from cognitive_harness.storage.interface import StorageInterface
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer


# ── A. SUPPORTS: evidence -> conclusion must be discoverable ──────────

def test_supports_inbound_discovery():
    """evidence -> SUPPORTS -> conclusion.
    WarrantAnalyzer(conclusion) MUST discover the evidence.
    """
    storage = InMemoryStorage()

    storage.create_ko(KnowledgeObject(
        id="ev-1", type=KOType.OBSERVATION,
        title="Independent measurement",
        content="Measured value 42.0",
        truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="lab", author="lab", independent=True),
    ))

    storage.create_ko(KnowledgeObject(
        id="conc-1", type=KOType.CONCLUSION,
        title="Value is correct",
        content="Based on measurement.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="analysis", author="analyst", independent=False),
    ))

    # Normative: evidence SUPPORTS conclusion
    storage.create_relation("ev-1", "conc-1", RelationType.SUPPORTS)

    wa = WarrantAnalyzer(storage)
    result = wa.compute_warrant("conc-1")

    # The evidence MUST be in the justification path
    assert "ev-1" in result.supporting_kos, \
        f"Evidence not discovered. Path: {result.supporting_kos}"

    # With independent evidence and no structural defects, should be warranted
    assert result.warrant_status.value == "warranted", \
        f"Expected warranted with independent evidence, got {result.warrant_status.value}"


# ── B. DEPENDS_ON: conclusion -> assumption must be discoverable ──────

def test_depends_on_outbound_discovery():
    """conclusion -> DEPENDS_ON -> assumption.
    WarrantAnalyzer(conclusion) MUST discover the assumption.
    """
    storage = InMemoryStorage()

    storage.create_ko(KnowledgeObject(
        id="assumption-1", type=KOType.HYPOTHESIS,
        title="Material is homogeneous",
        content="Assumption for model.",
        truth_category=TruthCategory.ASSUMPTION,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="model", author="modeler", independent=False),
    ))

    storage.create_ko(KnowledgeObject(
        id="conc-2", type=KOType.CONCLUSION,
        title="Stress is within limits",
        content="Computed stress below yield.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="analysis", author="analyst"),
    ))

    # Normative: conclusion DEPENDS_ON assumption
    storage.create_relation("conc-2", "assumption-1", RelationType.DEPENDS_ON)

    wa = WarrantAnalyzer(storage)
    result = wa.compute_warrant("conc-2")

    assert "assumption-1" in result.supporting_kos, \
        f"Assumption not discovered. Path: {result.supporting_kos}"
    # Should be conditionally warranted (depends on assumption)
    assert result.warrant_status.value == "conditionally_warranted", \
        f"Expected conditionally_warranted, got {result.warrant_status.value}"


# ── C. No reverse duplicate required ──────────────────────────────────

def test_no_reverse_duplicate():
    """SUPPORTS must work WITHOUT also storing conclusion -> SUPPORTS -> evidence.
    This proves we're not using the workaround of storing reverse edges.
    """
    storage = InMemoryStorage()

    storage.create_ko(KnowledgeObject(
        id="ev-3", type=KOType.OBSERVATION,
        title="Evidence",
        content="Test evidence",
        truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="lab", author="lab", independent=True),
    ))

    storage.create_ko(KnowledgeObject(
        id="conc-3", type=KOType.CONCLUSION,
        title="Conclusion",
        content="Test conclusion",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="analysis", author="analyst", independent=False),
    ))

    # ONLY evidence -> SUPPORTS -> conclusion
    storage.create_relation("ev-3", "conc-3", RelationType.SUPPORTS)

    # Verify: conclusion has NO outgoing SUPPORTS relations
    conc = storage.get_ko("conc-3")
    outgoing_supports = [r for r in conc.relations if r.type == RelationType.SUPPORTS]
    assert len(outgoing_supports) == 0, "Conclusion should have no outgoing SUPPORTS"

    wa = WarrantAnalyzer(storage)
    result = wa.compute_warrant("conc-3")
    assert "ev-3" in result.supporting_kos, \
        "Evidence must be discoverable without reverse edge"


# ── D. VALIDATES: validator -> conclusion must be discoverable ────────

def test_validates_inbound():
    """Validator/evidence inbound to conclusion must be discoverable."""
    storage = InMemoryStorage()

    storage.create_ko(KnowledgeObject(
        id="validator-1", type=KOType.FINDING,
        title="Validation check passes",
        content="Output matches expected.",
        truth_category=TruthCategory.VALIDATION_RESULT,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="test-suite", author="tester", independent=True),
    ))

    storage.create_ko(KnowledgeObject(
        id="conc-4", type=KOType.CONCLUSION,
        title="Model is validated",
        content="Model passes validation.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="analysis", author="analyst", independent=False),
    ))

    # Validator VALIDATES conclusion
    storage.create_relation("validator-1", "conc-4", RelationType.VALIDATES)

    wa = WarrantAnalyzer(storage)
    result = wa.compute_warrant("conc-4")

    assert "validator-1" in result.supporting_kos, \
        f"Validator not discovered. Path: {result.supporting_kos}"


# ── E. Mixed graph: inbound SUPPORTS + outbound DEPENDS_ON ───────────

def test_mixed_graph():
    """A claim with inbound SUPPORTS and outbound DEPENDS_ON must produce
    one coherent justification path that includes both evidence and assumptions."""
    storage = InMemoryStorage()

    # Independent evidence
    storage.create_ko(KnowledgeObject(
        id="ev-mix", type=KOType.OBSERVATION,
        title="Independent evidence",
        content="Measured.",
        truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="lab", author="lab", independent=True),
    ))

    # Assumption
    storage.create_ko(KnowledgeObject(
        id="assumption-mix", type=KOType.HYPOTHESIS,
        title="Boundary condition",
        content="Steady-state assumption.",
        truth_category=TruthCategory.ASSUMPTION,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="model", author="modeler"),
    ))

    # Conclusion
    storage.create_ko(KnowledgeObject(
        id="conc-mix", type=KOType.CONCLUSION,
        title="Combined conclusion",
        content="Evidence supports, assumption required.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="analysis", author="analyst"),
    ))

    # Inbound: evidence SUPPORTS conclusion
    storage.create_relation("ev-mix", "conc-mix", RelationType.SUPPORTS)
    # Outbound: conclusion DEPENDS_ON assumption
    storage.create_relation("conc-mix", "assumption-mix", RelationType.DEPENDS_ON)

    wa = WarrantAnalyzer(storage)
    result = wa.compute_warrant("conc-mix")

    # Both must be in the path
    assert "ev-mix" in result.supporting_kos, \
        f"Evidence missing from mixed graph path: {result.supporting_kos}"
    assert "assumption-mix" in result.supporting_kos, \
        f"Assumption missing from mixed graph path: {result.supporting_kos}"

    # Should be conditionally warranted (has assumption)
    assert result.warrant_status in (
        "conditionally_warranted", "warranted"
    ), f"Got {result.warrant_status.value}"


# ── F. Impact traversal uses correct direction ────────────────────────

def test_impact_traversal_direction():
    """Impact/downstream traversal must use correct direction and must not
    simply reuse warrant traversal backwards."""
    storage = InMemoryStorage()

    # Evidence
    storage.create_ko(KnowledgeObject(
        id="ev-imp", type=KOType.OBSERVATION,
        title="Material property",
        content="Yield stress: 450 MPa",
        truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
        epistemic_status=EpistemicStatus.CANONICAL,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="lab", author="lab", independent=True),
    ))

    # Conclusion depends on evidence
    storage.create_ko(KnowledgeObject(
        id="conc-imp", type=KOType.CONCLUSION,
        title="Design safe",
        content="Stress below yield.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="design", author="designer"),
    ))

    # Evidence SUPPORTS conclusion
    storage.create_relation("ev-imp", "conc-imp", RelationType.SUPPORTS)

    # If evidence changes, conclusion should be impacted
    impact = storage.compute_impact_set("ev-imp")
    assert "conc-imp" in impact, \
        f"Conclusion should be impacted when evidence changes. Impact: {impact}"

    # If conclusion changes, evidence should NOT be impacted
    impact_rev = storage.compute_impact_set("conc-imp")
    assert "ev-imp" not in impact_rev, \
        f"Evidence should NOT be impacted when conclusion changes. Impact: {impact_rev}"


# ── G. Backend independence ────────────────────────────────────────────

def test_direction_backend_independence():
    """Same semantics must work on a storage backend without _kos."""
    import sys, pathlib
    conformance_dir = pathlib.Path(__file__).parent / "conformance"
    sys.path.insert(0, str(conformance_dir))
    from test_storage_independence import NoKosStorage

    storage = NoKosStorage()

    storage.create_ko(KnowledgeObject(
        id="ev-no-kos", type=KOType.OBSERVATION,
        title="Evidence",
        content="Test",
        truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="lab", author="lab", independent=True),
    ))

    storage.create_ko(KnowledgeObject(
        id="conc-no-kos", type=KOType.CONCLUSION,
        title="Conclusion",
        content="Test conclusion",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="analysis", author="analyst", independent=False),
    ))

    storage.create_relation("ev-no-kos", "conc-no-kos", RelationType.SUPPORTS)

    wa = WarrantAnalyzer(storage)
    result = wa.compute_warrant("conc-no-kos")
    assert "ev-no-kos" in result.supporting_kos, \
        "Direction-aware traversal must work on backend without _kos"


# ── H. Cycle detection with direction-aware traversal ──────────────────

def test_direction_aware_cycle_detection():
    """Direction-aware traversal must detect real justification cycles
    and must not invent cycles from opposite-direction relation lookup."""
    storage = InMemoryStorage()

    # Real cycle: A SUPPORTS B SUPPORTS A
    storage.create_ko(KnowledgeObject(
        id="cycle-a", type=KOType.HYPOTHESIS,
        title="Claim A",
        content="A supports B.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="model", author="analyst", independent=True),
    ))

    storage.create_ko(KnowledgeObject(
        id="cycle-b", type=KOType.HYPOTHESIS,
        title="Claim B",
        content="B supports A.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="model", author="analyst", independent=True),
    ))

    # A SUPPORTS B
    storage.create_relation("cycle-a", "cycle-b", RelationType.SUPPORTS)
    # B SUPPORTS A
    storage.create_relation("cycle-b", "cycle-a", RelationType.SUPPORTS)

    wa = WarrantAnalyzer(storage)
    result = wa.compute_warrant("cycle-a")

    # Both A and B should be in path (cycle)
    assert "cycle-b" in result.supporting_kos, \
        f"Cycle partner not discovered: {result.supporting_kos}"
    # Should be unwarranted due to cycle
    assert result.warrant_status.value == "unwarranted", \
        f"Circular should be unwarranted, got {result.warrant_status.value}"


def test_no_false_cycle_from_mixed_direction():
    """A valid chain with mixed inbound/outbound relations must NOT
    be detected as a cycle."""
    storage = InMemoryStorage()

    # Evidence SUPPORTS conclusion (inbound)
    storage.create_ko(KnowledgeObject(
        id="ev-valid", type=KOType.OBSERVATION,
        title="Evidence",
        content="Independent.",
        truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="lab", author="lab", independent=True),
    ))

    # Assumption
    storage.create_ko(KnowledgeObject(
        id="assumption-valid", type=KOType.HYPOTHESIS,
        title="Assumption",
        content="Boundary condition.",
        truth_category=TruthCategory.ASSUMPTION,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="model", author="modeler"),
    ))

    # Conclusion: supported by evidence, depends on assumption
    storage.create_ko(KnowledgeObject(
        id="conc-valid", type=KOType.CONCLUSION,
        title="Valid conclusion",
        content="Supported and dependent.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="analysis", author="analyst"),
    ))

    # Inbound: ev SUPPORTS conc
    storage.create_relation("ev-valid", "conc-valid", RelationType.SUPPORTS)
    # Outbound: conc DEPENDS_ON assumption
    storage.create_relation("conc-valid", "assumption-valid", RelationType.DEPENDS_ON)

    wa = WarrantAnalyzer(storage)
    result = wa.compute_warrant("conc-valid")

    # No cycle should be detected
    circular = [d for d in result.anti_pattern_diagnoses
                if d.pattern.value == "circular_dependency"]
    assert len(circular) == 0, \
        f"False cycle detected on valid mixed-direction graph: {circular}"


# ── I. Storage contract: direction-aware access ────────────────────────

def test_storage_direction_methods():
    """StorageInterface must have get_incoming_relations and get_outgoing_relations."""
    storage = InMemoryStorage()

    storage.create_ko(KnowledgeObject(
        id="src", type=KOType.OBSERVATION,
        title="Source", content="S",
        truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
        provenance=Provenance(source="test", author="test"),
    ))

    storage.create_ko(KnowledgeObject(
        id="tgt", type=KOType.CONCLUSION,
        title="Target", content="T",
        truth_category=TruthCategory.MODEL_DERIVED,
        provenance=Provenance(source="test", author="test"),
    ))

    storage.create_relation("src", "tgt", RelationType.SUPPORTS)

    # Outgoing from src: should have SUPPORTS -> tgt
    outgoing = storage.get_outgoing_relations("src")
    assert ("tgt", RelationType.SUPPORTS) in outgoing

    # Outgoing from tgt: should be empty
    outgoing_tgt = storage.get_outgoing_relations("tgt")
    assert len(outgoing_tgt) == 0

    # Incoming to tgt: should have src SUPPORTS
    incoming = storage.get_incoming_relations("tgt")
    assert ("src", RelationType.SUPPORTS) in incoming

    # Incoming to src: should be empty
    incoming_src = storage.get_incoming_relations("src")
    assert len(incoming_src) == 0

    # Filtered
    incoming_filtered = storage.get_incoming_relations(
        "tgt", frozenset({RelationType.SUPPORTS})
    )
    assert len(incoming_filtered) == 1

    incoming_wrong_filter = storage.get_incoming_relations(
        "tgt", frozenset({RelationType.DEPENDS_ON})
    )
    assert len(incoming_wrong_filter) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
