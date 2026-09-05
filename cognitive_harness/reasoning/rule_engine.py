# FILE: cognitive-harness/reasoning/rule_engine.py
"""Rule-based reasoner: deterministic, LLM-free.

Demonstrates a Thread traversing CAFCR viewpoints:
  Customer → Functional → Conceptual → Realization → conclusion

Each step examines actual KOs from storage, asks questions, proposes
hypotheses, collects evidence, and reaches explicit conclusions."""
from __future__ import annotations
from cognitive_harness.model.thread import (
    Thread, ThreadStep, Conclusion, ConclusionType, StepAction, Viewpoint,
)
from cognitive_harness.model.ko import EpistemicStatus, ConfidenceLevel
from cognitive_harness.reasoning.interface import ReasonerInterface


class RuleEngineReasoner(ReasonerInterface):
    """Minimal rule-based reasoner that performs actual viewpoint traversal.

    In production, this would be replaced by domain-specific rules or
    an LLM reasoner adapter. The key property: it produces structured
    ThreadSteps and Conclusions, never writes to storage directly."""

    def __init__(self, storage):
        self.storage = storage
        self._step_index = 0
        self._plan: list[dict] = []

    def start_thread(self, thread: Thread, ko_ids: list[str], canonical_ids: list[str]) -> ThreadStep:
        """Initialize the thread: build a traversal plan across CAFCR viewpoints."""
        self._step_index = 0
        self._plan = self._build_plan(ko_ids, canonical_ids)

        # First step: examine Customer viewpoint
        customer_kos = [
            k for k in [self.storage.get_ko(kid) for kid in ko_ids]
            if k and "customer" in k.viewpoint_ids
        ]
        step = ThreadStep(
            action=StepAction.EXAMINE,
            viewpoint=Viewpoint.CUSTOMER,
            input_ko_ids=[k.id for k in customer_kos],
            claim=f"Examining {len(customer_kos)} KOs in Customer viewpoint",
        )
        thread.add_step(step)
        return step

    def continue_thread(self, thread: Thread) -> ThreadStep | Conclusion:
        """Execute next planned step or conclude."""
        if self._step_index >= len(self._plan):
            return self._generate_conclusion(thread)

        plan_step = self._plan[self._step_index]
        self._step_index += 1
        action = plan_step["action"]

        if action == StepAction.EXAMINE:
            step = self._step_examine(plan_step)
        elif action == StepAction.QUESTION:
            step = self._question(plan_step)
        elif action == StepAction.TRAVERSE:
            step = self._traverse(plan_step)
        elif action == StepAction.PROPOSE:
            step = self._propose(plan_step)
        elif action == StepAction.COLLECT_EVIDENCE:
            step = self._collect_evidence(plan_step)
        elif action == StepAction.EVALUATE:
            step = self._evaluate(plan_step)
        elif action == StepAction.EXPECT_TRANSITION:
            step = self._expect_transition(plan_step)
        elif action == StepAction.CONCLUDE:
            return self._generate_conclusion(thread)
        else:
            return self._generate_conclusion(thread)

        thread.add_step(step)
        return step

        return self._generate_conclusion(thread)

    # ── Step implementations ─────────────────────────────────────────

    def _step_examine(self, plan):
        vp = Viewpoint(plan["viewpoint"])
        kos = [
            self.storage.get_ko(kid) for kid in plan.get("ko_ids", [])
            if self.storage.get_ko(kid)
        ]
        return ThreadStep(
            action=StepAction.EXAMINE,
            viewpoint=vp,
            input_ko_ids=[k.id for k in kos],
            claim=plan.get("claim", f"Examined {len(kos)} KOs in {vp.value}"),
        )

    def _question(self, plan):
        vp = Viewpoint(plan["viewpoint"])
        return ThreadStep(
            action=StepAction.QUESTION,
            viewpoint=vp,
            input_ko_ids=plan.get("ko_ids", []),
            question=plan["question"],
            missing_evidence=plan.get("missing_evidence", []),
        )

    def _traverse(self, plan):
        vp = Viewpoint(plan["viewpoint"])
        kos = [
            self.storage.get_ko(kid) for kid in plan.get("ko_ids", [])
            if self.storage.get_ko(kid)
        ]
        return ThreadStep(
            action=StepAction.TRAVERSE,
            viewpoint=vp,
            input_ko_ids=[k.id for k in kos],
            claim=f"Traversed to {vp.value} viewpoint; found {len(kos)} relevant KOs",
        )

    def _propose(self, plan):
        vp = Viewpoint(plan["viewpoint"])
        return ThreadStep(
            action=StepAction.PROPOSE,
            viewpoint=vp,
            input_ko_ids=plan.get("ko_ids", []),
            claim=plan["claim"],
            speculative=plan.get("speculative", True),
        )

    def _collect_evidence(self, plan):
        vp = Viewpoint(plan["viewpoint"])
        evs = [self.storage.get_evidence(eid) for eid in plan.get("evidence_ids", [])]
        verified = [e for e in evs if e and e.get("status") == "verified"]
        gaps = [e for e in evs if e and e.get("status") != "verified"]
        return ThreadStep(
            action=StepAction.COLLECT_EVIDENCE,
            viewpoint=vp,
            input_ko_ids=plan.get("ko_ids", []),
            evidence_used=plan.get("evidence_ids", []),
            missing_evidence=plan.get("missing_evidence", []),
            claim=f"Collected evidence: {len(verified)} verified, {len(gaps)} gaps",
            speculative=len(gaps) > 0,
        )

    def _expect_transition(self, plan):
        vp = Viewpoint(plan["viewpoint"])
        return ThreadStep(
            action=StepAction.EXPECT_TRANSITION,
            viewpoint=vp,
            input_ko_ids=[plan["expected_from"]],
            expected_from=plan["expected_from"],
            expected_status=plan["expected_status"],
            claim=f"Expect {plan['expected_from']} to transition to {plan['expected_status']}",
        )

    def _evaluate(self, plan):
        vp = Viewpoint(plan["viewpoint"])
        return ThreadStep(
            action=StepAction.EVALUATE,
            viewpoint=vp,
            input_ko_ids=plan.get("ko_ids", []),
            claim=plan.get("claim", "Evaluation complete"),
            evidence_used=plan.get("evidence_ids", []),
        )

    def _generate_conclusion(self, thread: Thread) -> Conclusion:
        verified_steps = [s for s in thread.steps if not s.speculative]
        speculative_steps = [s for s in thread.steps if s.speculative]
        proposals = [s for s in thread.steps if s.action == StepAction.PROPOSE]

        if proposals and len(verified_steps) > len(speculative_steps):
            target = proposals[0].input_ko_ids[0] if proposals[0].input_ko_ids else ""
            return Conclusion(
                type=ConclusionType.VALIDATION,
                target_ko_id=target,
                rationale=f"Thread across {thread.get_viewpoint_sequence()}: "
                          f"{len(verified_steps)} verified steps support proposal",
            )
        if proposals:
            return Conclusion(
                type=ConclusionType.DEFERRAL,
                rationale=f"Insufficient evidence: {len(speculative_steps)} speculative steps remain",
                unresolved_tensions=[thread.origin_tension_id],
            )
        return Conclusion(
            type=ConclusionType.DEFERRAL,
            rationale="No proposals generated; thread inconclusive",
            unresolved_tensions=[thread.origin_tension_id],
        )

    # ── Plan builder ──────────────────────────────────────────────────

    def _build_plan(self, ko_ids: list[str], canonical_ids: list[str]) -> list[dict]:
        """Default traversal plan: Customer → Functional → Conceptual → Realization.

        The complete reasoning trace in main.py provides custom plans per thread."""
        return [
            {"action": StepAction.QUESTION, "viewpoint": "customer", "ko_ids": ko_ids,
             "question": "What is the stakeholder requirement?",
             "missing_evidence": []},
            {"action": StepAction.TRAVERSE, "viewpoint": "functional", "ko_ids": ko_ids},
            {"action": StepAction.TRAVERSE, "viewpoint": "realization", "ko_ids": ko_ids},
            {"action": StepAction.COLLECT_EVIDENCE, "viewpoint": "realization",
             "ko_ids": ko_ids, "evidence_ids": [], "missing_evidence": []},
            {"action": StepAction.EVALUATE, "viewpoint": "conceptual", "ko_ids": ko_ids,
             "claim": "Evaluation complete", "evidence_ids": []},
            {"action": StepAction.CONCLUDE, "viewpoint": "conceptual"},
        ]
