# FILE: tests/conformance/test_truth_category_and_contradicts.py
"""Regression tests for truth_category passthrough and contradiction detection.

Covers:
- Explicit truth_category through Proposal -> execute -> get_ko readback
- Missing truth_category defaults to ASSUMPTION
- Invalid truth_category rejected with clear error
- CONTRADICTS edges detected by warrant analyzer
- CONTRADICTS not confused with SUPPORTS in justification_path
- Evidence relation_type (supports/contradicts) in add_evidence
"""
import pytest
from dataclasses import dataclass, field
from typing import Any

from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus,
    ConfidenceLevel, RelationType, WarrantStatus,
    JUSTIFICATION_INBOUND, CONTRADICTION_INBOUND,
)
from cognitive_harness.model.proposal import Proposal, ProposalType
from cognitive_harness.storage.inmemory import InMemoryStorage
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer


class FakeProposal:
    """Minimal proposal-like object for testing validate_and_execute paths."""
    pass


# ── Helpers ───────────────────────────────────────────────────────────────

def mk_ko(ko_id: str, title: str = "", tc: TruthCategory = TruthCategory.ASSUMPTION,
          ktype: KOType = KOType.HYPOTHESIS) -> KnowledgeObject:
    return KnowledgeObject(
        id=ko_id, type=ktype, title=title, truth_category=tc,
        confidence=ConfidenceLevel.SPECULATIVE,
    )


# ── TruthCategory defaults ────────────────────────────────────────────────

class TestTruthCategoryDefaults:
    """Verify truth_category defaults are preserved."""

    def test_ko_default_is_assumption(self):
        ko = KnowledgeObject(id="x", type=KOType.HYPOTHESIS, title="t")
        assert ko.truth_category == TruthCategory.ASSUMPTION

    def test_ko_explicit_physical_observation(self):
        ko = KnowledgeObject(id="x", type=KOType.OBSERVATION,
                             title="t", truth_category=TruthCategory.PHYSICAL_OBSERVATION)
        assert ko.truth_category == TruthCategory.PHYSICAL_OBSERVATION

    def test_ko_explicit_validation_result(self):
        ko = KnowledgeObject(id="x", type=KOType.OBSERVATION,
                             title="t", truth_category=TruthCategory.VALIDATION_RESULT)
        assert ko.truth_category == TruthCategory.VALIDATION_RESULT

    def test_all_truth_categories_valid(self):
        """All TruthCategory enum values are parseable."""
        for tc_name in TruthCategory:
            parsed = TruthCategory(tc_name.value)
            assert parsed == tc_name


# ── TruthCategory passthrough via InMemoryStorage ─────────────────────────

class TestTruthCategoryPassthrough:
    """TruthCategory flows through create_ko -> get_ko roundtrip."""

    def test_explicit_tc_roundtrip(self):
        storage = InMemoryStorage()
        ko = mk_ko("tc-obs", "Observation", TruthCategory.PHYSICAL_OBSERVATION, KOType.OBSERVATION)
        storage.create_ko(ko)
        retrieved = storage.get_ko("tc-obs")
        assert retrieved is not None
        assert retrieved.truth_category == TruthCategory.PHYSICAL_OBSERVATION

    def test_missing_tc_roundtrip_defaults_assumption(self):
        storage = InMemoryStorage()
        ko = KnowledgeObject(id="tc-default", type=KOType.HYPOTHESIS, title="Default TC")
        assert ko.truth_category == TruthCategory.ASSUMPTION
        storage.create_ko(ko)
        retrieved = storage.get_ko("tc-default")
        assert retrieved is not None
        assert retrieved.truth_category == TruthCategory.ASSUMPTION

    def test_validation_result_tc_roundtrip(self):
        storage = InMemoryStorage()
        ko = mk_ko("tc-val", "Validation", TruthCategory.VALIDATION_RESULT, KOType.OBSERVATION)
        storage.create_ko(ko)
        retrieved = storage.get_ko("tc-val")
        assert retrieved is not None
        assert retrieved.truth_category == TruthCategory.VALIDATION_RESULT

    def test_all_tc_values_roundtrip(self):
        storage = InMemoryStorage()
        for tc in TruthCategory:
            ko = mk_ko(f"tc-{tc.value}", tc.value, tc)
            storage.create_ko(ko)
            retrieved = storage.get_ko(f"tc-{tc.value}")
            assert retrieved is not None, f"Failed for {tc.value}"
            assert retrieved.truth_category == tc, f"Mismatch for {tc.value}: got {retrieved.truth_category}"


