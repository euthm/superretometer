"""Conformance test: circular justification detection.

A conclusion that depends (directly or indirectly) on itself must be
detected as UNWARRANTED with a CIRCULAR_DEPENDENCY diagnosis.
"""
from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus,
    ConfidenceLevel, RelationType, Provenance, Relation,
)
from cognitive_harness.storage.inmemory import InMemoryStorage
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer


def test_direct_circular():
    """A → SUPPORTS → B → SUPPORTS → A (direct cycle)."""
    storage = InMemoryStorage()

    ko_a = KnowledgeObject(
        id="ko-a", type=KOType.HYPOTHESIS,
        title="Hypothesis A",
        content="A supports B which supports A.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="model", author="analyst", independent=True),
        relations=[Relation(to="ko-b", type=RelationType.SUPPORTS)],
    )
    ko_b = KnowledgeObject(
        id="ko-b", type=KOType.HYPOTHESIS,
        title="Hypothesis B",
        content="B supports A which supports B.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="model", author="analyst", independent=True),
        relations=[Relation(to="ko-a", type=RelationType.SUPPORTS)],
    )
    storage.create_ko(ko_a)
    storage.create_ko(ko_b)
    storage.create_relation("ko-a", "ko-b", RelationType.SUPPORTS)
    storage.create_relation("ko-b", "ko-a", RelationType.SUPPORTS)

    wa = WarrantAnalyzer(storage)
    result = wa.compute_warrant("ko-a")
    assert result.warrant_status.value == "unwarranted", \
        f"Circular justification should be UNWARRANTED, got {result.warrant_status.value}"
    # Cycles are detected via DFS anti-pattern scan (CIRCULAR_DEPENDENCY diagnosis)
    circular_dxs = [d for d in result.anti_pattern_diagnoses
                     if d.pattern.value == "circular_dependency"]
    assert len(circular_dxs) > 0, \
        f"CIRCULAR_DEPENDENCY diagnosis should be found, got {[d.pattern.value for d in result.anti_pattern_diagnoses]}"

    print("  PASS: Direct circular dependency detected")


def test_indirect_circular():
    """A → B → C → A (3-node cycle)."""
    storage = InMemoryStorage()

    for name, next_target in [("ko-x", "ko-y"), ("ko-y", "ko-z"), ("ko-z", "ko-x")]:
        storage.create_ko(KnowledgeObject(
            id=name, type=KOType.HYPOTHESIS,
            title=f"Hypothesis {name}",
            content=f"{name} supports {next_target}.",
            truth_category=TruthCategory.MODEL_DERIVED,
            epistemic_status=EpistemicStatus.PROPOSED,
            confidence=ConfidenceLevel.MEDIUM,
            provenance=Provenance(source="model", author="analyst", independent=True),
            relations=[Relation(to=next_target, type=RelationType.SUPPORTS)],
        ))
        storage.create_relation(name, next_target, RelationType.SUPPORTS)

    wa = WarrantAnalyzer(storage)
    result = wa.compute_warrant("ko-x")
    assert result.warrant_status.value == "unwarranted", \
        f"Indirect circular should be UNWARRANTED, got {result.warrant_status.value}"
    circular_dxs = [d for d in result.anti_pattern_diagnoses
                     if d.pattern.value == "circular_dependency"]
    assert len(circular_dxs) > 0, "CIRCULAR_DEPENDENCY diagnosis expected"

    print("  PASS: Indirect circular dependency (3-node cycle) detected")


def test_no_false_positive_on_valid_chain():
    """A valid linear chain must NOT trigger circular detection."""
    storage = InMemoryStorage()

    # ev → supports → model → supports → conclusion
    storage.create_ko(KnowledgeObject(
        id="ev-base", type=KOType.OBSERVATION,
        title="Base evidence",
        content="Independent measurement.",
        truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
        epistemic_status=EpistemicStatus.CANONICAL,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="lab", author="lab", independent=True),
    ))
    storage.create_ko(KnowledgeObject(
        id="model-intermediate", type=KOType.MODEL_RESULT,
        title="Intermediate model",
        content="Derived from evidence.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="model", author="analyst", independent=False),
        relations=[Relation(to="ev-base", type=RelationType.DERIVED_FROM)],
    ))
    storage.create_ko(KnowledgeObject(
        id="conclusion-valid", type=KOType.CONCLUSION,
        title="Valid conclusion",
        content="Follows from chain.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="analysis", author="analyst"),
    ))
    storage.create_relation("model-intermediate", "ev-base", RelationType.DERIVED_FROM)
    # Model SUPPORTS conclusion (inbound)
    storage.create_relation("model-intermediate", "conclusion-valid", RelationType.SUPPORTS)

    wa = WarrantAnalyzer(storage)
    result = wa.compute_warrant("conclusion-valid")
    circular_dxs = [d for d in result.anti_pattern_diagnoses
                     if d.pattern.value == "circular_dependency"]
    assert len(circular_dxs) == 0, \
        f"No circular dependency on valid chain, got {[d.pattern.value for d in result.anti_pattern_diagnoses]}"

    print("  PASS: No false positive on valid linear chain")


if __name__ == "__main__":
    test_direct_circular()
    test_indirect_circular()
    test_no_false_positive_on_valid_chain()
    print("\nCircular justification conformance: PASS")
