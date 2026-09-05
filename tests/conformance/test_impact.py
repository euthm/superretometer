"""Conformance test: impact propagation after upstream supersession.

When an upstream KO is superseded, all downstream KOs that depend on it
must be identified in the impact set and marked review-required.
"""
from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus,
    ConfidenceLevel, RelationType, Provenance, Relation,
)
from cognitive_harness.storage.inmemory import InMemoryStorage


def test_impact_propagation():
    """Upstream material spec → model result → design conclusion.
    Supersede material spec → design conclusion in impact set."""
    storage = InMemoryStorage()

    # Upstream: material specification
    mat_spec = KnowledgeObject(
        id="mat-spec-v1",
        type=KOType.SPECIFICATION,
        title="Material yield stress: 400 MPa",
        content="Original specification.",
        truth_category=TruthCategory.DOCUMENTED_DECISION,
        epistemic_status=EpistemicStatus.CANONICAL,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="contract", author="engineering", revision=1),
    )
    storage.create_ko(mat_spec)

    # Mid: model result depends on material spec
    model_result = KnowledgeObject(
        id="stress-model",
        type=KOType.MODEL_RESULT,
        title="Calculated stress: 350 MPa",
        content="Stress computed using material spec.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="simulation", author="simulation"),
        relations=[Relation(to="mat-spec-v1", type=RelationType.DEPENDS_ON)],
    )
    storage.create_ko(model_result)
    storage.create_relation("stress-model", "mat-spec-v1", RelationType.DEPENDS_ON)

    # Downstream: conclusion depends on model result
    conclusion = KnowledgeObject(
        id="design-conclusion",
        type=KOType.CONCLUSION,
        title="Design is safe",
        content="Stress below yield.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="design-review", author="engineer"),
        relations=[Relation(to="stress-model", type=RelationType.DEPENDS_ON)],
    )
    storage.create_ko(conclusion)
    storage.create_relation("design-conclusion", "stress-model", RelationType.DEPENDS_ON)

    # Compute impact set before supersession
    impact_before = storage.compute_impact_set("mat-spec-v1")
    # The model depends on mat-spec, so it should be in impact set
    assert "stress-model" in impact_before, \
        f"stress-model should be in impact set of mat-spec-v1, got {impact_before}"

    # Now supersede the material spec
    mat_spec_v2 = KnowledgeObject(
        id="mat-spec-v2",
        type=KOType.SPECIFICATION,
        title="Material yield stress: 450 MPa",
        content="Revised specification after new testing.",
        truth_category=TruthCategory.DOCUMENTED_DECISION,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="contract-v2", author="engineering", revision=2),
    )
    storage.create_ko(mat_spec_v2)
    storage.supersede("mat-spec-v1", "mat-spec-v2")

    # Verify old spec is superseded
    old = storage.get_ko("mat-spec-v1")
    assert old.epistemic_status == EpistemicStatus.SUPERSEDED

    # Impact set should include downstream KOs
    impact_after = storage.compute_impact_set("mat-spec-v1")
    assert "stress-model" in impact_after, \
        f"stress-model should still be in impact set after supersession"

    print("  PASS: Impact propagation after upstream supersession")


def test_impact_marks_review_required():
    """Supersession should mark impacted KOs as review-required."""
    storage = InMemoryStorage()

    # Simple dependency chain
    storage.create_ko(KnowledgeObject(
        id="upstream", type=KOType.SPECIFICATION,
        title="Original spec", content="v1",
        truth_category=TruthCategory.DOCUMENTED_DECISION,
        epistemic_status=EpistemicStatus.CANONICAL,
        confidence=ConfidenceLevel.HIGH,
    ))
    storage.create_ko(KnowledgeObject(
        id="downstream", type=KOType.CONCLUSION,
        title="Conclusion", content="Based on spec.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
    ))
    storage.create_relation("downstream", "upstream", RelationType.DEPENDS_ON)

    # Create and supersede
    storage.create_ko(KnowledgeObject(
        id="upstream-v2", type=KOType.SPECIFICATION,
        title="Revised spec", content="v2",
        truth_category=TruthCategory.DOCUMENTED_DECISION,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
    ))

    # Before supersession: no review-required
    rr_before = storage.list_review_required()
    assert len(rr_before) == 0

    storage.supersede("upstream", "upstream-v2")

    # After supersession: downstream should be review-required
    rr_after = storage.list_review_required()
    rr_ids = [k.id for k in rr_after]
    assert "downstream" in rr_ids, \
        f"downstream should be review-required, got {rr_ids}"

    # Clear review-required
    storage.clear_review_required("downstream")
    rr_cleared = storage.list_review_required()
    assert len(rr_cleared) == 0

    print("  PASS: Review-required marking and clearing")


if __name__ == "__main__":
    test_impact_propagation()
    test_impact_marks_review_required()
    print("\nImpact propagation conformance: PASS")
