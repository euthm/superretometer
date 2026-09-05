# FILE: cognitive-harness/model/proposal.py
"""Structured proposal — the ONLY mutation path for Consumers (LLMs, humans).

A Proposal is a typed request for a state change. It is validated deterministically
by the Orchestration layer before any mutation is applied to canonical state.
LLMs can never call create_ko / update_ko directly; they submit Proposals.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from enum import Enum
from cognitive_harness.model.ko import KOType, EpistemicStatus, ConfidenceLevel, RelationType
from cognitive_harness.model.thread import Viewpoint


# ── Proposal types ────────────────────────────────────────────────────────

class ProposalType(str, Enum):
    CREATE_KO = "create_ko"
    UPDATE_KO = "update_ko"           # only non-canonical KOs
    TRANSITION_STATUS = "transition_status"  # propose → validated → canonical
    CREATE_RELATION = "create_relation"
    CREATE_TENSION = "create_tension"
    CREATE_EVIDENCE = "create_evidence"
    PROMOTE_CANONICAL = "promote_canonical"
    SUPERSEDE = "supersede"           # supersede a canonical KO with a successor


# ── Proposal states ───────────────────────────────────────────────────────

class ProposalState(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PARTIALLY_ACCEPTED = "partially_accepted"


# ── Proposals ─────────────────────────────────────────────────────────────

@dataclass
class Proposal:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: ProposalType = ProposalType.CREATE_KO
    proposer: str = ""               # agent session ID, human ID, tool identifier
    rationale: str = ""
    state: ProposalState = ProposalState.PENDING
    rejection_reason: str = ""

    # CREATE_KO fields
    ko_type: KOType | None = None
    ko_title: str = ""
    ko_content: object | None = None
    ko_viewpoints: list[str] = field(default_factory=list)
    ko_assumptions: list[str] = field(default_factory=list)
    ko_scope: str = ""
    ko_valid_from: str | None = None
    ko_valid_to: str | None = None
    ko_confidence: ConfidenceLevel = ConfidenceLevel.SPECULATIVE

    # UPDATE_KO fields
    target_ko_id: str = ""
    updates: dict = field(default_factory=dict)

    # TRANSITION_STATUS fields
    target_status: EpistemicStatus | None = None

    # CREATE_RELATION fields
    from_ko_id: str = ""
    to_ko_id: str = ""
    relation_type: RelationType | None = None

    # CREATE_TENSION fields
    tension_title: str = ""
    tension_description: str = ""
    tension_ko_ids: list[str] = field(default_factory=list)
    tension_viewpoints: list[str] = field(default_factory=list)

    # CREATE_EVIDENCE fields
    evidence_claim_id: str = ""
    evidence_observation: str = ""
    evidence_records: list[dict] = field(default_factory=list)

    # SUPERSEDE fields
    successor_ko_id: str = ""       # must be a valid non-terminal KO

    # Result: set by orchestrator after validation
    created_ko_id: str = ""
    created_evidence_id: str = ""
    created_tension_id: str = ""
