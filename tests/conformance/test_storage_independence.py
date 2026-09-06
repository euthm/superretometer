"""Conformance test: storage independence.

WarrantAnalyzer must not depend on internal storage implementation
details like _kos.  It must only use the public StorageInterface.

This test uses a minimal StorageInterface implementation that has
NO _kos attribute — exercising list_all_kos() as the sole iteration
path.
"""
from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus,
    ConfidenceLevel, RelationType, Provenance, Relation, Dataset,
    WarrantStatus, AntiPattern, AntiPatternDiagnosis,
    JUSTIFICATION_RELATIONS,
)
from cognitive_harness.model.proposal import Proposal, ProposalType, ProposalState
from cognitive_harness.storage.interface import StorageInterface
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer
from typing import Any


class NoKosStorage(StorageInterface):
    """Minimal StorageInterface impl with NO _kos attribute.

    Proves that WarrantAnalyzer and consumers iterate KOs via
    list_all_kos() and not by reaching into internal state.
    """

    enumeration_complete = True  # _objects.values() returns every object

    def __init__(self):
        # Deliberately NOT named _kos
        self._objects: dict[str, KnowledgeObject] = {}
        self._evidence: dict[str, dict] = {}
        self._datasets: dict[str, Dataset] = {}
        self._locks: dict[str, str] = {}
        self._proposals: dict[str, Proposal] = {}

    # ── Explicitly break the old pattern ──────────────────────────────

    @property
    def _kos(self):
        """If any caller reaches for _kos, fail loudly."""
        raise AttributeError(
            "_kos does not exist on this storage backend. "
            "Use list_all_kos() instead."
        )

    # ── StorageInterface contract ─────────────────────────────────────

    def create_ko(self, ko: KnowledgeObject) -> str:
        self._objects[ko.id] = ko
        return ko.id

    def update_ko(self, ko_id: str, updates: dict[str, Any]) -> bool:
        ko = self._objects.get(ko_id)
        if ko is None or ko.is_canonical():
            return False
        for k, v in updates.items():
            if hasattr(ko, k):
                setattr(ko, k, v)
        return True

    def get_ko(self, ko_id: str) -> KnowledgeObject | None:
        return self._objects.get(ko_id)

    def create_relation(self, from_id: str, to_id: str, rel_type: RelationType) -> bool:
        fr = self._objects.get(from_id)
        if fr is None or self._objects.get(to_id) is None:
            return False
        fr.relations.append(Relation(to=to_id, type=rel_type))
        return True

    def get_outgoing_relations(self, ko_id: str, relation_types: frozenset | None = None) -> list[tuple[str, RelationType]]:
        ko = self._objects.get(ko_id)
        if ko is None:
            return []
        result = [(r.to, r.type) for r in ko.relations]
        if relation_types:
            result = [(to, t) for to, t in result if t in relation_types]
        return result

    def get_incoming_relations(self, ko_id: str, relation_types: frozenset | None = None) -> list[tuple[str, RelationType]]:
        result = []
        for kid, ko in self._objects.items():
            for r in ko.relations:
                if r.to == ko_id:
                    if relation_types is None or r.type in relation_types:
                        result.append((kid, r.type))
        return result

    def query_by_viewpoint(self, viewpoint_id: str) -> list[KnowledgeObject]:
        return [ko for ko in self._objects.values() if viewpoint_id in ko.viewpoint_ids]

    def query_by_type(self, ko_type) -> list[KnowledgeObject]:
        return [ko for ko in self._objects.values() if ko.type == ko_type]

    def query_active_by_scope(self, scope: str) -> list[KnowledgeObject]:
        return [
            ko for ko in self._objects.values()
            if scope in ko.scope and not ko.epistemic_status.is_terminal
        ]

    def query_semantic(self, query: str, viewpoint_id: str | None = None, limit: int = 10) -> list[KnowledgeObject]:
        q = query.lower()
        results = []
        for ko in self._objects.values():
            if viewpoint_id and viewpoint_id not in ko.viewpoint_ids:
                continue
            if q in ko.title.lower() or (isinstance(ko.content, str) and q in ko.content.lower()):
                results.append(ko)
        return results[:limit]

    def list_canonical(self, scope: str | None = None) -> list[KnowledgeObject]:
        cos = [ko for ko in self._objects.values() if ko.epistemic_status == EpistemicStatus.CANONICAL]
        if scope:
            cos = [ko for ko in cos if scope in ko.scope]
        return cos

    def get_succession_chain(self, ko_id: str) -> list[KnowledgeObject]:
        chain = []
        current_id = ko_id
        while current_id:
            ko = self._objects.get(current_id)
            if ko is None:
                break
            chain.append(ko)
            current_id = ko.supersedes_id or None
        chain.reverse()
        return chain

    def add_evidence(self, evidence_id: str, claim_id: str, status: str, observation: str, records: list[dict]) -> str:
        ev = {"id": evidence_id, "claim_id": claim_id, "status": status,
              "observation": observation, "records": records}
        self._evidence[evidence_id] = ev
        return evidence_id

    def get_evidence(self, evidence_id: str) -> dict | None:
        return self._evidence.get(evidence_id)

    def list_evidence_for_ko(self, ko_id: str) -> list[dict]:
        return [ev for ev in self._evidence.values() if ev["claim_id"] == ko_id]

    def lock_ko(self, ko_id: str, thread_id: str) -> bool:
        if ko_id in self._locks:
            return False
        self._locks[ko_id] = thread_id
        return True

    def unlock_ko(self, ko_id: str, thread_id: str) -> bool:
        if self._locks.get(ko_id) == thread_id:
            del self._locks[ko_id]
            return True
        return False

    def compute_impact_set(self, ko_id: str) -> list[str]:
        return []

    def mark_review_required(self, ko_ids: list[str], reason: str) -> int:
        count = 0
        for kid in ko_ids:
            ko = self._objects.get(kid)
            if ko and not ko.epistemic_status.is_terminal:
                ko.review_required = True
                ko.review_reason = reason
                count += 1
        return count

    def clear_review_required(self, ko_id: str) -> bool:
        ko = self._objects.get(ko_id)
        if ko and ko.review_required:
            ko.review_required = False
            ko.review_reason = ""
            return True
        return False

    def list_review_required(self) -> list[KnowledgeObject]:
        return [ko for ko in self._objects.values() if ko.review_required]

    def submit_proposal(self, proposal: Proposal) -> str:
        self._proposals[proposal.id] = proposal
        return proposal.id

    def validate_and_execute(self, proposal_id: str) -> Proposal:
        p = self._proposals.get(proposal_id)
        if p is None:
            raise ValueError(f"Proposal {proposal_id} not found")
        return p

    def list_by_warrant_status(self, warrant_status_str: str) -> list[KnowledgeObject]:
        return []

    def list_anti_pattern_hits(self, pattern_str: str) -> list[KnowledgeObject]:
        return [
            ko for ko in self._objects.values()
            if pattern_str in ko.anti_patterns
        ]

    def get_justification_path(self, ko_id: str) -> list[str]:
        visited: set[str] = set()
        queue = [ko_id]
        path = []
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            path.append(current)
            ko = self._objects.get(current)
            if ko is None:
                continue
            for rel in ko.relations:
                if rel.type in JUSTIFICATION_RELATIONS and rel.to not in visited:
                    queue.append(rel.to)
        return path

    def create_dataset(self, dataset: Dataset) -> str:
        self._datasets[dataset.id] = dataset
        return dataset.id

    def get_dataset(self, dataset_id: str) -> Dataset | None:
        return self._datasets.get(dataset_id)

    # ── The method that replaces _kos access ──────────────────────────

    def list_all_kos(self) -> list[KnowledgeObject]:
        return list(self._objects.values())


