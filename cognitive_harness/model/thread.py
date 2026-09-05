# FILE: cognitive-harness/model/thread.py
"""Thread of Reasoning v0.4 — non-linear, transition-aware.

Per Muller: CAFCR viewpoints are not pipeline stages. A Thread may enter,
leave, revisit or skip viewpoints. Every transition records what KOs were
consumed, what was produced, what evidence was used, and what assumptions
carried the step.

Reasoning modes (per arscontexta):
  Forward:  constraints → decisions (deductive)
  Backward: decisions → rationale (explanatory)
  Quality-needle: a single quality concern threads through all viewpoints
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from enum import Enum


# ── CAFCR Viewpoints ──────────────────────────────────────────────────────

class Viewpoint(str, Enum):
    CUSTOMER = "customer"
    APPLICATION = "application"
    FUNCTIONAL = "functional"
    CONCEPTUAL = "conceptual"
    REALIZATION = "realization"

    @classmethod
    def from_str(cls, s: str) -> Viewpoint:
        try:
            return cls(s)
        except ValueError:
            raise ValueError(f"Not a valid CAFCR viewpoint: {s!r}")


# ── Reasoning mode ────────────────────────────────────────────────────────

class ReasoningMode(str, Enum):
    FORWARD = "forward"            # constraints → decisions
    BACKWARD = "backward"          # decisions → rationale
    QUALITY_NEEDLE = "quality_needle"  # single quality through all views
    EXPLORATORY = "exploratory"    # broad scanning, no fixed direction


# ── Thread state ──────────────────────────────────────────────────────────

class ThreadStatus(str, Enum):
    ACTIVE = "active"
    CONCLUDED = "concluded"
    UNRESOLVED = "unresolved"


class StepAction(str, Enum):
    EXAMINE = "examine"
    TRAVERSE = "traverse"
    QUESTION = "question"
    PROPOSE = "propose"
    EXPECT_TRANSITION = "expect_transition"
    COLLECT_EVIDENCE = "collect_evidence"
    EVALUATE = "evaluate"
    CONCLUDE = "conclude"


class ConclusionType(str, Enum):
    DECISION = "decision"
    VALIDATION = "validation"
    REFUTATION = "refutation"
    DEFERRAL = "deferral"
    PROMOTION = "promotion"
    SUPERSESSION = "supersession"


# ── Thread Step — transition-aware ────────────────────────────────────────

@dataclass
class ThreadStep:
    action: StepAction
    viewpoint: Viewpoint

    # Transition record: what this step consumed and produced
    input_ko_ids: list[str] = field(default_factory=list)     # KOs examined
    output_ko_ids: list[str] = field(default_factory=list)    # KOs created/modified
    evidence_used: list[str] = field(default_factory=list)    # evidence IDs consumed
    assumptions_used: list[str] = field(default_factory=list) # assumptions invoked
    transition_reason: str = ""                                # why this transition

    # Step content
    claim: str = ""
    question: str = ""
    expected_from: str = ""
    expected_status: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    speculative: bool = False


# ── Conclusion ────────────────────────────────────────────────────────────

@dataclass
class Conclusion:
    type: ConclusionType
    target_ko_id: str = ""
    successor_ko_id: str = ""
    rationale: str = ""
    unresolved_tensions: list[str] = field(default_factory=list)


# ── Thread ────────────────────────────────────────────────────────────────

@dataclass
class Thread:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    origin_tension_id: str = ""
    originating_question: str = ""
    reasoning_mode: ReasoningMode = ReasoningMode.EXPLORATORY
    steps: list[ThreadStep] = field(default_factory=list)
    conclusion: Conclusion | None = None
    status: ThreadStatus = ThreadStatus.ACTIVE
    viewpoint_sequence: list[str] = field(default_factory=list)  # ordered, may repeat

    def add_step(self, step: ThreadStep) -> None:
        if self.status != ThreadStatus.ACTIVE:
            raise RuntimeError(f"Thread {self.id} is {self.status}")
        self.steps.append(step)
        self.viewpoint_sequence.append(step.viewpoint.value)

    def conclude(self, conclusion: Conclusion) -> None:
        self.conclusion = conclusion
        self.status = ThreadStatus.CONCLUDED

    def leave_unresolved(self) -> None:
        self.status = ThreadStatus.UNRESOLVED

    def get_viewpoint_sequence(self) -> list[str]:
        return list(self.viewpoint_sequence)

    def is_non_linear(self) -> bool:
        """Check if viewpoint sequence shows revisits (non-linear traversal)."""
        return len(self.viewpoint_sequence) != len(set(self.viewpoint_sequence))