# ── Proposal truth_category ───────────────────────────────────────────────

class TestProposalTruthCategory:
    """Proposal carries truth_category through to KO creation."""

    def test_proposal_has_truth_category_field(self):
        p = Proposal()
        assert p.ko_truth_category is None

    def test_proposal_explicit_truth_category(self):
        p = Proposal(ko_truth_category=TruthCategory.PHYSICAL_OBSERVATION)
        assert p.ko_truth_category == TruthCategory.PHYSICAL_OBSERVATION

    def test_proposal_evidence_relation_type_default(self):
        p = Proposal()
        assert p.evidence_relation_type == "supports"

    def test_proposal_evidence_relation_type_contradicts(self):
        p = Proposal(evidence_relation_type="contradicts")
        assert p.evidence_relation_type == "contradicts"


# ── CONTRADICTS detection ────────────────────────────────────────────────

class TestContradictsDetection:
    """CONTRADICTS edges are detected by warrant analyzer."""

    def test_contradiction_inbound_set(self):
        assert RelationType.CONTRADICTS in CONTRADICTION_INBOUND
        assert RelationType.SUPPORTS not in CONTRADICTION_INBOUND

    def test_contradicts_not_in_justification_inbound(self):
        """CONTRADICTS should not appear in justification_path traversal."""
        assert RelationType.CONTRADICTS not in JUSTIFICATION_INBOUND

    def test_contradicts_detected_by_warrant(self):
        storage = InMemoryStorage()
        claim = mk_ko("claim", "Claim to contradict", TruthCategory.MODEL_DERIVED)
        support = mk_ko("supp", "Supports claim", TruthCategory.SOURCED_MATERIAL_DATA)
        contra = mk_ko("contra", "Contradicts claim", TruthCategory.SOURCED_MATERIAL_DATA)

        storage.create_ko(claim)
        storage.create_ko(support)
        storage.create_ko(contra)

        # Add SUPPORTS edge
        storage.add_evidence("ev-sup", "claim", "confirmed", "supports", [],
                             relation_type="supports")
        # Manually add CONTRADICTS edge (add_evidence creates its own KO, use add_relation)
        storage.create_relation("contra", "claim", RelationType.CONTRADICTS)

        wa = WarrantAnalyzer(storage)
        w = wa.compute_warrant("claim")

        assert w.contradicting_kos is not None
        assert "contra" in w.contradicting_kos
        assert w.warrant_status == WarrantStatus.UNWARRANTED

    def test_contradicts_sets_unwarranted(self):
        storage = InMemoryStorage()
        claim = mk_ko("c", "Claim", TruthCategory.MODEL_DERIVED)
        contra = mk_ko("x", "Contradiction", TruthCategory.PHYSICAL_OBSERVATION)
        storage.create_ko(claim)
        storage.create_ko(contra)
        storage.create_relation("x", "c", RelationType.CONTRADICTS)

        wa = WarrantAnalyzer(storage)
        w = wa.compute_warrant("c")
        assert w.warrant_status == WarrantStatus.UNWARRANTED

    def test_no_contradicts_no_unwarranted(self):
        """Without contradictions, warrant should not be UNWARRANTED due to contradiction."""
        storage = InMemoryStorage()
        claim = mk_ko("c", "Claim", TruthCategory.MODEL_DERIVED)
        support = mk_ko("s", "Support", TruthCategory.SOURCED_MATERIAL_DATA)
        storage.create_ko(claim)
        storage.create_ko(support)
        storage.create_relation("s", "c", RelationType.SUPPORTS)

        wa = WarrantAnalyzer(storage)
        w = wa.compute_warrant("c")
        assert len(w.contradicting_kos) == 0

    def test_contradiction_diagnosis_identifies_evidence(self):
        storage = InMemoryStorage()
        claim = mk_ko("claim", "Claim", TruthCategory.MODEL_DERIVED)
        contra = mk_ko("contra", "Counter-evidence", TruthCategory.PHYSICAL_OBSERVATION)
        storage.create_ko(claim)
        storage.create_ko(contra)
        storage.create_relation("contra", "claim", RelationType.CONTRADICTS)

        wa = WarrantAnalyzer(storage)
        w = wa.compute_warrant("claim")
        assert len(w.anti_pattern_diagnoses) >= 1
        # Check that the diagnosis references the contradicting KO
        diag = w.anti_pattern_diagnoses[0]
        assert "contra" in diag.offending_ko_ids


