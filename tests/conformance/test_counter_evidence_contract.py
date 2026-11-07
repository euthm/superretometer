"""Explicit counter-evidence contract (spec/WARRANT.md); no manual edge workaround."""
import pytest

from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer
from cognitive_harness.model.ko import (
    KnowledgeObject, TruthCategory, AntiPattern, RelationType, WarrantStatus,
    CONTRADICTION_INBOUND,
)
from cognitive_harness.model.proposal import Proposal, ProposalType, ProposalState
from cognitive_harness.storage.inmemory import InMemoryStorage


def test_create_evidence_proposal_changes_warrant():
    storage = InMemoryStorage()
    claim = KnowledgeObject(title="Software returns HTTP 200")
    storage.create_ko(claim)
    proposal = Proposal(type=ProposalType.CREATE_EVIDENCE, evidence_claim_id=claim.id,
                        evidence_observation="Observed HTTP 500",
                        evidence_relation_type="contradicts")
    storage.submit_proposal(proposal)
    result = storage.validate_and_execute(proposal.id)
    assert result.state == ProposalState.ACCEPTED
    eid = result.created_evidence_id
    assert storage.get_evidence(eid)["relation_type"] == "contradicts"
    assert storage.get_incoming_relations(claim.id, CONTRADICTION_INBOUND) == [
        (eid, RelationType.CONTRADICTS)]
    warrant = WarrantAnalyzer(storage).compute_warrant(claim.id)
    assert warrant.warrant_status == WarrantStatus.UNWARRANTED
    assert warrant.contradicting_kos == [eid]
    patterns = [d.pattern for d in warrant.anti_pattern_diagnoses]
    assert AntiPattern.CONTRADICTED in patterns
    assert AntiPattern.PHYSICALLY_UNREALIZABLE not in patterns
    assert eid not in warrant.supporting_kos
    assert eid not in warrant.independent_kos


def test_conservation_law_retains_physical_diagnosis():
    storage = InMemoryStorage()
    claim = KnowledgeObject(title="Model claim")
    law = KnowledgeObject(title="Conservation constraint", truth_category=TruthCategory.CONSERVATION_LAW)
    storage.create_ko(claim)
    storage.create_ko(law)
    storage.create_relation(law.id, claim.id, RelationType.CONTRADICTS)
    warrant = WarrantAnalyzer(storage).compute_warrant(claim.id)
    assert warrant.warrant_status == WarrantStatus.UNWARRANTED
    assert AntiPattern.PHYSICALLY_UNREALIZABLE in [d.pattern for d in warrant.anti_pattern_diagnoses]


def test_legacy_verification_record_does_not_become_a_carrying_assumption():
    storage = InMemoryStorage()
    claim = KnowledgeObject(title="Observation")
    storage.create_ko(claim)
    before = WarrantAnalyzer(storage).compute_warrant(claim.id).supporting_kos
    storage.add_evidence("record", claim.id, "verified", "Recorded measurement", [])
    assert storage.get_evidence("record") is not None
    assert WarrantAnalyzer(storage).compute_warrant(claim.id).supporting_kos == before


def test_invalid_relation_cannot_silently_become_support():
    storage = InMemoryStorage()
    claim = KnowledgeObject(title="Claim")
    storage.create_ko(claim)
    with pytest.raises(ValueError, match="relation_type"):
        storage.add_evidence("bad", claim.id, "pending", "test", [], relation_type="typo")
    assert storage.get_evidence("bad") is None
