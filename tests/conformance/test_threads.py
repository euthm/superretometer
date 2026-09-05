"""Conformance test: competing reasoning threads.

Two threads investigate the same tension from different viewpoints.
One resolves with a decision; the other remains contested.
The tension reflects the unresolved/contested state.
"""
from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus,
    ConfidenceLevel, RelationType, Provenance, Relation,
)
from cognitive_harness.model.tension import Tension, TensionPriority, TensionStatus
from cognitive_harness.model.thread import (
    Thread, ThreadStatus, ReasoningMode, Viewpoint, StepAction,
    ThreadStep, Conclusion, ConclusionType,
)
from cognitive_harness.storage.inmemory import InMemoryStorage


def test_competing_threads():
    """Two threads on the same tension: one resolves, one stays contested.
    The tension should remain investigating or contested."""
    storage = InMemoryStorage()

    # Two competing KOs
    ko_alpha = KnowledgeObject(
        id="ko-alpha", type=KOType.HYPOTHESIS,
        title="Design Alpha: high-speed configuration",
        content="Alpha prioritizes rotational speed.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="team-alpha", author="engineer-1", independent=True),
    )
    ko_beta = KnowledgeObject(
        id="ko-beta", type=KOType.HYPOTHESIS,
        title="Design Beta: high-torque configuration",
        content="Beta prioritizes torque capacity.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="team-beta", author="engineer-2", independent=True),
    )
    storage.create_ko(ko_alpha)
    storage.create_ko(ko_beta)

    # Create tension
    tension = Tension(
        id="tension-design-choice",
        title="Speed vs. torque design trade-off",
        description="Teams disagree on optimal configuration.",
        ko_ids=["ko-alpha", "ko-beta"],
        viewpoint_ids=["functional", "realization"],
        priority=TensionPriority.HIGH,
        status=TensionStatus.INVESTIGATING,
    )
    storage.create_tension(tension)

    # Thread 1: functional viewpoint, resolves with decision for Alpha
    thread1 = Thread(
        id="thread-functional",
        origin_tension_id="tension-design-choice",
        originating_question="Which design meets functional requirements?",
        reasoning_mode=ReasoningMode.FORWARD,
        status=ThreadStatus.ACTIVE,
    )
    thread1.add_step(ThreadStep(
        action=StepAction.EXAMINE,
        viewpoint=Viewpoint.FUNCTIONAL,
        claim="Examining functional requirements for both designs.",
        input_ko_ids=["ko-alpha", "ko-beta"],
    ))
    thread1.add_step(ThreadStep(
        action=StepAction.PROPOSE,
        viewpoint=Viewpoint.FUNCTIONAL,
        claim="Alpha meets speed requirement; Beta meets torque requirement.",
        input_ko_ids=["ko-alpha", "ko-beta"],
    ))
    thread1.add_step(ThreadStep(
        action=StepAction.CONCLUDE,
        viewpoint=Viewpoint.FUNCTIONAL,
        claim="Alpha selected for speed-critical application.",
        output_ko_ids=["ko-alpha"],
    ))
    thread1.conclusion = Conclusion(
        type=ConclusionType.DECISION,
        target_ko_id="ko-alpha",
        rationale="Speed requirement takes priority for this application.",
    )
    storage.create_thread(thread1)

    # Thread 2: realization viewpoint, contested (cannot resolve)
    thread2 = Thread(
        id="thread-realization",
        origin_tension_id="tension-design-choice",
        originating_question="Which design is more manufacturable?",
        reasoning_mode=ReasoningMode.EXPLORATORY,
        status=ThreadStatus.ACTIVE,
    )
    thread2.add_step(ThreadStep(
        action=StepAction.EXAMINE,
        viewpoint=Viewpoint.REALIZATION,
        claim="Examining manufacturing constraints.",
        input_ko_ids=["ko-alpha", "ko-beta"],
    ))
    thread2.add_step(ThreadStep(
        action=StepAction.PROPOSE,
        viewpoint=Viewpoint.REALIZATION,
        claim="Alpha requires tighter tolerances; Beta uses standard tooling.",
        input_ko_ids=["ko-alpha", "ko-beta"],
    ))
    # No conclusion — contested
    storage.create_thread(thread2)

    # Verify both threads exist
    t1 = storage.get_thread("thread-functional")
    t2 = storage.get_thread("thread-realization")
    assert t1 is not None and t2 is not None
    assert len(t1.steps) == 3
    assert len(t2.steps) == 2
    assert t1.conclusion is not None
    assert t1.conclusion.type == ConclusionType.DECISION
    assert t2.conclusion is None

    # Verify tension links to both threads
    tension_obj = storage.get_tension("tension-design-choice")
    assert tension_obj is not None
    assert "thread-functional" in tension_obj.thread_ids
    assert "thread-realization" in tension_obj.thread_ids

    print("  PASS: Competing threads with unresolved/contested outcome")


def test_thread_viewpoint_traversal():
    """Verify viewpoint sequence is tracked through thread steps."""
    storage = InMemoryStorage()

    thread = Thread(
        id="thread-traversal",
        origin_tension_id="tension-x",
        originating_question="Is the design safe?",
        reasoning_mode=ReasoningMode.FORWARD,
        status=ThreadStatus.ACTIVE,
    )
    thread.add_step(ThreadStep(
        action=StepAction.EXAMINE, viewpoint=Viewpoint.CONCEPTUAL,
        claim="What are we trying to achieve?",
    ))
    thread.add_step(ThreadStep(
        action=StepAction.EXAMINE, viewpoint=Viewpoint.FUNCTIONAL,
        claim="What must the system do?",
    ))
    thread.add_step(ThreadStep(
        action=StepAction.PROPOSE, viewpoint=Viewpoint.REALIZATION,
        claim="How is it built?",
    ))
    thread.add_step(ThreadStep(
        action=StepAction.EVALUATE, viewpoint=Viewpoint.APPLICATION,
        claim="Does it work in practice?",
    ))
    storage.create_thread(thread)

    saved = storage.get_thread("thread-traversal")
    assert saved is not None
    viewpoints = [s.viewpoint.value for s in saved.steps]
    assert viewpoints == ["conceptual", "functional", "realization", "application"], \
        f"Viewpoint traversal: {viewpoints}"
    assert saved.viewpoint_sequence == ["conceptual", "functional", "realization", "application"]

    print("  PASS: Viewpoint traversal tracked correctly")


if __name__ == "__main__":
    test_competing_threads()
    test_thread_viewpoint_traversal()
    print("\nCompeting threads conformance: PASS")
