# FILE: cognitive-harness/consumer/api.py
"""Consumer API — the ONLY interface for agents, humans, and external tools.

Two modes:
  1. READ: query, explain, list — no mutation
  2. PROPOSE: submit structured proposals for new KOs, relations, tensions,
             hypotheses, evidence, and state transitions.

Proposals are validated deterministically by the Orchestration layer.
The Consumer never touches canonical state directly.
"""
from __future__ import annotations
from cognitive_harness.storage.interface import StorageInterface
from cognitive_harness.model.proposal import Proposal, ProposalType
from cognitive_harness.model.ko import KOType, EpistemicStatus, ConfidenceLevel, RelationType
from cognitive_harness.model.tension import Tension, TensionPriority
from cognitive_harness.model.thread import Viewpoint
from cognitive_harness.orchestration.engine import OrchestrationEngine


class ConsumerAPI:
    """Read-only queries + proposal submission."""

    def __init__(self, storage: StorageInterface, orchestrator: OrchestrationEngine):
        self.storage = storage
        self.orchestrator = orchestrator

    # ── READ operations (no mutation) ─────────────────────────────────

    def query(self, topic: str, viewpoint: str | None = None, limit: int = 10) -> list[dict]:
        kos = self.storage.query_semantic(topic, viewpoint, limit)
        return [self._present_ko(ko, summary=True) for ko in kos]

    def explain(self, ko_id: str) -> dict | None:
        ko = self.storage.get_ko(ko_id)
        if ko is None:
            return None
        return self._present_ko(ko, summary=False)

    def succession_chain(self, ko_id: str) -> list[dict]:
        chain = self.storage.get_succession_chain(ko_id)
        return [self._present_ko(ko, summary=True) for ko in chain]

    def list_canonical(self, scope: str | None = None) -> list[dict]:
        return [self._present_ko(ko, summary=True) for ko in self.storage.list_canonical(scope)]

    def list_active_by_scope(self, scope: str) -> list[dict]:
        return [self._present_ko(ko, summary=True) for ko in self.storage.query_active_by_scope(scope)]

    def impact_set(self, ko_id: str) -> list[dict]:
        impacted_ids = self.storage.compute_impact_set(ko_id)
        return [self._present_ko(self.storage.get_ko(kid), summary=True) for kid in impacted_ids]

    def list_review_required(self) -> list[dict]:
        return [self._present_ko(ko, summary=False) for ko in self.storage.list_review_required()]

    # ── Warrant queries (v0.4) ────────────────────────────────────────

    def check_warrant(self, conclusion_ko_id: str) -> dict:
        """Compute and return warrant status for a conclusion."""
        return self.orchestrator.check_warrant(conclusion_ko_id)

    def scan_anti_patterns(self) -> list[dict]:
        """Scan all KOs for epistemic anti-patterns."""
        return self.orchestrator.scan_anti_patterns()

    def justification_path(self, ko_id: str) -> list[dict]:
        """Return the justification path (all KOs that carry this one)."""
        path_ids = self.storage.get_justification_path(ko_id)
        return [self._present_ko(self.storage.get_ko(kid), summary=True) for kid in path_ids]

    def list_anti_pattern_hits(self, pattern: str) -> list[dict]:
        """List KOs flagged with a specific anti-pattern."""
        return [self._present_ko(ko, summary=True) for ko in self.storage.list_anti_pattern_hits(pattern)]

    # ── PROPOSAL operations (structured, validated mutations) ─────────

    def propose_ko(self, proposer: str, ko_type: KOType, title: str,
                   content: object | None, viewpoints: list[str],
                   scope: str = "", assumptions: list[str] | None = None,
                   confidence: ConfidenceLevel = ConfidenceLevel.SPECULATIVE,
                   valid_from: str | None = None, valid_to: str | None = None,
                   rationale: str = "") -> str:
        p = Proposal(
            type=ProposalType.CREATE_KO,
            proposer=proposer,
            rationale=rationale,
            ko_type=ko_type,
            ko_title=title,
            ko_content=content,
            ko_viewpoints=viewpoints,
            ko_scope=scope,
            ko_assumptions=assumptions or [],
            ko_confidence=confidence,
            ko_valid_from=valid_from,
            ko_valid_to=valid_to,
        )
        return self.orchestrator.submit_proposal(p)

    def propose_evidence(self, proposer: str, claim_id: str,
                         observation: str, records: list[dict],
                         rationale: str = "") -> str:
        p = Proposal(
            type=ProposalType.CREATE_EVIDENCE,
            proposer=proposer,
            rationale=rationale,
            evidence_claim_id=claim_id,
            evidence_observation=observation,
            evidence_records=records,
        )
        return self.orchestrator.submit_proposal(p)

    def propose_transition(self, proposer: str, ko_id: str,
                           target_status: EpistemicStatus,
                           rationale: str = "") -> str:
        p = Proposal(
            type=ProposalType.TRANSITION_STATUS,
            proposer=proposer,
            rationale=rationale,
            target_ko_id=ko_id,
            target_status=target_status,
        )
        return self.orchestrator.submit_proposal(p)

    def propose_promote_canonical(self, proposer: str, ko_id: str,
                                  rationale: str = "") -> str:
        p = Proposal(
            type=ProposalType.PROMOTE_CANONICAL,
            proposer=proposer,
            rationale=rationale,
            target_ko_id=ko_id,
        )
        return self.orchestrator.submit_proposal(p)

    def propose_supersede(self, proposer: str, old_ko_id: str,
                          new_ko_id: str, rationale: str = "") -> str:
        p = Proposal(
            type=ProposalType.SUPERSEDE,
            proposer=proposer,
            rationale=rationale,
            target_ko_id=old_ko_id,
            successor_ko_id=new_ko_id,
        )
        return self.orchestrator.submit_proposal(p)

    def propose_relation(self, proposer: str, from_ko_id: str, to_ko_id: str,
                         relation_type: RelationType, rationale: str = "") -> str:
        p = Proposal(
            type=ProposalType.CREATE_RELATION,
            proposer=proposer,
            rationale=rationale,
            from_ko_id=from_ko_id,
            to_ko_id=to_ko_id,
            relation_type=relation_type,
        )
        return self.orchestrator.submit_proposal(p)

    def propose_tension(self, proposer: str, title: str, description: str,
                        ko_ids: list[str], viewpoints: list[str] | None = None,
                        priority: TensionPriority = TensionPriority.MEDIUM,
                        rationale: str = "") -> str:
        p = Proposal(
            type=ProposalType.CREATE_TENSION,
            proposer=proposer,
            rationale=rationale,
            tension_title=title,
            tension_description=description,
            tension_ko_ids=ko_ids,
            tension_viewpoints=viewpoints or [],
        )
        return self.orchestrator.submit_proposal(p)

    def execute_pending_proposals(self, proposal_ids: list[str]) -> list:
        results = self.orchestrator.execute_proposals(proposal_ids)
        return [
            {
                "id": r.id,
                "type": r.type.value,
                "state": r.state.value,
                "rejection_reason": r.rejection_reason,
                "created_ko_id": r.created_ko_id,
                "created_evidence_id": r.created_evidence_id,
                "created_tension_id": r.created_tension_id,
            }
            for r in results
        ]

    # ── Presentation ──────────────────────────────────────────────────

    def _present_ko(self, ko, summary: bool) -> dict:
        result = {
            "id": ko.id,
            "type": ko.type.value,
            "title": ko.title,
            "epistemic_status": ko.epistemic_status.value,
            "confidence": ko.confidence.value,
            "viewpoints": ko.viewpoint_ids,
            "scope": ko.scope,
            "assumptions": ko.assumptions,
            "valid_from": ko.valid_from.isoformat() if ko.valid_from else None,
            "valid_to": ko.valid_to.isoformat() if ko.valid_to else None,
            "supersedes_id": ko.supersedes_id,
            "superseded_by_id": ko.superseded_by_id,
            "provenance": {
                "source": ko.provenance.source,
                "author": ko.provenance.author,
                "timestamp": ko.provenance.timestamp.isoformat(),
                "revision": ko.provenance.revision,
            },
            "evidence_count": len(ko.evidence_ids),
            "truth_category": ko.truth_category.value,
            "anti_patterns": ko.anti_patterns,
        }
        if not summary:
            result["content"] = ko.content
            result["relations"] = [{"to": r.to, "type": r.type.value} for r in ko.relations]
            result["tensions"] = ko.tension_ids
            result["validators"] = [
                {"id": v.id, "description": v.description,
                 "what_would_falsify": v.what_would_falsify,
                 "passes": v.passes, "observation": v.observation}
                for v in ko.validators
            ]
            result["review_required"] = ko.review_required
            result["review_reason"] = ko.review_reason
        return result
