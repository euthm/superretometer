# FILE: cognitive-harness/storage/inmemory.py
"""In-memory Storage implementation with full proposal pipeline.

Demonstrates:
- Proposal validation before any mutation
- Supersession with history preservation
- Temporal validity
- Succession chains
"""
from __future__ import annotations
import uuid
from cognitive_harness.model.ko import (
    KnowledgeObject, EpistemicStatus, RelationType, VALID_TRANSITIONS,
    Relation, Provenance, IMPACT_RELATIONS, JUSTIFICATION_RELATIONS, Dataset,
)
from cognitive_harness.model.proposal import Proposal, ProposalType, ProposalState
from cognitive_harness.model.tension import Tension
from cognitive_harness.model.thread import Viewpoint, Thread
from cognitive_harness.storage.interface import StorageInterface


class InMemoryStorage(StorageInterface):
    enumeration_complete = True  # _kos.values() returns every object

    def __init__(self):
        self._kos: dict[str, KnowledgeObject] = {}
        self._evidence: dict[str, dict] = {}
        self._locks: dict[str, str] = {}
        self._proposals: dict[str, Proposal] = {}
        self._datasets: dict[str, Dataset] = {}

    # ── KO CRUD (internal path: Orchestration/Reasoner) ──────────────

    def create_ko(self, ko: KnowledgeObject) -> str:
        self._kos[ko.id] = ko
        return ko.id

    def update_ko(self, ko_id: str, updates: dict) -> bool:
        ko = self._kos.get(ko_id)
        if ko is None:
            return False
        if ko.is_canonical():
            return False  # canonical KOs must be superseded, not updated
        for k, v in updates.items():
            if k == "epistemic_status":
                if not ko.can_transition_to(v):
                    return False
            if hasattr(ko, k):
                setattr(ko, k, v)
        return True

    def get_ko(self, ko_id: str) -> KnowledgeObject | None:
        return self._kos.get(ko_id)

    def create_relation(self, from_id: str, to_id: str, rel_type: RelationType) -> bool:
        fr = self._kos.get(from_id)
        if fr is None or self._kos.get(to_id) is None:
            return False
        fr.relations.append(Relation(to=to_id, type=rel_type))
        return True

    # ── Direction-aware relation access (v0.6.4) ──────────────────────

    def get_outgoing_relations(self, ko_id: str, relation_types: frozenset | None = None) -> list[tuple[str, RelationType]]:
        """Return outgoing relations: (to_id, type)."""
        ko = self._kos.get(ko_id)
        if ko is None:
            return []
        result = [(r.to, r.type) for r in ko.relations]
        if relation_types:
            result = [(to, t) for to, t in result if t in relation_types]
        return result

    def get_incoming_relations(self, ko_id: str, relation_types: frozenset | None = None) -> list[tuple[str, RelationType]]:
        """Return incoming relations: (from_id, type)."""
        result = []
        for kid, ko in self._kos.items():
            for r in ko.relations:
                if r.to == ko_id:
                    if relation_types is None or r.type in relation_types:
                        result.append((kid, r.type))
        return result

    # ── Queries ───────────────────────────────────────────────────────

    def query_by_viewpoint(self, viewpoint_id: str) -> list[KnowledgeObject]:
        return [ko for ko in self._kos.values() if viewpoint_id in ko.viewpoint_ids]

    def query_by_type(self, ko_type) -> list[KnowledgeObject]:
        return [ko for ko in self._kos.values() if ko.type == ko_type]

    def query_active_by_scope(self, scope: str) -> list[KnowledgeObject]:
        return [
            ko for ko in self._kos.values()
            if scope in ko.scope and not ko.epistemic_status.is_terminal
        ]

    def query_semantic(self, query: str, viewpoint_id: str | None = None, limit: int = 10) -> list[KnowledgeObject]:
        results = []
        q = query.lower()
        for ko in self._kos.values():
            if viewpoint_id and viewpoint_id not in ko.viewpoint_ids:
                continue
            title_match = q in ko.title.lower()
            content_match = isinstance(ko.content, str) and q in ko.content.lower()
            if title_match or content_match:
                results.append(ko)
        return results[:limit]

    def list_canonical(self, scope: str | None = None) -> list[KnowledgeObject]:
        cos = [ko for ko in self._kos.values() if ko.epistemic_status == EpistemicStatus.CANONICAL]
        if scope:
            cos = [ko for ko in cos if scope in ko.scope]
        return cos

    def get_succession_chain(self, ko_id: str) -> list[KnowledgeObject]:
        """Build succession chain from oldest to newest.
        Follows superseded_by_id forward, then supersedes_id backward."""
        # First: go backward to find the oldest ancestor
        ancestors = []
        current_id = ko_id
        while current_id:
            ko = self._kos.get(current_id)
            if ko is None:
                break
            ancestors.append(ko)
            current_id = ko.supersedes_id or None  # "this supersedes that"
        ancestors.reverse()  # oldest first

        # Then: go forward from the last ancestor via superseded_by_id
        chain = list(ancestors)
        last = ancestors[-1] if ancestors else None
        while last and last.superseded_by_id:
            nxt = self._kos.get(last.superseded_by_id)
            if nxt is None:
                break
            chain.append(nxt)
            last = nxt
        return chain

    def compute_impact_set(self, ko_id: str) -> list[str]:
        """BFS: find all KOs downstream of ko_id.
        
        Impact semantics (v0.6.4): if X changes, which KOs are affected?
        
        For OUTBOUND relations (DEPENDS_ON, DERIVED_FROM):
          X is a prerequisite. Find KOs Y where Y -> DEPENDS_ON/DERIVED_FROM -> X.
          These Y dependents are affected.
        
        For INBOUND relations (SUPPORTS, VALIDATES):
          X is evidence/support. Find the target Z where X -> SUPPORTS/VALIDATES -> Z.
          The claim Z loses support and is affected.
          Do NOT recurse backward from Z through its own evidence — 
          that would create false impact from conclusions back to evidence.
        
        For CONSTRAINS, IMPACTS:
          X constrains/impacts Z. Find X -> CONSTRAINS/IMPACTS -> Z.
        """
        impacted: set[str] = set()
        queue = [ko_id]
        while queue:
            current = queue.pop(0)
            
            # Case 1: Find KOs that depend on current (incoming DEPENDS_ON, DERIVED_FROM)
            for ko in self._kos.values():
                for rel in ko.relations:
                    if rel.type in (RelationType.DEPENDS_ON, RelationType.DERIVED_FROM) and rel.to == current:
                        if ko.id not in impacted:
                            impacted.add(ko.id)
                            queue.append(ko.id)
            
            # Case 2: current is evidence — find claims it supports (outgoing SUPPORTS, VALIDATES)
            ko_cur = self._kos.get(current)
            if ko_cur:
                for rel in ko_cur.relations:
                    if rel.type in (RelationType.SUPPORTS, RelationType.VALIDATES):
                        if rel.to not in impacted:
                            impacted.add(rel.to)
                            queue.append(rel.to)
            
            # Case 3: current constrains/impacts others (outgoing CONSTRAINS, IMPACTS)
            if ko_cur:
                for rel in ko_cur.relations:
                    if rel.type in (RelationType.CONSTRAINS, RelationType.IMPACTS):
                        if rel.to not in impacted:
                            impacted.add(rel.to)
                            queue.append(rel.to)
        return list(impacted)

    def mark_review_required(self, ko_ids: list[str], reason: str) -> int:
        """Mark KOs as needing reassessment. Does not change epistemic status."""
        marked = 0
        for kid in ko_ids:
            ko = self._kos.get(kid)
            if ko and not ko.epistemic_status.is_terminal:
                if not ko.review_required:
                    ko.review_required = True
                    ko.review_reason = reason
                    marked += 1
        return marked

    def clear_review_required(self, ko_id: str) -> bool:
        ko = self._kos.get(ko_id)
        if ko and ko.review_required:
            ko.review_required = False
            ko.review_reason = ""
            return True
        return False

    def list_review_required(self) -> list[KnowledgeObject]:
        return [ko for ko in self._kos.values() if ko.review_required]

    # ── Evidence ──────────────────────────────────────────────────────

    def add_evidence(self, evidence_id, claim_id, status, observation, records):
        ev = {
            "id": evidence_id,
            "claim_id": claim_id,
            "status": status,
            "observation": observation,
            "records": records,
        }
        self._evidence[evidence_id] = ev
        ko = self._kos.get(claim_id)
        if ko and evidence_id not in ko.evidence_ids:
            ko.evidence_ids.append(evidence_id)
        return evidence_id

    def get_evidence(self, evidence_id) -> dict | None:
        return self._evidence.get(evidence_id)

    def list_evidence_for_ko(self, ko_id: str) -> list[dict]:
        return [ev for ev in self._evidence.values() if ev["claim_id"] == ko_id]

    # ── Locking ───────────────────────────────────────────────────────

    def lock_ko(self, ko_id: str, thread_id: str) -> bool:
        if ko_id in self._locks:
            return False
        self._locks[ko_id] = thread_id
        return True

    def unlock_ko(self, ko_id: str, thread_id: str) -> bool:
        if self._locks.get(ko_id) == thread_id:
            del self._locks[ko_id]
            return True
        return False

    # ── Proposal validation and execution ─────────────────────────────

    def submit_proposal(self, proposal: Proposal) -> str:
        self._proposals[proposal.id] = proposal
        return proposal.id

    def validate_and_execute(self, proposal_id: str) -> Proposal:
        """Deterministic validation rules for each proposal type."""
        p = self._proposals.get(proposal_id)
        if p is None:
            raise ValueError(f"Proposal {proposal_id} not found")

        if p.type == ProposalType.CREATE_KO:
            self._validate_create_ko(p)
        elif p.type == ProposalType.UPDATE_KO:
            self._validate_update_ko(p)
        elif p.type == ProposalType.TRANSITION_STATUS:
            self._validate_transition(p)
        elif p.type == ProposalType.CREATE_RELATION:
            self._validate_create_relation(p)
        elif p.type == ProposalType.CREATE_TENSION:
            self._validate_create_tension(p)
        elif p.type == ProposalType.CREATE_EVIDENCE:
            self._validate_create_evidence(p)
        elif p.type == ProposalType.PROMOTE_CANONICAL:
            self._validate_promote_canonical(p)
        elif p.type == ProposalType.SUPERSEDE:
            self._validate_supersede(p)
        else:
            p.state = ProposalState.REJECTED
            p.rejection_reason = f"Unknown proposal type: {p.type}"

        return p

    def _validate_create_ko(self, p: Proposal) -> None:
        if not p.ko_title:
            p.state = ProposalState.REJECTED
            p.rejection_reason = "ko_title is required"
            return
        from cognitive_harness.model.ko import KnowledgeObject, KOType, ConfidenceLevel, JUSTIFICATION_RELATIONS
        ko = KnowledgeObject(
            type=p.ko_type or KOType.HYPOTHESIS,
            title=p.ko_title,
            content=p.ko_content,
            viewpoint_ids=[Viewpoint.from_str(v).value for v in p.ko_viewpoints] if p.ko_viewpoints else [],
            assumptions=list(p.ko_assumptions),
            scope=p.ko_scope,
            confidence=p.ko_confidence,
            provenance=Provenance(source="proposal", author=p.proposer),
        )
        self.create_ko(ko)
        p.created_ko_id = ko.id
        p.state = ProposalState.ACCEPTED

    def _validate_update_ko(self, p: Proposal) -> None:
        ko = self._kos.get(p.target_ko_id)
        if ko is None:
            p.state = ProposalState.REJECTED
            p.rejection_reason = f"KO {p.target_ko_id} not found"
            return
        if ko.is_canonical():
            p.state = ProposalState.REJECTED
            p.rejection_reason = "Cannot update canonical KO directly; use SUPERSEDE"
            return
        if "epistemic_status" in p.updates:
            target = p.updates["epistemic_status"]
            if not ko.can_transition_to(target):
                p.state = ProposalState.REJECTED
                p.rejection_reason = (
                    f"Invalid transition: {ko.epistemic_status} → {target}"
                )
                return
        self.update_ko(p.target_ko_id, p.updates)
        p.state = ProposalState.ACCEPTED

    def _validate_transition(self, p: Proposal) -> None:
        ko = self._kos.get(p.target_ko_id)
        if ko is None:
            p.state = ProposalState.REJECTED
            p.rejection_reason = f"KO {p.target_ko_id} not found"
            return
        if not p.target_status:
            p.state = ProposalState.REJECTED
            p.rejection_reason = "target_status is required"
            return
        if not ko.can_transition_to(p.target_status):
            p.state = ProposalState.REJECTED
            p.rejection_reason = (
                f"Invalid transition: {ko.epistemic_status} → {p.target_status}"
            )
            return
        # Check: promotion to canonical requires >= MEDIUM confidence
        if p.target_status == EpistemicStatus.CANONICAL and ko.confidence.value < "medium":
            p.state = ProposalState.REJECTED
            p.rejection_reason = (
                f"Cannot promote to canonical with {ko.confidence} confidence; need >= MEDIUM"
            )
            return
        # Check: at least one verified evidence for promotion
        if p.target_status in (EpistemicStatus.VALIDATED, EpistemicStatus.CANONICAL):
            verified = [
                ev for ev in self.list_evidence_for_ko(ko.id)
                if ev.get("status") == "verified"
            ]
            if not verified:
                p.state = ProposalState.REJECTED
                p.rejection_reason = "No verified evidence; cannot validate"
                return
        ko.epistemic_status = p.target_status
        p.state = ProposalState.ACCEPTED

    def _validate_create_relation(self, p: Proposal) -> None:
        if not p.from_ko_id or not p.to_ko_id or not p.relation_type:
            p.state = ProposalState.REJECTED
            p.rejection_reason = "from_ko_id, to_ko_id, and relation_type required"
            return
        if not self.create_relation(p.from_ko_id, p.to_ko_id, p.relation_type):
            p.state = ProposalState.REJECTED
            p.rejection_reason = "Relation creation failed (KO not found)"
            return
        p.state = ProposalState.ACCEPTED

    def _validate_create_tension(self, p: Proposal) -> None:
        if not p.tension_title:
            p.state = ProposalState.REJECTED
            p.rejection_reason = "tension_title required"
            return
        p.state = ProposalState.ACCEPTED
        # Tension creation is handled by Orchestration; storage just validates

    def _validate_create_evidence(self, p: Proposal) -> None:
        if not p.evidence_claim_id:
            p.state = ProposalState.REJECTED
            p.rejection_reason = "evidence_claim_id required"
            return
        ko = self._kos.get(p.evidence_claim_id)
        if ko is None:
            p.state = ProposalState.REJECTED
            p.rejection_reason = f"Claim KO {p.evidence_claim_id} not found"
            return
        eid = str(uuid.uuid4())
        self.add_evidence(eid, p.evidence_claim_id, "pending", p.evidence_observation, p.evidence_records)
        p.created_evidence_id = eid
        p.state = ProposalState.ACCEPTED

    def _validate_promote_canonical(self, p: Proposal) -> None:
        ko = self._kos.get(p.target_ko_id)
        if ko is None:
            p.state = ProposalState.REJECTED
            p.rejection_reason = f"KO {p.target_ko_id} not found"
            return
        if ko.epistemic_status != EpistemicStatus.VALIDATED:
            p.state = ProposalState.REJECTED
            p.rejection_reason = (
                f"Only VALIDATED KOs can be promoted to canonical; current: {ko.epistemic_status}"
            )
            return
        ko.epistemic_status = EpistemicStatus.CANONICAL
        p.state = ProposalState.ACCEPTED

    def _validate_supersede(self, p: Proposal) -> None:
        old_ko = self._kos.get(p.target_ko_id)
        new_ko = self._kos.get(p.successor_ko_id)
        if old_ko is None:
            p.state = ProposalState.REJECTED
            p.rejection_reason = f"Target KO {p.target_ko_id} not found"
            return
        if new_ko is None:
            p.state = ProposalState.REJECTED
            p.rejection_reason = f"Successor KO {p.successor_ko_id} not found"
            return
        if new_ko.epistemic_status.is_terminal:
            p.state = ProposalState.REJECTED
            p.rejection_reason = "Successor KO cannot be terminal"
            return
        # Execute supersession: mark old as superseded, link both ways
        old_ko.epistemic_status = EpistemicStatus.SUPERSEDED
        old_ko.superseded_by_id = new_ko.id
        new_ko.supersedes_id = old_ko.id
        new_ko.relations.append(Relation(to=old_ko.id, type=RelationType.SUPERSEDES))

        # Compute impact set: downstream KOs that depend on the old canonical
        impacted = self.compute_impact_set(old_ko.id)
        if impacted:
            reason = (
                f"Superseded KO {old_ko.id[:8]}... ({old_ko.title[:50]}); "
                f"successor is {new_ko.id[:8]}..."
            )
            marked = self.mark_review_required(impacted, reason)
        p.state = ProposalState.ACCEPTED

    # ── Warrant queries (v0.4) ───────────────────────────────────────

    def list_by_warrant_status(self, warrant_status_str: str) -> list[KnowledgeObject]:
        return []

    def list_anti_pattern_hits(self, pattern_str: str) -> list[KnowledgeObject]:
        return [
            ko for ko in self._kos.values()
            if pattern_str in ko.anti_patterns
        ]

    def get_justification_path(self, ko_id: str) -> list[str]:
        """Direction-aware justification path.
        
        From a conclusion, find all KOs in its justification chain:
        - OUTGOING DEPENDS_ON, DERIVED_FROM → prerequisites and sources
        - INCOMING SUPPORTS, VALIDATES → supporting evidence
        """
        visited: set[str] = set()
        queue = [ko_id]
        path = []
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            path.append(current)
            
            # Outbound: follow dependencies and derivations
            ko = self._kos.get(current)
            if ko is not None:
                for rel in ko.relations:
                    if rel.type in JUSTIFICATION_OUTBOUND and rel.to not in visited:
                        queue.append(rel.to)
            
            # Inbound: follow supporting evidence
            for from_id, rel_type in self.get_incoming_relations(current, JUSTIFICATION_INBOUND):
                if from_id not in visited:
                    queue.append(from_id)
        return path

    # ── Dataset operations (v0.5) ──────────────────────────────────────

    def create_dataset(self, dataset: Dataset) -> str:
        self._datasets[dataset.id] = dataset
        return dataset.id

    def get_dataset(self, dataset_id: str) -> Dataset | None:
        return self._datasets.get(dataset_id)

    # ── Supersession ──────────────────────────────────────────────────

    def supersede(self, old_ko_id: str, new_ko_id: str) -> bool:
        """Supersede old_ko with new_ko. Old KO marked SUPERSEDED."""
        old = self._kos.get(old_ko_id)
        new = self._kos.get(new_ko_id)
        if old is None or new is None:
            return False
        if new.epistemic_status.is_terminal:
            return False
        old.epistemic_status = EpistemicStatus.SUPERSEDED
        old.superseded_by_id = new_ko_id
        new.supersedes_id = old_ko_id

        # Impact propagation: mark downstream as review-required
        impacted = self.compute_impact_set(old_ko_id)
        if impacted:
            reason = f"Superseded KO {old_ko_id[:8]} ({old.title[:50]}); successor {new_ko_id[:8]}"
            self.mark_review_required(impacted, reason)
        return True

    # ── Tension operations ────────────────────────────────────────────

    def create_tension(self, tension) -> str:
        if not hasattr(self, '_tensions'):
            self._tensions = {}
        self._tensions[tension.id] = tension
        return tension.id

    def get_tension(self, tension_id: str):
        return getattr(self, '_tensions', {}).get(tension_id)

    def list_tensions(self):
        return list(getattr(self, '_tensions', {}).values())

    # ── Thread operations ─────────────────────────────────────────────

    def create_thread(self, thread) -> str:
        if not hasattr(self, '_threads'):
            self._threads = {}
        self._threads[thread.id] = thread
        # Link thread to tension
        if thread.origin_tension_id:
            tension = self.get_tension(thread.origin_tension_id)
            if tension and thread.id not in tension.thread_ids:
                tension.thread_ids.append(thread.id)
        return thread.id

    def get_thread(self, thread_id: str):
        return getattr(self, '_threads', {}).get(thread_id)

    def list_threads(self):
        return list(getattr(self, '_threads', {}).values())

    # ── Iteration (v0.6.3) ────────────────────────────────────────────

    def list_all_kos(self) -> list[KnowledgeObject]:
        return list(self._kos.values())
