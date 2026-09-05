# FILE: cognitive-harness/reasoning/interface.py
from __future__ import annotations
from abc import ABC, abstractmethod
from cognitive_harness.model.thread import Thread, ThreadStep, Conclusion


class ReasonerInterface(ABC):
    """Reasoning layer contract. LLM-agnostic.

    The reasoner produces structured steps and conclusions.
    It never writes to storage directly; all mutations go through
    the Orchestration layer via Proposals or Conclusions."""

    @abstractmethod
    def start_thread(self, thread: Thread, ko_ids: list[str], canonical_ids: list[str]) -> ThreadStep:
        """Begin reasoning on a thread. Returns first step."""
        ...

    @abstractmethod
    def continue_thread(self, thread: Thread) -> ThreadStep | Conclusion:
        """Continue a thread. Returns next step or a Conclusion."""
        ...
