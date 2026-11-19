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

def _build_warrant_response(result, *, ncm_suggestion: dict | None = None) -> dict:
    """Build the check_warrant response dict from a WarrantResult.

    Shared between the packaged MCP server (mcp/server.py) and
    OrchestrationEngine so the Memory runtime returns the same
    provenance-tracing fields (root_sets, shared_ancestors) as the
    standalone server.

    Optionally accepts an NCM suggestion dict produced by
    `_ncm_challenge_suggestion()`.  When present the response includes
    an ``ncm_suggestion`` key with the model's alternative hypothesis
    and the discriminating observation it proposes.
    """
    resp = {
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
            "root_sets": {k: sorted(v) for k, v in (result.independence.root_sets or {}).items()},
            "shared_ancestors": {
                k: sorted(v) for k, v in (result.independence.shared_ancestors or {}).items()
            },
        } if result.independence else None,
        "cycles": result.cycles,
    }
    if ncm_suggestion is not None:
        resp["ncm_suggestion"] = ncm_suggestion
    return resp


def _ncm_challenge_suggestion(result) -> dict | None:
    """Send warrant result to NCM and ask for a challenging hypothesis.

    Prompt: given this conclusion, its evidence roots, shared provenance,
    and open assumptions — what explanation might the graph have missed,
    and what single observation could discriminate it from the graph's
    current explanation?

    Returns a dict with status, hypothesis, discriminating_observation,
    assumption_reference, and error/reason.  Returns None only when
    NCM is not available at all (no env vars set).  On error or irrelevant
    output returns a dict with status="error" or status="irrelevant".
    """
    import os
    checkpoint_dir = os.environ.get("NCM_CHECKPOINT_DIR", "")
    source_dir = os.environ.get("NCM_SOURCE_DIR", "")

    if not checkpoint_dir or not source_dir:
        return None

    # Build prompt from warrant result
    ko = None
    # Try to get the conclusion title from supporting_kos
    prompt_lines = []
    if result.independence:
        prompt_lines.append(
            f"CONCLUSION: {result.conclusion_ko_id} "
            f"(verdict: {result.warrant_status.value})"
        )
        prompt_lines.append(
            f"Evidence items: {result.independence.evidence_count}. "
            f"Independent provenance roots: {result.independence.independent_root_count}."
        )
        # Root mapping
        for ev_id, roots in sorted(result.independence.root_sets.items()):
            prompt_lines.append(
                f"Finding {ev_id} traces to source(s): {', '.join(sorted(roots))}."
            )
        # Shared provenance
        shared = result.independence.shared_ancestors
        if shared:
            for root, kos in sorted(shared.items()):
                prompt_lines.append(
                    f"Source '{root}' is shared by findings: {', '.join(sorted(kos))}."
                )
        else:
            prompt_lines.append("No shared provenance. Evidence roots are independent.")

    if result.conditional_assumptions:
        prompt_lines.append("Open assumptions / gaps:")
        for a in result.conditional_assumptions:
            prompt_lines.append(f"  - {a}")

    if result.dependent_kos:
        prompt_lines.append(
            f"Dependent/ungrounded findings: {', '.join(result.dependent_kos)}."
        )
    if result.independent_kos:
        prompt_lines.append(
            f"Independently grounded findings: {', '.join(result.independent_kos)}."
        )

    prompt_lines.append(
        "What alternative explanation might this evidence graph have missed? "
        "Propose one hypothesis and one observation that could discriminate it "
        "from the graph's current explanation."
    )

    prompt = "\n".join(prompt_lines)

    # Call NCM via ncm_run.py (upstream eval_shard.py)
    try:
        import json
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        here = Path(__file__).resolve().parents[2] / "examples" / "ncm_explanations"
        ncm_run = here / "ncm_run.py"
        if not ncm_run.exists():
            return {"status": "unavailable", "reason": "ncm_run.py not found",
                    "hypothesis": "", "discriminating_observation": "",
                    "assumption_reference": ""}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fin:
            json.dump([prompt], fin)
            input_path = fin.name
        output_path = input_path + ".out"

        proc = subprocess.run(
            [sys.executable, str(ncm_run),
             "--checkpoint-dir", checkpoint_dir,
             "--source-dir", source_dir,
             "--input-file", input_path,
             "--output-file", output_path],
            capture_output=True, text=True, timeout=120,
        )

        os.unlink(input_path)

        if proc.returncode != 0 or not Path(output_path).exists():
            err = proc.stderr.strip() or proc.stdout.strip() or "ncm_run failed"
            return {"status": "error", "reason": err[:500],
                    "hypothesis": "", "discriminating_observation": "",
                    "assumption_reference": ""}

        out = json.load(open(output_path))
        os.unlink(output_path)

        if not out or out[0].get("status") != "generated":
            return {"status": "error", "reason": out[0].get("error", "no output"),
                    "hypothesis": "", "discriminating_observation": "",
                    "assumption_reference": ""}

        summary = out[0]["summary"]

        # Check relevance: must mention at least one warrant concept
        warrant_terms = [
            "evidence", "source", "finding", "hypothesis", "observation",
            "root", "provenance", "assumption", "conclusion", "explain",
            "validation", "measurement", "test",
        ]
        lower = summary.lower()
        relevant_count = sum(1 for t in warrant_terms if t in lower)

        if relevant_count == 0:
            return {"status": "irrelevant",
                    "reason": "NCM summary contains no warrant-relevant concepts",
                    "raw_summary": summary,
                    "hypothesis": "", "discriminating_observation": "",
                    "assumption_reference": ""}

        # Parse the summary into hypothesis + observation
        # The summary is a single sentence — treat the whole thing as hypothesis
        # and note that it challenges the graph's explanation
        assumption_ref = ""
        if result.conditional_assumptions:
            assumption_ref = result.conditional_assumptions[0].split(":")[0]

        return {
            "status": "generated",
            "hypothesis": summary.strip(),
            "discriminating_observation": (
                "See hypothesis — NCM XSum produces a single-sentence summary. "
                "Review the raw output for the proposed discriminating observation."
            ),
            "assumption_reference": assumption_ref,
            "raw_summary": summary,
        }

    except subprocess.TimeoutExpired:
        return {"status": "error", "reason": "NCM timed out (120s)",
                "hypothesis": "", "discriminating_observation": "",
                "assumption_reference": ""}
    except Exception as e:
        return {"status": "error", "reason": str(e)[:500],
                "hypothesis": "", "discriminating_observation": "",
                "assumption_reference": ""}


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
        # Ask NCM for a challenging hypothesis (non-blocking, advisory)
        ncm = _ncm_challenge_suggestion(result)
        return _build_warrant_response(result, ncm_suggestion=ncm)

    def scan_anti_patterns(self) -> list[dict]:
        findings = self.warrant_analyzer.detect_all_anti_patterns()
        return [
            {"pattern": f.pattern.value,
             "offending_ko_ids": f.offending_ko_ids,
             "violated_condition": f.violated_condition,
             "resolution_hint": f.resolution_hint}
            for f in findings
        ]