class TestStorageIndependence:
    """WarrantAnalyzer must work with any StorageInterface impl,
    not just InMemoryStorage."""

    def setup_method(self):
        self.storage = NoKosStorage()

    def _make_ko(self, ko_id: str, **kw) -> KnowledgeObject:
        ko = KnowledgeObject(
            id=ko_id,
            type=kw.get("type", KOType.OBSERVATION),
            title=kw.get("title", ko_id),
            content=kw.get("content"),
            truth_category=kw.get("truth_category", TruthCategory.SOURCED_MATERIAL_DATA),
            confidence=kw.get("confidence", ConfidenceLevel.MEDIUM),
            scope=kw.get("scope", ""),
            provenance=kw.get("provenance", Provenance(source="test", author="test")),
        )
        self.storage.create_ko(ko)
        return ko

    def test_iter_all_kos_no_kos_attr(self):
        """_iter_all_kos() must not crash when storage has no _kos."""
        self._make_ko("ko1")
        self._make_ko("ko2")

        wa = WarrantAnalyzer(self.storage)
        # This must NOT raise AttributeError on _kos
        kos = list(wa._iter_all_kos())
        assert len(kos) == 2
        ids = {ko.id for ko in kos}
        assert ids == {"ko1", "ko2"}

    def test_kos_attr_raises(self):
        """Accessing _kos on NoKosStorage must fail."""
        with pytest.raises(AttributeError, match="_kos"):
            _ = self.storage._kos

    def test_detect_all_anti_patterns_no_kos(self):
        """detect_all_anti_patterns iterates via list_all_kos(), not _kos."""
        self._make_ko("obs1", type=KOType.OBSERVATION)
        self._make_ko("obs2", type=KOType.OBSERVATION)
        self._make_ko("conc", type=KOType.CONCLUSION)
        self.storage.create_relation("obs1", "conc", RelationType.SUPPORTS)
        self.storage.create_relation("obs2", "conc", RelationType.SUPPORTS)

        wa = WarrantAnalyzer(self.storage)
        # Must complete without touching _kos
        findings = wa.detect_all_anti_patterns()
        # Two independent sourced observations -> no anti-patterns
        assert isinstance(findings, list)

    def test_compute_warrant_no_kos(self):
        """compute_warrant works without _kos on storage."""
        self._make_ko("obs", truth_category=TruthCategory.SOURCED_MATERIAL_DATA)
        self._make_ko("conc", type=KOType.CONCLUSION, truth_category=TruthCategory.MODEL_DERIVED)
        # Evidence SUPPORTS conclusion (inbound to conclusion)
        self.storage.create_relation("obs", "conc", RelationType.SUPPORTS)

        wa = WarrantAnalyzer(self.storage)
        result = wa.compute_warrant("conc")
        assert result.conclusion_ko_id == "conc"
        # The justification path should include obs
        assert "obs" in result.supporting_kos

    def test_list_all_kos_contract(self):
        """list_all_kos returns all KOs including superseded/invalidated."""
        self._make_ko("active", epistemic_status=EpistemicStatus.VALIDATED)
        ko = self._make_ko("superseded", epistemic_status=EpistemicStatus.SUPERSEDED)
        self._make_ko("invalid", epistemic_status=EpistemicStatus.INVALIDATED)

        all_kos = self.storage.list_all_kos()
        assert len(all_kos) == 3
        ids = {ko.id for ko in all_kos}
        assert ids == {"active", "superseded", "invalid"}


# pytest is the canonical test runner
import pytest  # noqa: E402 — import at bottom for standalone execution

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
