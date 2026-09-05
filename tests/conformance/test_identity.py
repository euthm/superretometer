"""Conformance test: logical identity.

Verify that Knowledge Objects maintain stable logical IDs
independent of storage backend, session, or process.
"""
from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus,
    ConfidenceLevel, RelationType, Provenance, Relation,
)
from cognitive_harness.storage.inmemory import InMemoryStorage


def test_logical_identity():
    """Create KO with logical ID, read back, verify ID unchanged."""
    storage = InMemoryStorage()
    ko = KnowledgeObject(
        id="my-stable-id",
        type=KOType.OBSERVATION,
        title="Stable identity test",
        content="Content",
        truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
    )
    ko_id = storage.create_ko(ko)
    assert ko_id == "my-stable-id", f"Expected 'my-stable-id', got {ko_id}"

    # Read back
    ko2 = storage.get_ko("my-stable-id")
    assert ko2 is not None
    assert ko2.id == "my-stable-id"
    assert ko2.type == KOType.OBSERVATION
    print("  PASS: Logical identity preserved")


def test_identity_across_operations():
    """Create KO, update it, read it — ID must remain stable through mutations."""
    storage = InMemoryStorage()
    ko_id = "mutability-test"
    storage.create_ko(KnowledgeObject(
        id=ko_id, type=KOType.OBSERVATION,
        title="Initial title", content="A",
        truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
    ))
    # Update
    storage.update_ko(ko_id, {"title": "Updated title"})
    # Read
    ko = storage.get_ko(ko_id)
    assert ko is not None
    assert ko.id == ko_id, f"ID changed: {ko.id} != {ko_id}"
    assert ko.title == "Updated title"
    print("  PASS: Identity stable through mutations")


if __name__ == "__main__":
    test_logical_identity()
    test_identity_across_operations()
    print("\nLogical identity conformance: PASS")
