# FILE: cognitive-harness/orchestration/engine.py
"""Orchestration layer.

Responsibilities:
- Manages Tension queue (priority-ordered)
- Creates Threads from Tensions
- Validates and executes Proposals (deterministic rules)
- Enforces Preservation Constraints (canonical KOs cannot be invalidated)
- Coordinates viewpoint traversal
- Enforces consumer boundary (consumers can only submit Proposals)

The Orchestrator is the ONLY component that mutates canonical state.
"""
from __future__ import annotations
import logging
from cognitive_harness.model.ko import KnowledgeObject, EpistemicStatus, KOType, Provenance
from cognitive_harness.model.thread import Thread, Conclusion, ConclusionType, Viewpoint
from cognitive_harness.model.tension import Tension, TensionPriority, TensionStatus
from cognitive_harness.model.thread import Viewpoint
from cognitive_harness.model.proposal import Proposal, ProposalType, ProposalState
from cognitive_harness.model.ko import KOType
from cognitive_harness.reasoning.interface import ReasonerInterface
from cognitive_harness.storage.interface import StorageInterface
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer

log = logging.getLogger(__name__)


class OrchestrationEngine:
    def __init__(self, storage: StorageInterface, reasoner: ReasonerInterface):
        self.storage = storage
        self.reasoner = reasoner
        self.warrant_analyzer = WarrantAnalyzer(storage)
        self._tensions: dict[str, Tension] = {}
        self._threads: dict[str, Thread] = {}
        self._proposals: dict[str, Proposal] = {}

    # ── Tension management ────────────────────────────────────────────

    def add_tension(self, tension: Tension) -> str:
        self._tensions[tension.id] = tension
        log.info("Tension created: %s [%s]", tension.title, tension.priority)
        return tension.id

    def _select_next_tension(self) -> Tension | None:
        priority_order = {
            TensionPriority.BLOCKER: 0,
            TensionPriority.HIGH: 1,
            TensionPriority.MEDIUM: 2,
            TensionPriority.LOW: 3,
        }
        open_tensions = [
            t for t in self._tensions.values()
            if t.status in (TensionStatus.OPEN, TensionStatus.INVESTIGATING, TensionStatus.CONTESTED)
        ]
        if not open_tensions:
            return None
        open_tensions.sort(key=lambda t: priority_order.get(t.priority, 99))
        return open_tensions[0]

    # ── Proposal pipeline ─────────────────────────────────────────────

    def submit_proposal(self, proposal: Proposal) -> str:
        """External entry point: agents, tools, humans submit proposals here."""
        pid = self.storage.submit_proposal(proposal)
        return pid

    def execute_proposal(self, proposal_id: str) -> Proposal:
        """Validate and execute a proposal through deterministic rules."""
        result = self.storage.validate_and_execute(proposal_id)
        if result.state == ProposalState.ACCEPTED:
            log.info("Proposal %s ACCEPTED: %s", proposal_id, result.type)
        else:
            log.info("Proposal %s REJECTED: %s — %s", proposal_id, result.type, result.rejection_reason)
        return result

    def execute_proposals(self, proposal_ids: list[str]) -> list[Proposal]:
        return [self.execute_proposal(pid) for pid in proposal_ids]

    # ── Reasoning loop ────────────────────────────────────────────────

    def _get_canonical_ids(self) -> list[str]:
        return [ko.id for ko in self.storage.list_canonical()]

    def run_iteration(self, max_threads: int = 5) -> list[dict]:
        """Run one iteration of the tension-driven reasoning loop.
        Returns list of {tension_id, thread_id, conclusion} dicts."""
        results = []
        threads_run = 0
        while threads_run < max_threads:
            tension = self._select_next_tension()
            if tension is None:
                break

            tension.status = TensionStatus.INVESTIGATING
            thread = Thread(
                origin_tension_id=tension.id,
                originating_question=tension.description,
            )
            self._threads[thread.id] = thread
            tension.thread_ids.append(thread.id)
            threads_run += 1
            log.info("Thread %s started for tension: %s", thread.id, tension.title)

            canonical_ids = self._get_canonical_ids()
            self.reasoner.start_thread(thread, tension.ko_ids, canonical_ids)

            max_steps = 20
            for _ in range(max_steps):
                result = self.reasoner.continue_thread(thread)
                if isinstance(result, Conclusion):
                    self._apply_conclusion(thread, tension, result)
                    results.append({
                        "tension_id": tension.id,
                        "thread_id": thread.id,
                        "conclusion": result,
                        "viewpoints_visited": thread.get_viewpoint_sequence(),
                    })
                    break

            else:
                thread.leave_unresolved()
                log.warning("Thread %s unresolved after %d steps", thread.id, max_steps)
                results.append({
                    "tension_id": tension.id,
                    "thread_id": thread.id,
                    "conclusion": None,
                    "viewpoints_visited": thread.get_viewpoint_sequence(),
                })

        return results

    # ── Apply conclusion ──────────────────────────────────────────────

    def _apply_conclusion(self, thread: Thread, tension: Tension, conclusion: Conclusion) -> None:
        log.info("Thread %s concluded: %s — %s",
                 thread.id, conclusion.type, conclusion.rationale)

        # Check if this tension already has a different concluding thread
        if conclusion.type not in (ConclusionType.DEFERRAL, ConclusionType.SUPERSESSION):
            for tid in tension.thread_ids:
                if tid != thread.id:
                    other = self._threads.get(tid)
                    if other and other.conclusion and other.conclusion.type != ConclusionType.DEFERRAL:
                        if other.conclusion.type == conclusion.type:
                            # Same conclusion type but different target → contested
                            if other.conclusion.target_ko_id != conclusion.target_ko_id:
                                tension.status = TensionStatus.CONTESTED
                                log.info("Tension %s is CONTESTED: threads %s and %s disagree",
                                         tension.id, tid[:8], thread.id[:8])
                                return
                        else:
                            tension.status = TensionStatus.CONTESTED
                            log.info("Tension %s is CONTESTED: threads %s and %s have different conclusions",
                                     tension.id, tid[:8], thread.id[:8])
                            return

        if conclusion.type == ConclusionType.VALIDATION:
            ko = self.storage.get_ko(conclusion.target_ko_id)
            if ko and ko.can_transition_to(EpistemicStatus.VALIDATED):
                self.storage.update_ko(ko.id, {"epistemic_status": EpistemicStatus.VALIDATED})

        elif conclusion.type == ConclusionType.REFUTATION:
            ko = self.storage.get_ko(conclusion.target_ko_id)
            if ko and ko.can_transition_to(EpistemicStatus.INVALIDATED):
                self.storage.update_ko(ko.id, {"epistemic_status": EpistemicStatus.INVALIDATED})

        elif conclusion.type == ConclusionType.DECISION:
            decision = KnowledgeObject(
                type=KOType.DECISION,
                title=f"Decision: {conclusion.rationale[:80]}",
                content=conclusion.rationale,
                provenance=Provenance(
                    source="thread",
                    author=thread.id,
                    derived_from=conclusion.target_ko_id or None,
                ),
                epistemic_status=EpistemicStatus.VALIDATED,
                viewpoint_ids=list(set(
                    s.viewpoint.value for s in thread.steps
                )),
            )
            self.storage.create_ko(decision)
            tension.resolution_ko_id = decision.id

        elif conclusion.type == ConclusionType.PROMOTION:
            ko = self.storage.get_ko(conclusion.target_ko_id)
            if ko and ko.can_transition_to(EpistemicStatus.CANONICAL):
                ko.epistemic_status = EpistemicStatus.CANONICAL

        elif conclusion.type == ConclusionType.SUPERSESSION:
            old_ko = self.storage.get_ko(conclusion.target_ko_id)
            new_ko = self.storage.get_ko(conclusion.successor_ko_id)
            if old_ko and new_ko:
                old_ko.epistemic_status = EpistemicStatus.SUPERSEDED
                old_ko.superseded_by_id = new_ko.id
                new_ko.supersedes_id = old_ko.id
                # Recompute warrant for impacted conclusions
                self._recompute_warrant_for_impacted(old_ko.id)

        elif conclusion.type == ConclusionType.DEFERRAL:
            pass  # tension stays open

        if conclusion.type != ConclusionType.DEFERRAL:
            tension.status = TensionStatus.RESOLVED
            tension.resolution_ko_id = conclusion.target_ko_id or conclusion.successor_ko_id

    # ── Reassessment from impact set ──────────────────────────────────

    def run_reassessment_iteration(self, impacted_ids: list[str], max_threads: int = 5) -> list[dict]:
        """Launch reassessment threads for KOs marked REVIEW_REQUIRED.
        Each impacted KO becomes the seed for a new tension + thread."""
        results = []
        for ko_id in impacted_ids[:max_threads]:
            ko = self.storage.get_ko(ko_id)
            if ko is None:
                continue

            # Create a reassessment tension
            tension = Tension(
                title=f"Reassessment: {ko.title}",
                description=f"KO {ko.id[:8]}... marked REVIEW_REQUIRED: {ko.review_reason}",
                ko_ids=[ko_id],
                viewpoint_ids=ko.viewpoint_ids,
                priority=TensionPriority.HIGH,
            )
            self.add_tension(tension)

            # Run a single thread for this reassessment
            r = self.run_iteration(max_threads=1)
            results.extend(r)

            # Clear review flag regardless of outcome
            self.storage.clear_review_required(ko_id)

        return results

    # ── Warrant integration (v0.4) ────────────────────────────────────

    def _recompute_warrant_for_impacted(self, superseded_ko_id: str) -> None:
        impacted = self.storage.compute_impact_set(superseded_ko_id)
        for kid in impacted:
            ko = self.storage.get_ko(kid)
            if ko and ko.type == KOType.CONCLUSION:
                result = self.warrant_analyzer.compute_warrant(kid)
                if result.warrant_status.value in ("unwarranted", "conditionally_warranted"):
                    log.warning(
                        "Conclusion %s warrant changed to %s after supersession of %s",
                        kid[:8], result.warrant_status, superseded_ko_id[:8],
                    )
                    self.storage.mark_review_required(
                        [kid],
                        f"Warrant downgraded to {result.warrant_status}: superseded premise {superseded_ko_id[:8]}",
                    )

    def check_warrant(self, conclusion_ko_id: str) -> dict:
        result = self.warrant_analyzer.compute_warrant(conclusion_ko_id)
        return {
            "conclusion_ko_id": result.conclusion_ko_id,
            "warrant_status": result.warrant_status.value,
            "supporting_kos": result.supporting_kos,
            "independent_kos": result.independent_kos,
            "dependent_kos": result.dependent_kos,
            "anti_patterns": [
                {"pattern": d.pattern.value,
                 "offending_ko_ids": d.offending_ko_ids,
                 "violated_condition": d.violated_condition,
                 "resolution_hint": d.resolution_hint}
                for d in result.anti_pattern_diagnoses
            ],
            "conditional_assumptions": result.conditional_assumptions,
            "independence": {
                "evidence_count": result.independence.evidence_count if result.independence else 0,
                "independent_root_count": result.independence.independent_root_count if result.independence else 0,
            },
            "cycles": result.cycles,
        }

    def scan_anti_patterns(self) -> list[dict]:
        findings = self.warrant_analyzer.detect_all_anti_patterns()
        return [
            {"pattern": f.pattern.value,
             "offending_ko_ids": f.offending_ko_ids,
             "violated_condition": f.violated_condition,
             "resolution_hint": f.resolution_hint}
            for f in findings
        ]