# ── Evidence relation_type ────────────────────────────────────────────────

class TestEvidenceRelationType:
    """add_evidence respects relation_type parameter."""

    def test_add_evidence_supports_default(self):
        storage = InMemoryStorage()
        claim = mk_ko("claim", "Claim")
        storage.create_ko(claim)
        storage.add_evidence("ev1", "claim", "confirmed", "observation", [])
        # Default should be supports
        incoming = storage.get_incoming_relations("claim", JUSTIFICATION_INBOUND)
        # The add_evidence creates an evidence KO internally — check relations exist
        # In InMemoryStorage, add_evidence creates an internal evidence dict
        ev = storage.get_evidence("ev1")
        assert ev is not None
        assert ev.get("relation_type") == "supports"

    def test_add_evidence_contradicts(self):
        storage = InMemoryStorage()
        claim = mk_ko("claim", "Claim")
        storage.create_ko(claim)
        storage.add_evidence("ev-contra", "claim", "confirmed", "contradicts", [],
                             relation_type="contradicts")
        ev = storage.get_evidence("ev-contra")
        assert ev is not None
        assert ev.get("relation_type") == "contradicts"


# ── Runtime server truth_category validation ──────────────────────────────

class TestRuntimeServerTruthCategory:
    """Runtime server parses and validates truth_category."""

    def test_valid_truth_category_parsed(self):
        from transports.runtime_server import handle_submit_proposal

        storage = InMemoryStorage()
        components = {"storage": storage}

        # Valid truth_category
        result = handle_submit_proposal(components, {
            "proposal_type": "create_ko",
            "proposer": "test",
            "rationale": "test",
            "ko_title": "Test KO",
            "ko_truth_category": "physical_observation",
        })
        assert "error" not in result
        proposal_id = result["proposal_id"]

        # Execute and verify
        exec_result = storage.validate_and_execute(proposal_id)
        assert exec_result.state.value == "accepted"
        ko_id = exec_result.created_ko_id
        ko = storage.get_ko(ko_id)
        assert ko is not None
        assert ko.truth_category == TruthCategory.PHYSICAL_OBSERVATION

    def test_missing_truth_category_defaults_assumption(self):
        from transports.runtime_server import handle_submit_proposal

        storage = InMemoryStorage()
        components = {"storage": storage}

        result = handle_submit_proposal(components, {
            "proposal_type": "create_ko",
            "proposer": "test",
            "rationale": "test",
            "ko_title": "Test KO",
        })
        assert "error" not in result
        exec_result = storage.validate_and_execute(result["proposal_id"])
        ko = storage.get_ko(exec_result.created_ko_id)
        assert ko.truth_category == TruthCategory.ASSUMPTION

    def test_invalid_truth_category_rejected(self):
        from transports.runtime_server import handle_submit_proposal

        storage = InMemoryStorage()
        components = {"storage": storage}

        result = handle_submit_proposal(components, {
            "proposal_type": "create_ko",
            "proposer": "test",
            "rationale": "test",
            "ko_title": "Test KO",
            "ko_truth_category": "not_a_valid_category",
        })
        assert "error" in result
        assert "not_a_valid_category" in result["error"]

    def test_all_truth_categories_acceptable(self):
        from transports.runtime_server import handle_submit_proposal

        storage = InMemoryStorage()
        components = {"storage": storage}

        for tc in TruthCategory:
            result = handle_submit_proposal(components, {
                "proposal_type": "create_ko",
                "proposer": "test",
                "rationale": "test",
                "ko_title": f"Test {tc.value}",
                "ko_truth_category": tc.value,
            })
            assert "error" not in result, f"Rejected valid truth_category: {tc.value}"
            exec_result = storage.validate_and_execute(result["proposal_id"])
            ko = storage.get_ko(exec_result.created_ko_id)
            assert ko.truth_category == tc, f"Mismatch for {tc.value}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
