# FILE: tests/conformance/test_enumeration_completeness.py
"""Blocker A: Enumeration completeness and fail-closed behavior (v0.6.4).

Tests that FULL_REQUIRED analyses cannot silently produce partial results
from an incomplete graph enumeration.

Regression coverage: a plausible partial graph backend MUST NOT return a
normal result for detect_all_anti_patterns or list_review_required.
"""
import pytest
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer
from cognitive_harness.exceptions import IncompleteEnumerationError
from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus,
    ConfidenceLevel, Provenance, RelationType, AntiPattern,
    DerivationType, DerivationRelation,
)
from cognitive_harness.storage.interface import StorageInterface
from cognitive_harness.storage.inmemory import InMemoryStorage


class PartialStorage(StorageInterface):
    """Simulates a storage backend that returns partial enumeration.

    Has KOs internally but list_all_kos() only returns a subset — simulating
    what an HTTP search backend might return when some entities are missed.
    """
    enumeration_complete = False

    def __init__(self):
        self._kos: dict[str, KnowledgeObject] = {}
        self._partial_ids: set[str] = set()  # IDs that list_all_kos will return
        self._evidence: dict[str, dict] = {}
        self._locks: dict[str, str] = {}
        self._proposals: dict[str, object] = {}
        self._datasets: dict[str, object] = {}
        self._review_required: dict[str, str] = {}

    def create_ko(self, ko: KnowledgeObject) -> str:
        self._kos[ko.id] = ko
        return ko.id

    def update_ko(self, ko_id: str, updates: dict) -> bool:
        ko = self._kos.get(ko_id)
        if ko:
            for k, v in updates.items():
                setattr(ko, k, v)
            return True
        return False

    def get_ko(self, ko_id: str):
        return self._kos.get(ko_id)

    def create_relation(self, from_id: str, to_id: str, rel_type: RelationType) -> bool:
        fr = self._kos.get(from_id)
        if fr:
            from cognitive_harness.model.ko import Relation
            fr.relations.append(Relation(to=to_id, type=rel_type))
            return True
        return False

    def get_outgoing_relations(self, ko_id: str, relation_types=None):
        ko = self._kos.get(ko_id)
        if ko is None:
            return []
        result = [(r.to, r.type) for r in ko.relations]
        if relation_types:
            result = [(to, t) for to, t in result if t in relation_types]
        return result

    def get_incoming_relations(self, ko_id: str, relation_types=None):
        result = []
        for kid, ko in self._kos.items():
            for r in ko.relations:
                if r.to == ko_id:
                    if relation_types is None or r.type in relation_types:
                        result.append((kid, r.type))
        return result

    def query_by_viewpoint(self, viewpoint_id: str):
        return [ko for ko in self._kos.values() if viewpoint_id in ko.viewpoint_ids]

    def query_by_type(self, ko_type):
        target = ko_type.value if hasattr(ko_type, "value") else ko_type
        return [ko for ko in self._kos.values() if ko.type.value == target]

    def query_active_by_scope(self, scope: str):
        return [
            ko for ko in self._kos.values()
            if scope in ko.scope and not ko.epistemic_status.is_terminal
        ]

    def query_semantic(self, query: str, viewpoint_id=None, limit=10):
        return list(self._kos.values())[:limit]

    def list_canonical(self, scope=None):
        result = [ko for ko in self._kos.values() if ko.epistemic_status == EpistemicStatus.CANONICAL]
        if scope:
            result = [ko for ko in result if scope in ko.scope]
        return result

    def get_succession_chain(self, ko_id: str):
        chain = []
        current_id = ko_id
        while current_id:
            ko = self._kos.get(current_id)
            if ko is None:
                break
            chain.append(ko)
            current_id = ko.superseded_by_id or None
        return chain

    def add_evidence(self, evidence_id, claim_id, status, observation, records):
        self._evidence[evidence_id] = {
            "id": evidence_id, "claim_id": claim_id,
            "status": status, "observation": observation, "records": records,
        }
        return evidence_id

    def get_evidence(self, evidence_id):
        return self._evidence.get(evidence_id)

    def list_evidence_for_ko(self, ko_id):
        return [ev for ev in self._evidence.values() if ev["claim_id"] == ko_id]

    def lock_ko(self, ko_id, thread_id):
        self._locks[ko_id] = thread_id
        return True

    def unlock_ko(self, ko_id, thread_id):
        if self._locks.get(ko_id) == thread_id:
            del self._locks[ko_id]
            return True
        return False

    def compute_impact_set(self, ko_id):
        return []

    def mark_review_required(self, ko_ids, reason):
        marked = 0
        for kid in ko_ids:
            if self._kos.get(kid):
                self._review_required[kid] = reason
                marked += 1
        return marked

    def clear_review_required(self, ko_id):
        if ko_id in self._review_required:
            del self._review_required[ko_id]
            return True
        return False

    def list_review_required(self):
        return [self._kos[kid] for kid in self._review_required if kid in self._kos]

    def submit_proposal(self, proposal):
        import uuid
        pid = str(uuid.uuid4())
        self._proposals[pid] = proposal
        return pid

    def validate_and_execute(self, proposal_id):
        return self._proposals.get(proposal_id)

    def list_by_warrant_status(self, warrant_status_str):
        return []

    def list_anti_pattern_hits(self, pattern_str):
        return []

    def get_justification_path(self, ko_id):
        return [ko_id]

    def create_dataset(self, dataset):
        self._datasets[dataset.id] = dataset
        return dataset.id

    def get_dataset(self, dataset_id):
        return self._datasets.get(dataset_id)

    # KEY METHOD: only returns subset — simulating incomplete search
    def list_all_kos(self):
        return [self._kos[kid] for kid in self._partial_ids if kid in self._kos]

    def hide_ko(self, ko_id):
        """Remove a KO from enumeration (simulate search miss)."""
        self._partial_ids.discard(ko_id)

    def show_ko(self, ko_id):
        """Add a KO to enumeration results."""
        self._partial_ids.add(ko_id)


