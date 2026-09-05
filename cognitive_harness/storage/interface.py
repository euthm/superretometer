# FILE: cognitive-harness/storage/interface.py
"""Storage layer contract.

Two mutation paths exist:
  1. Internal (Orchestration, Reasoner): direct KO CRUD with validation
  2. External (Consumer/agent): structured Proposals only — no direct mutation

All mutations record provenance and version. History is never deleted."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
from cognitive_harness.model.ko import KnowledgeObject, RelationType, Dataset
from cognitive_harness.model.proposal import Proposal


class StorageInterface(ABC):
    @abstractmethod
    def create_ko(self, ko: KnowledgeObject) -> str:
        ...

    @abstractmethod
    def update_ko(self, ko_id: str, updates: dict[str, Any]) -> bool:
        """Only for non-canonical KOs. Canonical KOs must be superseded."""
        ...

    @abstractmethod
    def get_ko(self, ko_id: str) -> KnowledgeObject | None:
        ...

    @abstractmethod
    def create_relation(self, from_id: str, to_id: str, rel_type: RelationType) -> bool:
        ...

    @abstractmethod
    def query_by_viewpoint(self, viewpoint_id: str) -> list[KnowledgeObject]:
        ...

    @abstractmethod
    def query_by_type(self, ko_type) -> list[KnowledgeObject]:
        ...

    @abstractmethod
    def query_active_by_scope(self, scope: str) -> list[KnowledgeObject]:
        """Return non-terminal KOs within a scope/domain."""
        ...

    @abstractmethod
    def query_semantic(self, query: str, viewpoint_id: str | None = None, limit: int = 10) -> list[KnowledgeObject]:
        ...

    @abstractmethod
    def list_canonical(self, scope: str | None = None) -> list[KnowledgeObject]:
        ...

    @abstractmethod
    def get_succession_chain(self, ko_id: str) -> list[KnowledgeObject]:
        """Return the full succession chain: [original, ..., current]."""
        ...

    # ── Evidence ──────────────────────────────────────────────────────
    @abstractmethod
    def add_evidence(self, evidence_id: str, claim_id: str, status: str, observation: str, records: list[dict]) -> str:
        ...

    @abstractmethod
    def get_evidence(self, evidence_id: str) -> dict | None:
        ...

    @abstractmethod
    def list_evidence_for_ko(self, ko_id: str) -> list[dict]:
        ...

    # ── Locking ───────────────────────────────────────────────────────
    @abstractmethod
    def lock_ko(self, ko_id: str, thread_id: str) -> bool:
        ...

    @abstractmethod
    def unlock_ko(self, ko_id: str, thread_id: str) -> bool:
        ...

    # ── Impact analysis ──────────────────────────────────────────────
    @abstractmethod
    def compute_impact_set(self, ko_id: str) -> list[str]:
        """Return all downstream KO IDs whose justification path includes ko_id.
        Traverses depends_on, supports, derived_from, validates, constrains, impacts."""
        ...

    @abstractmethod
    def mark_review_required(self, ko_ids: list[str], reason: str) -> int:
        ...

    @abstractmethod
    def clear_review_required(self, ko_id: str) -> bool:
        ...

    @abstractmethod
    def list_review_required(self) -> list[KnowledgeObject]:
        ...

    # ── Proposal pipeline ────────────────────────────────────────────
    @abstractmethod
    def submit_proposal(self, proposal: Proposal) -> str:
        """Accept a structured proposal from external source (agent, tool, human)."""
        ...

    @abstractmethod
    def validate_and_execute(self, proposal_id: str) -> Proposal:
        """Deterministically validate and execute a proposal."""
        ...

    # ── Warrant queries (v0.4) ────────────────────────────────────────
    @abstractmethod
    def list_by_warrant_status(self, warrant_status_str: str) -> list[KnowledgeObject]:
        """List conclusions matching a warrant status (computed externally)."""
        ...

    @abstractmethod
    def list_anti_pattern_hits(self, pattern_str: str) -> list[KnowledgeObject]:
        """List KOs where a specific anti-pattern was detected."""
        ...

    @abstractmethod
    def get_justification_path(self, ko_id: str) -> list[str]:
        """Return ordered list of KO IDs in the justification path."""
        ...

    # ── Dataset operations (v0.5) ──────────────────────────────────────
    @abstractmethod
    def create_dataset(self, dataset: Dataset) -> str:
        ...

    @abstractmethod
    def get_dataset(self, dataset_id: str) -> Dataset | None:
        ...
