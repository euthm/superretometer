# FILE: transports/tests/test_evidence_lookup_fix.py
"""Regression tests for list_evidence_for_ko ID resolution fix.

The bug: evidence KOs created with claim_id = Memory UUID, but after
adopt_existing_ko the claim's .id is the CH logical ID.  The content-level
comparison in list_evidence_for_ko failed, returning zero results.

Fix: list_evidence_for_ko resolves both claim.id (CH) and claim_uuid (Memory)
and checks ev["claim_id"] against the set of known identifiers.
get_evidence prefers the graph edge's CH ID over the content-level claim_id.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from cognitive_harness.model.ko import KnowledgeObject, KOType, EpistemicStatus
from cognitive_harness.model.ko import Relation, RelationType


@pytest.fixture
def mock_adapter():
    """Minimal MemoryAdapter mock with the fixed methods."""
    from transports.memory_adapter import MemoryAdapter

    adapter = MagicMock(spec=MemoryAdapter)
    adapter._evidence = {}

    # Patch the methods we need — use real implementations
    adapter.list_evidence_for_ko = lambda kid: MemoryAdapter.list_evidence_for_ko(adapter, kid)
    adapter.get_evidence = lambda kid: MemoryAdapter.get_evidence(adapter, kid)
    return adapter


class TestEvidenceLookupMixedIdentifiers:
    """Evidence KOs created with Memory UUID claim_id, looked up by CH ID."""

    def test_evidence_by_ch_id_after_adoption(self, mock_adapter):
        """CP-010 scenario: evidence claim_id is Memory UUID, lookup by CH ID."""
        claim = KnowledgeObject(
            id="cp-010-connector-liveness",
            type=KOType.REQUIREMENT,
            title="CP-010",
            evidence_ids=["24a4b7ef-1a1b-4152-8870-ae12266a2d41"],
        )
        evidence_ko = KnowledgeObject(
            id="24a4b7ef-1a1b-4152-8870-ae12266a2d41",
            type=KOType.EVIDENCE_ITEM,
            title="CP-010 spec",
            content={"claim_id": "cc24d523-memory-uuid", "observation": "spec defines topics"},
            relations=[Relation(to="cp-010-connector-liveness", type=RelationType.SUPPORTS)],
        )

        mock_adapter.get_ko = lambda kid: claim if kid in ("cp-010-connector-liveness", "cc24d523-memory-uuid") else evidence_ko if kid == "24a4b7ef-1a1b-4152-8870-ae12266a2d41" else None
        mock_adapter._resolve_ch_id = lambda kid: "cc24d523-memory-uuid" if kid == "cp-010-connector-liveness" else kid
        mock_adapter.get_incoming_relations = lambda kid, rt: [("24a4b7ef-1a1b-4152-8870-ae12266a2d41", RelationType.SUPPORTS)]

        results = mock_adapter.list_evidence_for_ko("cp-010-connector-liveness")
        assert len(results) == 1
        assert results[0]["id"] == "24a4b7ef-1a1b-4152-8870-ae12266a2d41"

    def test_evidence_by_memory_uuid(self, mock_adapter):
        """Same evidence, looked up by Memory UUID — should also work."""
        claim = KnowledgeObject(
            id="cp-010-connector-liveness",
            type=KOType.REQUIREMENT,
            title="CP-010",
            evidence_ids=["24a4b7ef-1a1b-4152-8870-ae12266a2d41"],
        )
        evidence_ko = KnowledgeObject(
            id="24a4b7ef-1a1b-4152-8870-ae12266a2d41",
            type=KOType.EVIDENCE_ITEM,
            title="CP-010 spec",
            content={"claim_id": "cc24d523-memory-uuid"},
            relations=[Relation(to="cp-010-connector-liveness", type=RelationType.SUPPORTS)],
        )

        mock_adapter.get_ko = lambda kid: claim if kid in ("cp-010-connector-liveness", "cc24d523-memory-uuid") else evidence_ko if kid == "24a4b7ef-1a1b-4152-8870-ae12266a2d41" else None
        mock_adapter._resolve_ch_id = lambda kid: "cc24d523-memory-uuid" if kid == "cp-010-connector-liveness" else kid
        mock_adapter.get_incoming_relations = lambda kid, rt: [("24a4b7ef-1a1b-4152-8870-ae12266a2d41", RelationType.SUPPORTS)]

        results = mock_adapter.list_evidence_for_ko("cc24d523-memory-uuid")
        assert len(results) == 1

    def test_evidence_graph_edge_prefers_ch_id(self, mock_adapter):
        """get_evidence should prefer graph edge CH ID over content Memory UUID."""
        evidence_ko = KnowledgeObject(
            id="ev-001",
            type=KOType.EVIDENCE_ITEM,
            title="Test evidence",
            content={"claim_id": "memory-uuid-123", "observation": "test"},
            relations=[Relation(to="cp-010-connector-liveness", type=RelationType.SUPPORTS)],
        )

        mock_adapter.get_ko = lambda kid: evidence_ko if kid == "ev-001" else None

        ev = mock_adapter.get_evidence("ev-001")
        assert ev is not None
        assert ev["claim_id"] == "cp-010-connector-liveness"

    def test_evidence_no_graph_edge_uses_content(self, mock_adapter):
        """Without graph edge, fall back to content-level claim_id."""
        evidence_ko = KnowledgeObject(
            id="ev-002",
            type=KOType.EVIDENCE_ITEM,
            title="Orphan evidence",
            content={"claim_id": "memory-uuid-456"},
            relations=[],
        )

        mock_adapter.get_ko = lambda kid: evidence_ko if kid == "ev-002" else None

        ev = mock_adapter.get_evidence("ev-002")
        assert ev is not None
        assert ev["claim_id"] == "memory-uuid-456"

    def test_evidence_no_content_no_edge_empty_string(self, mock_adapter):
        """Neither content nor edge — claim_id is empty string."""
        evidence_ko = KnowledgeObject(
            id="ev-003",
            type=KOType.EVIDENCE_ITEM,
            title="Empty evidence",
            content={},
            relations=[],
        )

        mock_adapter.get_ko = lambda kid: evidence_ko if kid == "ev-003" else None

        ev = mock_adapter.get_evidence("ev-003")
        assert ev is not None
        assert ev["claim_id"] == ""

    def test_no_duplicate_evidence(self, mock_adapter):
        """Same evidence in claim.evidence_ids AND incoming SUPPORTS — deduplicated."""
        claim = KnowledgeObject(
            id="claim-1",
            type=KOType.REQUIREMENT,
            title="Claim",
            evidence_ids=["ev-001"],
        )
        evidence_ko = KnowledgeObject(
            id="ev-001",
            type=KOType.EVIDENCE_ITEM,
            title="Evidence",
            content={},
            relations=[Relation(to="claim-1", type=RelationType.SUPPORTS)],
        )

        mock_adapter.get_ko = lambda kid: claim if kid == "claim-1" else evidence_ko if kid == "ev-001" else None
        mock_adapter._resolve_ch_id = lambda kid: kid
        mock_adapter.get_incoming_relations = lambda kid, rt: [("ev-001", RelationType.SUPPORTS)]

        results = mock_adapter.list_evidence_for_ko("claim-1")
        assert len(results) == 1

    def test_mixed_memory_ch_lookup_consistent(self, mock_adapter):
        """3 evidence items, looked up by both Memory UUID and CH ID — same count."""
        claim = KnowledgeObject(
            id="cp-010-connector-liveness",
            type=KOType.REQUIREMENT,
            title="CP-010",
            evidence_ids=["ev-a", "ev-b", "ev-c"],
        )
        evidence_kos = {}
        for eid in ("ev-a", "ev-b", "ev-c"):
            evidence_kos[eid] = KnowledgeObject(
                id=eid,
                type=KOType.EVIDENCE_ITEM,
                title=f"Evidence {eid}",
                content={"claim_id": "cc24d523-memory-uuid"},
                relations=[Relation(to="cp-010-connector-liveness", type=RelationType.SUPPORTS)],
            )

        def get_ko(kid):
            if kid in ("cp-010-connector-liveness", "cc24d523-memory-uuid"):
                return claim
            return evidence_kos.get(kid)

        mock_adapter.get_ko = get_ko
        mock_adapter._resolve_ch_id = lambda kid: "cc24d523-memory-uuid" if kid == "cp-010-connector-liveness" else kid
        mock_adapter.get_incoming_relations = lambda kid, rt: [
            ("ev-a", RelationType.SUPPORTS),
            ("ev-b", RelationType.SUPPORTS),
            ("ev-c", RelationType.SUPPORTS),
        ]

        results_ch = mock_adapter.list_evidence_for_ko("cp-010-connector-liveness")
        results_uuid = mock_adapter.list_evidence_for_ko("cc24d523-memory-uuid")
        assert len(results_ch) == 3
        assert len(results_uuid) == 3
        assert {r["id"] for r in results_ch} == {r["id"] for r in results_uuid}

    def test_evidence_cache_invalidation(self, mock_adapter):
        """Cached evidence should still resolve correctly after first lookup."""
        claim = KnowledgeObject(
            id="claim-x",
            type=KOType.REQUIREMENT,
            title="Claim X",
            evidence_ids=["ev-1"],
        )
        evidence_ko = KnowledgeObject(
            id="ev-1",
            type=KOType.EVIDENCE_ITEM,
            title="Evidence 1",
            content={"claim_id": "uuid-x"},
            relations=[Relation(to="claim-x", type=RelationType.SUPPORTS)],
        )

        mock_adapter.get_ko = lambda kid: claim if kid in ("claim-x", "uuid-x") else evidence_ko if kid == "ev-1" else None
        mock_adapter._resolve_ch_id = lambda kid: "uuid-x" if kid == "claim-x" else kid
        mock_adapter.get_incoming_relations = lambda kid, rt: [("ev-1", RelationType.SUPPORTS)]

        # First lookup caches the evidence
        r1 = mock_adapter.list_evidence_for_ko("claim-x")
        # Second lookup uses cache — should still match
        r2 = mock_adapter.list_evidence_for_ko("claim-x")
        assert len(r1) == len(r2) == 1