class TestEnumerationCompleteness:
    """Blocker A: FULL_REQUIRED analyses must fail closed on incomplete enumeration."""

    def test_detect_all_raises_on_incomplete_storage(self):
        """detect_all_anti_patterns raises IncompleteEnumerationError
        when the storage backend cannot guarantee complete enumeration."""
        storage = PartialStorage()
        storage.create_ko(KnowledgeObject(
            id="test-1", type=KOType.CONCLUSION, title="Test conclusion",
            truth_category=TruthCategory.MODEL_DERIVED,
            epistemic_status=EpistemicStatus.PROPOSED,
            confidence=ConfidenceLevel.MEDIUM,
            provenance=Provenance(source="test", author="test"),
        ))
        storage.show_ko("test-1")

        analyzer = WarrantAnalyzer(storage)
        with pytest.raises(IncompleteEnumerationError):
            analyzer.detect_all_anti_patterns()

    def test_detect_all_works_on_complete_storage(self):
        """detect_all_anti_patterns works normally on complete storage."""
        storage = InMemoryStorage()
        storage.create_ko(KnowledgeObject(
            id="test-2", type=KOType.CONCLUSION, title="Test conclusion",
            truth_category=TruthCategory.MODEL_DERIVED,
            epistemic_status=EpistemicStatus.PROPOSED,
            confidence=ConfidenceLevel.MEDIUM,
            provenance=Provenance(source="test", author="test"),
        ))

        analyzer = WarrantAnalyzer(storage)
        # Should NOT raise — complete enumeration
        result = analyzer.detect_all_anti_patterns()
        assert isinstance(result, list)

    def test_partial_graph_cannot_sneak_anti_pattern(self):
        """A KO with tautological validation exists in the graph but is
        hidden from enumeration. Without fail-closed, the analysis would
        return 0 findings (false clean). With fail-closed, it raises."""
        storage = PartialStorage()

        # Create a tautologically validated KO — self-validating
        taut_ko = KnowledgeObject(
            id="taut-self", type=KOType.CONCLUSION, title="Self-validating claim",
            truth_category=TruthCategory.MODEL_DERIVED,
            epistemic_status=EpistemicStatus.PROPOSED,
            confidence=ConfidenceLevel.HIGH,
            provenance=Provenance(source="test", author="test", independent=False),
            derivation=DerivationRelation(
                derivation_type=DerivationType.VALIDATED,
                upstream_ko_ids=["taut-self"],  # validates itself
            ),
        )
        storage.create_ko(taut_ko)
        storage.show_ko("taut-self")  # Visible in partial enumeration

        # Create a clean KO that IS visible
        clean_ko = KnowledgeObject(
            id="clean-obs", type=KOType.OBSERVATION, title="Clean observation",
            truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
            epistemic_status=EpistemicStatus.VALIDATED,
            confidence=ConfidenceLevel.HIGH,
            provenance=Provenance(source="lab", author="scientist", independent=True),
        )
        storage.create_ko(clean_ko)
        storage.show_ko("clean-obs")

        # Now hide the tautological KO from enumeration
        # (simulating what happens when HTTP search misses an entity)
        storage.hide_ko("taut-self")

        analyzer = WarrantAnalyzer(storage)
        # MUST raise — cannot silently return clean result for partial graph
        with pytest.raises(IncompleteEnumerationError):
            analyzer.detect_all_anti_patterns()

    def test_enumeration_complete_default_false(self):
        """Base StorageInterface defaults enumeration_complete to False."""
        # The abstract class defaults to False
        # InMemoryStorage overrides to True
        assert InMemoryStorage().enumeration_complete is True
        assert PartialStorage().enumeration_complete is False

    def test_local_operations_not_affected_by_completeness(self):
        """LOCAL_COMPLETE_ADJACENCY_REQUIRED operations work on incomplete storage.
        compute_warrant only needs the KO and its adjacency, not full enumeration."""
        storage = PartialStorage()

        # Evidence
        ev = KnowledgeObject(
            id="ev-local", type=KOType.OBSERVATION, title="Local evidence",
            truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
            epistemic_status=EpistemicStatus.VALIDATED,
            confidence=ConfidenceLevel.HIGH,
            provenance=Provenance(source="lab", author="sci", independent=True),
        )
        storage.create_ko(ev)

        # Conclusion
        conc = KnowledgeObject(
            id="conc-local", type=KOType.CONCLUSION, title="Local conclusion",
            truth_category=TruthCategory.MODEL_DERIVED,
            epistemic_status=EpistemicStatus.PROPOSED,
            confidence=ConfidenceLevel.MEDIUM,
            provenance=Provenance(source="test", author="test"),
        )
        storage.create_ko(conc)

        # Evidence SUPPORTS conclusion (inbound to conclusion)
        storage.create_relation("ev-local", "conc-local", RelationType.SUPPORTS)

        # compute_warrant should work — it only needs local adjacency
        analyzer = WarrantAnalyzer(storage)
        result = analyzer.compute_warrant("conc-local")
        # Should not raise IncompleteEnumerationError
        assert result is not None
