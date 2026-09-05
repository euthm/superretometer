"""Conformance test: supersession with history preservation.

A successor KO supersedes an older KO. The old KO remains in the graph,
marked SUPERSEDED. History is never deleted.
"""
from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus,
    ConfidenceLevel, RelationType, Provenance,
)
from cognitive_harness.storage.inmemory import InMemoryStorage


def test_supersession_preserves_history():
    """Create KO, create successor, supersede. Old KO persists as SUPERSEDED."""
    storage = InMemoryStorage()

    # Original KO
    spec_v1 = KnowledgeObject(
        id="spec-v1",
        type=KOType.SPECIFICATION,
        title="Specification v1: max stress 400 MPa",
        content="Original specification with 400 MPa limit.",
        truth_category=TruthCategory.DOCUMENTED_DECISION,
        epistemic_status=EpistemicStatus.CANONICAL,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="contract-v1", author="engineering", revision=1),
    )
    storage.create_ko(spec_v1)

    # Successor
    spec_v2 = KnowledgeObject(
        id="spec-v2",
        type=KOType.SPECIFICATION,
        title="Specification v2: max stress 450 MPa",
        content="Revised specification with 450 MPa limit after new testing.",
        truth_category=TruthCategory.DOCUMENTED_DECISION,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="contract-v2", author="engineering", revision=2),
    )
    storage.create_ko(spec_v2)

    # Supersede
    result = storage.supersede("spec-v1", "spec-v2")
    assert result is True, "Supersession should succeed"

    # Read old KO — should be SUPERSEDED
    old = storage.get_ko("spec-v1")
    assert old is not None, "Old KO must exist in graph"
    assert old.epistemic_status == EpistemicStatus.SUPERSEDED, \
        f"Old KO should be SUPERSEDED, got {old.epistemic_status.value}"
    assert old.superseded_by_id == "spec-v2", \
        f"superseded_by_id should be spec-v2, got {old.superseded_by_id}"

    # Read new KO — should reference old
    new = storage.get_ko("spec-v2")
    assert new is not None
    assert new.supersedes_id == "spec-v1", \
        f"supersedes_id should be spec-v1, got {new.supersedes_id}"
    assert new.epistemic_status != EpistemicStatus.SUPERSEDED

    # Succession chain
    chain = storage.get_succession_chain("spec-v1")
    assert len(chain) == 2, f"Chain should have 2 elements, got {len(chain)}"
    assert chain[0].id == "spec-v1"
    assert chain[1].id == "spec-v2"

    print("  PASS: Supersession preserves history")


def test_supersession_chain_length():
    """Three-version chain: v1 → v2 → v3."""
    storage = InMemoryStorage()

    for i in range(1, 4):
        storage.create_ko(KnowledgeObject(
            id=f"spec-v{i}",
            type=KOType.SPECIFICATION,
            title=f"Spec v{i}",
            content=f"Version {i}",
            truth_category=TruthCategory.DOCUMENTED_DECISION,
            epistemic_status=EpistemicStatus.CANONICAL if i == 1 else EpistemicStatus.VALIDATED,
            confidence=ConfidenceLevel.HIGH,
        ))

    storage.supersede("spec-v1", "spec-v2")
    storage.supersede("spec-v2", "spec-v3")

    chain = storage.get_succession_chain("spec-v1")
    assert len(chain) == 3
    assert [k.id for k in chain] == ["spec-v1", "spec-v2", "spec-v3"]
    assert chain[0].epistemic_status == EpistemicStatus.SUPERSEDED
    assert chain[1].epistemic_status == EpistemicStatus.SUPERSEDED
    assert chain[2].epistemic_status == EpistemicStatus.VALIDATED

    print("  PASS: Three-version succession chain")


def test_canonical_protection():
    """Cannot directly update a CANONICAL KO — must supersede."""
    storage = InMemoryStorage()
    storage.create_ko(KnowledgeObject(
        id="canonical-ko",
        type=KOType.OBSERVATION,
        title="Canonical observation",
        content="Original",
        truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
        epistemic_status=EpistemicStatus.CANONICAL,
        confidence=ConfidenceLevel.HIGH,
    ))
    # Direct update of canonical KO should fail
    result = storage.update_ko("canonical-ko", {"title": "Hacked"})
    assert result is False, "Cannot update canonical KO directly"

    # Verify unchanged
    ko = storage.get_ko("canonical-ko")
    assert ko.title == "Canonical observation"
    print("  PASS: Canonical protection enforced")


if __name__ == "__main__":
    test_supersession_preserves_history()
    test_supersession_chain_length()
    test_canonical_protection()
    print("\nSupersession conformance: PASS")
