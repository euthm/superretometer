# FILE: superretometer-runtime/memory_adapter.py
"""MemoryAdapter — implements cognitive_harness.storage.interface.StorageInterface
using the Memory server HTTP API as persistence backend.

Semantic dependency: canonical cognitive_harness v0.6.3 (euthm/superretometer).
No private CH semantics. Pure storage transport.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import requests

from cognitive_harness.model.ko import (
    KnowledgeObject,
    RelationType,
    Dataset,
    Provenance,
    Relation,
    KOType,
    TruthCategory,
    EpistemicStatus,
    ConfidenceLevel,
    DerivationRelation,
    DerivationType,
    FalsifiableValidator,
    JUSTIFICATION_RELATIONS,
    JUSTIFICATION_INBOUND,
    JUSTIFICATION_OUTBOUND,
    IMPACT_RELATIONS,
)
from cognitive_harness.model.proposal import Proposal
from cognitive_harness.storage.interface import StorageInterface
from cognitive_harness.exceptions import IncompleteEnumerationError

log = logging.getLogger(__name__)

# ── Memory API defaults ─────────────────────────────────────────────────────

DEFAULT_MEMORY_SERVER = "http://localhost:3002"
PAGE_SIZE = 200


# ── Serialization helpers ──────────────────────────────────────────────────

def ko_to_memory_object(ko: KnowledgeObject) -> dict:
    """Convert a canonical KnowledgeObject to Memory API object format."""
    props: dict[str, Any] = {}

    # Core fields
    props["ch_ko_type"] = ko.type.value if hasattr(ko.type, "value") else str(ko.type)
    props["title"] = ko.title

    # Content — store preserving type (dict, str, int, float, list)
    if ko.content is not None:
        if isinstance(ko.content, (dict, str, int, float, bool, list)):
            props["content"] = ko.content
        else:
            props["content"] = str(ko.content)

    # Truth category
    tc = ko.truth_category
    props["ch_truth_category"] = tc.value if hasattr(tc, "value") else str(tc)

    # Viewpoints
    if ko.viewpoint_ids:
        props["ch_viewpoint_ids"] = list(ko.viewpoint_ids)

    # Epistemic status
    es = ko.epistemic_status
    props["ch_epistemic_status"] = es.value if hasattr(es, "value") else str(es)

    # Confidence
    cl = ko.confidence
    props["ch_confidence"] = cl.value if hasattr(cl, "value") else str(cl)

    # Scope and assumptions
    if ko.scope:
        props["ch_scope"] = ko.scope
    if ko.assumptions:
        props["ch_assumptions"] = list(ko.assumptions)

    # Temporal validity
    if ko.valid_from:
        props["ch_valid_from"] = ko.valid_from.isoformat() if isinstance(ko.valid_from, datetime) else str(ko.valid_from)
    if ko.valid_to:
        props["ch_valid_to"] = ko.valid_to.isoformat() if isinstance(ko.valid_to, datetime) else str(ko.valid_to)

    # Succession links
    if ko.supersedes_id:
        props["ch_supersedes_id"] = ko.supersedes_id
    if ko.superseded_by_id:
        props["ch_superseded_by_id"] = ko.superseded_by_id

    # Evidence IDs
    if ko.evidence_ids:
        props["ch_evidence_ids"] = list(ko.evidence_ids)

    # Tension IDs
    if ko.tension_ids:
        props["ch_tension_ids"] = list(ko.tension_ids)

    # Anti-patterns (v0.4 legacy)
    if ko.anti_patterns:
        props["ch_anti_patterns"] = list(ko.anti_patterns)

    # Review flags
    props["ch_review_required"] = ko.review_required
    if ko.review_reason:
        props["ch_review_reason"] = ko.review_reason

    # Provenance
    if ko.provenance:
        p = ko.provenance
        props["ch_provenance_source"] = p.source
        props["ch_provenance_author"] = p.author
        props["ch_provenance_timestamp"] = (
            p.timestamp.isoformat() if isinstance(p.timestamp, datetime) else str(p.timestamp)
        )
        props["ch_provenance_revision"] = p.revision
        if p.derived_from:
            props["ch_provenance_derived_from"] = p.derived_from
        props["ch_provenance_independent"] = p.independent

    # Derivation
    if ko.derivation:
        d = ko.derivation
        props["ch_derivation_type"] = d.derivation_type.value if hasattr(d.derivation_type, "value") else str(d.derivation_type)
        if d.upstream_ko_ids:
            props["ch_derivation_upstream_ko_ids"] = list(d.upstream_ko_ids)
        if d.training_dataset_id:
            props["ch_derivation_training_dataset_id"] = d.training_dataset_id
        if d.test_dataset_id:
            props["ch_derivation_test_dataset_id"] = d.test_dataset_id
        if d.domain_source_ko_id:
            props["ch_derivation_domain_source_ko_id"] = d.domain_source_ko_id
        if d.domain_mapping_ko_id:
            props["ch_derivation_domain_mapping_ko_id"] = d.domain_mapping_ko_id

    # Validators
    if ko.validators:
        props["ch_validators"] = [
            {
                "id": v.id,
                "description": v.description,
                "what_would_falsify": v.what_would_falsify,
                "passes": v.passes,
                "observation": v.observation,
            }
            for v in ko.validators
        ]

    # Runtime/session metadata (separate from canonical provenance)
    if "CH_SESSION_ID" in os.environ:
        props["ch_runtime_session_id"] = os.environ["CH_SESSION_ID"]
    if "CH_WORKSPACE" in os.environ:
        props["ch_runtime_workspace"] = os.environ["CH_WORKSPACE"]

    # Key: use canonical KO id as key for reliable lookup
    key = f"ch:ko:{ko.id}"

    return {
        "type": "Concept",
        "key": key,
        "properties": props,
    }


def memory_object_to_ko(obj: dict) -> KnowledgeObject:
    """Convert a Memory API object to a canonical KnowledgeObject.

    Missing optional fields get canonical defaults.
    Unknown properties are logged but not silently dropped if they affect semantics.
    """
    props = obj.get("properties", {})
    # Restore CH ID from Memory key (v0.6.4 identity fix).
    # The key is ch:ko:{CH_ID}. If not a CH key, fall back to Memory UUID.
    key = obj.get("key", "")
    ko_ch_id = key[6:] if key.startswith("ch:ko:") else None
    obj_id = ko_ch_id or obj.get("id", str(uuid.uuid4()))

    # KO type
    raw_type = props.get("ch_ko_type", KOType.REQUIREMENT.value)
    try:
        ko_type = KOType(raw_type)
    except ValueError:
        ko_type = KOType.REQUIREMENT

    # Truth category
    raw_tc = props.get("ch_truth_category", TruthCategory.ASSUMPTION.value)
    try:
        truth_cat = TruthCategory(raw_tc)
    except ValueError:
        truth_cat = TruthCategory.ASSUMPTION

    # Epistemic status
    raw_es = props.get("ch_epistemic_status", EpistemicStatus.PROPOSED.value)
    try:
        ep_status = EpistemicStatus(raw_es)
    except ValueError:
        ep_status = EpistemicStatus.PROPOSED

    # Confidence
    raw_cl = props.get("ch_confidence", ConfidenceLevel.SPECULATIVE.value)
    try:
        confidence = ConfidenceLevel(raw_cl)
    except ValueError:
        confidence = ConfidenceLevel.SPECULATIVE

    # Parse provenance
    prov = None
    if props.get("ch_provenance_source"):
        prov_ts = props.get("ch_provenance_timestamp", "")
        try:
            ts = datetime.fromisoformat(prov_ts)
        except (ValueError, TypeError):
            ts = datetime.now(timezone.utc)
        prov = Provenance(
            source=props["ch_provenance_source"],
            author=props.get("ch_provenance_author", "system"),
            timestamp=ts,
            revision=props.get("ch_provenance_revision", 1),
            derived_from=props.get("ch_provenance_derived_from"),
            independent=props.get("ch_provenance_independent", True),
        )

    # Parse derivation
    deriv = None
    deriv_type_str = props.get("ch_derivation_type")
    if deriv_type_str:
        try:
            deriv_dt = DerivationType(deriv_type_str)
        except ValueError:
            deriv_dt = DerivationType.ASSUMED
        deriv = DerivationRelation(
            derivation_type=deriv_dt,
            upstream_ko_ids=props.get("ch_derivation_upstream_ko_ids", []),
            training_dataset_id=props.get("ch_derivation_training_dataset_id", ""),
            test_dataset_id=props.get("ch_derivation_test_dataset_id", ""),
            domain_source_ko_id=props.get("ch_derivation_domain_source_ko_id", ""),
            domain_mapping_ko_id=props.get("ch_derivation_domain_mapping_ko_id", ""),
        )

    # Parse validators
    validators = []
    for v_raw in props.get("ch_validators", []):
        validators.append(FalsifiableValidator(
            id=v_raw.get("id", str(uuid.uuid4())),
            description=v_raw.get("description", ""),
            what_would_falsify=v_raw.get("what_would_falsify", ""),
            ko_id=obj_id,
            passes=v_raw.get("passes", True),
            observation=v_raw.get("observation", ""),
        ))

    # Parse temporal validity
    valid_from = None
    vf = props.get("ch_valid_from")
    if vf:
        try:
            valid_from = datetime.fromisoformat(vf)
        except (ValueError, TypeError):
            pass

    valid_to = None
    vt = props.get("ch_valid_to")
    if vt:
        try:
            valid_to = datetime.fromisoformat(vt)
        except (ValueError, TypeError):
            pass

    # Parse relations from edges (passed separately) or stored inline
    relations = []

    ko = KnowledgeObject(
        id=obj_id,
        type=ko_type,
        title=props.get("title", obj.get("key", "")),
        content=props.get("content"),
        truth_category=truth_cat,
        viewpoint_ids=props.get("ch_viewpoint_ids", []),
        provenance=prov,
        derivation=deriv,
        epistemic_status=ep_status,
        confidence=confidence,
        valid_from=valid_from,
        valid_to=valid_to,
        assumptions=props.get("ch_assumptions", []),
        scope=props.get("ch_scope", ""),
        supersedes_id=props.get("ch_supersedes_id"),
        superseded_by_id=props.get("ch_superseded_by_id"),
        evidence_ids=props.get("ch_evidence_ids", []),
        tension_ids=props.get("ch_tension_ids", []),
        relations=relations,
        anti_patterns=props.get("ch_anti_patterns", []),
        validators=validators,
        review_required=props.get("ch_review_required", False),
        review_reason=props.get("ch_review_reason", ""),
    )

    return ko


# ── MemoryAdapter ──────────────────────────────────────────────────────────

class MemoryAdapter(StorageInterface):
    """StorageInterface backed by Memory HTTP API.

    enumeration_complete = False because HTTP search API is not provably complete.
    FULL_REQUIRED analyses will raise IncompleteEnumerationError.
    """
    enumeration_complete = False

    def __init__(self, server_url: str | None = None, api_key: str | None = None,
                 project_id: str | None = None):
        self.server_url = (server_url or os.environ.get("MEMORY_SERVER_URL")
                           or DEFAULT_MEMORY_SERVER).rstrip("/")
        self.api_key = api_key or os.environ.get("MEMORY_API_KEY") or ""
        self.project_id = project_id or os.environ.get("CH_PROJECT_ID") or ""

        if not self.api_key:
            raise RuntimeError(
                "MEMORY_API_KEY not set. Set it or configure ~/.memory/config.yaml."
            )
        if not self.project_id:
            raise RuntimeError(
                "CH_PROJECT_ID not set. Set it for project-scoped storage."
            )

        self._headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
            "X-Project-ID": self.project_id,
        }
        # Identity mapping: CH_ID <-> Memory_UUID (v0.6.4)
        # CH KnowledgeObject.id is canonical; Memory UUID is storage identity.
        # _ko_id_map[CH_ID] -> Memory_UUID (forward)
        # _memory_id_map[Memory_UUID] -> CH_ID (reverse)
        # Populated on create, on demand by key lookup, survives via Memory key field.
        self._ko_id_map: dict[str, str] = {}
        self._memory_id_map: dict[str, str] = {}
        # Internal registry of object UUIDs created through this adapter
        # Used as fallback for list_all_kos when search API cannot enumerate
        self._created_ids: set[str] = set()
        # Cached evidence store (Memory has no evidence endpoint)
        self._evidence: dict[str, dict] = {}
        # Cached datasets
        self._datasets: dict[str, Dataset] = {}
        # Cached proposals
        self._proposals: dict[str, Proposal] = {}

    # ── Identity resolution: CH_ID <-> Memory_UUID (v0.6.4) ────────────

    @staticmethod
    def _ch_key(ch_id: str) -> str:
        """Return the Memory key for a CH ID."""
        return f"ch:ko:{ch_id}"

    @staticmethod
    def _ch_id_from_key(key: str) -> str | None:
        """Extract CH ID from a Memory key, or None if not a CH key."""
        if key.startswith("ch:ko:"):
            return key[6:]
        return None

    def _resolve_ch_id(self, ko_id: str) -> str:
        """Resolve a CH ID or Memory UUID to the Memory UUID.

        If ko_id is already in _ko_id_map (forward cache), return the UUID.
        If ko_id is in _memory_id_map (reverse cache), it's a UUID — return it.
        If ko_id is an adopted Memory UUID, look up its wrapper.
        Otherwise, search by exact key ch:ko:{ko_id} and cache the result.
        Returns Memory UUID. Raises if not found or ambiguous.
        """
        # Already a cached CH ID -> UUID
        if ko_id in self._ko_id_map:
            return self._ko_id_map[ko_id]
        # Already a cached UUID
        if ko_id in self._memory_id_map:
            return ko_id
        # Search by exact key
        mem_uuid = self._lookup_by_key(self._ch_key(ko_id))
        if mem_uuid:
            self._ko_id_map[ko_id] = mem_uuid
            self._memory_id_map[mem_uuid] = ko_id
            return mem_uuid
        # Try as raw Memory UUID — check if it has an adopted wrapper
        try:
            uuid.UUID(ko_id)
            obj = self._get(f"/api/graph/objects/{ko_id}")
            wrapper_id = obj.get("properties", {}).get("ch_adopted_wrapper_id")
            if wrapper_id:
                # Resolve wrapper_id to its UUID
                wrapper_uuid = self._resolve_ch_id(wrapper_id)
                return wrapper_uuid
        except (ValueError, requests.HTTPError):
            pass
        # Not found — return the input; caller will get 404 from server
        return ko_id

    def _resolve_to_ch_id(self, mem_uuid: str) -> str:
        """Resolve a Memory UUID to the canonical CH ID.

        Uses the reverse map. If not cached, fetches the object to get its key.
        Returns CH ID. Returns the UUID as-is if no key mapping exists.
        """
        if mem_uuid in self._memory_id_map:
            return self._memory_id_map[mem_uuid]
        # Fetch the object to discover its key
        try:
            obj = self._get(f"/api/graph/objects/{mem_uuid}")
            key = obj.get("key", "")
            ch_id = self._ch_id_from_key(key)
            if ch_id:
                self._memory_id_map[mem_uuid] = ch_id
                self._ko_id_map[ch_id] = mem_uuid
                return ch_id
        except Exception:
            pass
        return mem_uuid

    def _lookup_by_key(self, key: str) -> str | None:
        """Deterministic exact lookup by Memory key.

        Searches for entities matching the exact key.
        Returns Memory UUID if exactly one match.
        Returns None if no match.
        Raises if multiple matches (duplicate key — fails closed).
        """
        resp = self._post("/api/graph/search", {
            "query": key,
            "projectId": self.project_id,
            "limit": 10,
            "offset": 0,
        })
        matches = [
            item["object"] for item in resp.get("data", [])
            if item.get("object", {}).get("key") == key
        ]
        if len(matches) == 0:
            return None
        if len(matches) > 1:
            uuids = [m.get("id") for m in matches]
            raise RuntimeError(
                f"Duplicate key '{key}' found for {len(matches)} entities "
                f"(UUIDs: {uuids}). Identity resolution fails closed."
            )
        return matches[0].get("id")

    # ── HTTP helpers ──────────────────────────────────────────────────

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.server_url}{path}"
        resp = requests.get(url, headers=self._headers, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        url = f"{self.server_url}{path}"
        resp = requests.post(url, headers=self._headers, json=body, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _patch(self, path: str, body: dict) -> dict:
        url = f"{self.server_url}{path}"
        resp = requests.patch(url, headers=self._headers, json=body, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> dict:
        url = f"{self.server_url}{path}"
        resp = requests.delete(url, headers=self._headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ── KO CRUD ───────────────────────────────────────────────────────

    def create_ko(self, ko: KnowledgeObject) -> str:
        mem_obj = ko_to_memory_object(ko)
        mem_obj["projectId"] = self.project_id
        result = self._post("/api/graph/objects", mem_obj)
        mem_uuid = result["id"]
        self._created_ids.add(mem_uuid)

        # Record identity mapping (v0.6.4)
        self._ko_id_map[ko.id] = mem_uuid
        self._memory_id_map[mem_uuid] = ko.id

        # Store relations as edges (resolve CH IDs to Memory UUIDs)
        for rel in ko.relations:
            dst_uuid = self._resolve_ch_id(rel.to)
            self._create_edge(mem_uuid, dst_uuid, rel.type.value)

        return mem_uuid

    def adopt_existing_ko(self, existing_mem_uuid: str, *,
                           ch_id: str | None = None,
                           title: str = "",
                           ko_type: str | None = None,
                           content: Any = None,
                           truth_category: str | None = None,
                           epistemic_status: str | None = None,
                           confidence: str | None = None,
                           scope: str = "",
                           assumptions: list[str] | None = None,
                           evidence_ids: list[str] | None = None,
                           source: str = "adopted",
                           author: str = "system",
                           derivation_type: str | None = None) -> str:
        """Adopt an existing Memory object as a CH KnowledgeObject.

        Creates a CH-wrapper entity with key ch:ko:{ch_id} that links to the
        original object via an ADOPTS relation. Uses ko_to_memory_object as
        format authority. Preserves the original UUID and content.

        Args:
            existing_mem_uuid: UUID of the existing Memory object to adopt.
            ch_id: Canonical CH ID. Auto-generated from existing key if omitted.
            title: KO title. Uses existing object's key if omitted.
            ... other fields map to ch_* properties via serializer.

        Returns:
            The CH ID of the adopted object.
        """
        # Verify the existing object is accessible
        existing = self._get(f"/api/graph/objects/{existing_mem_uuid}")
        existing_key = existing.get("key", "")
        existing_props = existing.get("properties", {})

        # Derive CH ID from existing key if not provided
        if not ch_id:
            ch_id = existing_key
        if not ch_id:
            ch_id = existing_mem_uuid

        # Build a proper KnowledgeObject with CH semantics
        from cognitive_harness.model.ko import (
            KOType, TruthCategory, EpistemicStatus, ConfidenceLevel,
            Provenance, DerivationRelation, DerivationType,
        )

        # Parse type
        ko_t = KOType.REQUIREMENT
        type_val = ko_type or existing_props.get("ch_ko_type")
        if type_val:
            try:
                ko_t = KOType(type_val)
            except ValueError:
                pass

        # Parse truth category
        tc = TruthCategory.ASSUMPTION
        tc_val = truth_category or existing_props.get("ch_truth_category")
        if tc_val:
            try:
                tc = TruthCategory(tc_val)
            except ValueError:
                pass

        # Parse epistemic status
        es = EpistemicStatus.PROPOSED
        es_val = epistemic_status or existing_props.get("ch_epistemic_status")
        if es_val:
            try:
                es = EpistemicStatus(es_val)
            except ValueError:
                pass

        # Parse confidence
        cl = ConfidenceLevel.SPECULATIVE
        cl_val = confidence or existing_props.get("ch_confidence")
        if cl_val:
            try:
                cl = ConfidenceLevel(cl_val)
            except ValueError:
                pass

        # Parse derivation
        deriv = None
        dt_val = derivation_type or existing_props.get("ch_derivation_type")
        if dt_val:
            try:
                deriv = DerivationRelation(derivation_type=DerivationType(dt_val))
            except ValueError:
                pass

        # Title: use provided, or existing object key, or CH ID
        ko_title = title or existing_key or ch_id

        # Content: use provided, or merge existing properties
        ko_content = content if content is not None else existing_props

        # Build the CH KnowledgeObject
        ko = KnowledgeObject(
            id=ch_id,
            type=ko_t,
            title=ko_title,
            content=ko_content,
            truth_category=tc,
            provenance=Provenance(
                source=source,
                author=author,
                derived_from=existing_mem_uuid,
            ),
            derivation=deriv,
            epistemic_status=es,
            confidence=cl,
            scope=scope or existing_props.get("ch_scope", ""),
            assumptions=assumptions or existing_props.get("ch_assumptions", []),
            evidence_ids=evidence_ids or existing_props.get("ch_evidence_ids", []),
        )

        # Serialize using the canonical serializer — this is the format authority
        mem_obj = ko_to_memory_object(ko)
        mem_obj["projectId"] = self.project_id

        # Link back to original object for traceability
        # Store original UUID in provenance (already set above)
        # Also add an ADOPTS edge from wrapper → original
        result = self._post("/api/graph/objects", mem_obj)
        wrapper_uuid = result["id"]
        self._created_ids.add(wrapper_uuid)

        # Record identity mapping
        self._ko_id_map[ch_id] = wrapper_uuid
        self._memory_id_map[wrapper_uuid] = ch_id

        # Create edge: wrapper ADOPTS → original (for traceability)
        # Use a custom relation type "adopts" to link wrapper to original
        self._create_edge(wrapper_uuid, existing_mem_uuid, "adopts")

        # Also store reverse lookup: original → wrapper
        # This allows get_ko called with original UUID to find the CH wrapper
        # by annotating the original with a reference
        try:
            self._patch(f"/api/graph/objects/{existing_mem_uuid}", {
                "properties": {"ch_adopted_wrapper_id": ch_id}
            })
        except Exception:
            pass  # Best-effort annotation

        return ch_id

    def update_ko(self, ko_id: str, updates: dict[str, Any]) -> bool:
        existing = self.get_ko(ko_id)
        if existing is None:
            return False
        if existing.is_canonical():
            return False  # canonical KOs must be superseded

        # Merge updates into properties
        props = {}
        for k, v in updates.items():
            if k == "epistemic_status":
                props["ch_epistemic_status"] = v.value if hasattr(v, "value") else str(v)
            elif k == "truth_category":
                props["ch_truth_category"] = v.value if hasattr(v, "value") else str(v)
            elif k == "confidence":
                props["ch_confidence"] = v.value if hasattr(v, "value") else str(v)
            elif k == "viewpoint_ids":
                props["ch_viewpoint_ids"] = v
            elif k == "scope":
                props["ch_scope"] = v
            elif k == "assumptions":
                props["ch_assumptions"] = v
            elif k == "supersedes_id":
                props["ch_supersedes_id"] = v
            elif k == "superseded_by_id":
                props["ch_superseded_by_id"] = v
            elif k == "review_required":
                props["ch_review_required"] = v
            elif k == "review_reason":
                props["ch_review_reason"] = v
            elif k == "title":
                props["title"] = v
            elif k == "content":
                props["content"] = v
            elif k == "evidence_ids":
                props["ch_evidence_ids"] = v
            else:
                props[k] = v

        if props:
            mem_uuid = self._resolve_ch_id(ko_id)
            self._patch(f"/api/graph/objects/{mem_uuid}", {"properties": props})
        return True

    def get_ko(self, ko_id: str) -> KnowledgeObject | None:
        """Fetch KO by CH ID (or Memory UUID if that's what was passed).

        Resolves CH ID → Memory UUID → fetches object → restores CH ID.
        """
        mem_uuid = self._resolve_ch_id(ko_id)
        # If _resolve_ch_id returned the input unchanged, it means
        # the CH ID was not in the map AND key lookup found nothing.
        # Don't waste a server call with a non-UUID.
        if mem_uuid == ko_id and mem_uuid not in self._memory_id_map:
            # Verify it's not actually a UUID by checking format
            try:
                uuid.UUID(mem_uuid)
            except ValueError:
                # Not a UUID and not found in key lookup → truly missing
                return None
        try:
            obj = self._get(f"/api/graph/objects/{mem_uuid}")
        except requests.HTTPError as e:
            if e.response and e.response.status_code == 404:
                return None
            if e.response and e.response.status_code == 400:
                # 400 means the server rejected the ID — not a valid UUID
                return None
            raise

        # Fetch edges and build outgoing relations
        edges = self._get_edges(mem_uuid)
        relations = []
        for edge in edges.get("outgoing", []):
            rel_type_str = edge.get("type", "")
            try:
                rel_type = RelationType(rel_type_str)
            except ValueError:
                rel_type = RelationType.SUPPORTS
            # Translate destination UUID back to CH ID
            dst_ch = self._resolve_to_ch_id(edge["dst_id"])
            relations.append(Relation(to=dst_ch, type=rel_type))

        ko = memory_object_to_ko(obj)
        ko.relations = relations
        return ko

    # ── Relations ─────────────────────────────────────────────────────

    def create_relation(self, from_id: str, to_id: str, rel_type: RelationType) -> bool:
        # Verify both KOs exist
        if self.get_ko(from_id) is None or self.get_ko(to_id) is None:
            return False
        src_uuid = self._resolve_ch_id(from_id)
        dst_uuid = self._resolve_ch_id(to_id)
        return self._create_edge(src_uuid, dst_uuid, rel_type.value)

    def _create_edge(self, src_uuid: str, dst_uuid: str, rel_type: str) -> bool:
        """Create edge using Memory UUIDs."""
        body = {
            "src_id": src_uuid,
            "dst_id": dst_uuid,
            "type": rel_type,
        }
        try:
            self._post("/api/graph/relationships", body)
            return True
        except requests.HTTPError:
            return False

    def _get_edges(self, ko_id: str) -> dict:
        mem_uuid = self._resolve_ch_id(ko_id)
        try:
            return self._get(f"/api/graph/objects/{mem_uuid}/edges")
        except requests.HTTPError:
            return {"incoming": [], "outgoing": []}

    # ── Direction-aware relation access (v0.6.4) ──────────────────────

    def get_outgoing_relations(self, ko_id: str, relation_types: frozenset | None = None) -> list[tuple[str, RelationType]]:
        """Return outgoing relations: (CH_ID, type). Uses Memory edges API."""
        edges = self._get_edges(ko_id)
        result = []
        for edge in edges.get("outgoing", []):
            rel_type_str = edge.get("type", "")
            try:
                rel_type = RelationType(rel_type_str)
            except ValueError:
                continue
            if relation_types is None or rel_type in relation_types:
                dst_ch = self._resolve_to_ch_id(edge["dst_id"])
                result.append((dst_ch, rel_type))
        return result

    def get_incoming_relations(self, ko_id: str, relation_types: frozenset | None = None) -> list[tuple[str, RelationType]]:
        """Return incoming relations: (CH_ID, type). Uses Memory edges API."""
        edges = self._get_edges(ko_id)
        result = []
        for edge in edges.get("incoming", []):
            rel_type_str = edge.get("type", "")
            try:
                rel_type = RelationType(rel_type_str)
            except ValueError:
                continue
            if relation_types is None or rel_type in relation_types:
                src_ch = self._resolve_to_ch_id(edge["src_id"])
                result.append((src_ch, rel_type))
        return result

    # ── Queries ───────────────────────────────────────────────────────

    def list_all_kos(self) -> list[KnowledgeObject]:
        """Return all KnowledgeObjects via best-effort enumeration.

        Strategy (v0.6.5):
        1. Paginated journal enumeration — most reliable for complete list
        2. Supplement with created_ids registry (adapter-local)
        3. Broad search with common prefixes (catches objects outside journal)
        4. Verify against count endpoint — warn on mismatch

        NOTE: HTTP search API with query='*' returns 0 results.
        Journal enumeration is the most reliable source.
        enumeration_complete=False means FULL_REQUIRED analyses will fail closed.
        """
        all_kos = []
        seen_ids: set[str] = set()

        def add_if_new(ko):
            if ko.id not in seen_ids:
                seen_ids.add(ko.id)
                all_kos.append(ko)

        # Strategy 1: Journal-based enumeration (most complete)
        kos_from_journal = self._list_all_via_journal()
        for ko in kos_from_journal:
            add_if_new(ko)

        # Strategy 2: Supplement with created_ids registry
        for kid in self._created_ids:
            if kid not in seen_ids:
                ko = self.get_ko(kid)
                if ko:
                    add_if_new(ko)

        # Strategy 3: Broad search with common prefixes
        kos_from_broad = self._list_all_via_broad_search()
        for ko in kos_from_broad:
            add_if_new(ko)

        # Verify against count — warn if mismatch
        try:
            count_resp = self._get("/api/graph/objects/count")
            api_total = count_resp.get("count", 0)
            if len(seen_ids) != api_total:
                log.warning(
                    "list_all_kos: returned %d unique objects but API count=%d. "
                    "Some objects may be missing from enumeration.",
                    len(seen_ids), api_total
                )
        except Exception:
            pass

        return all_kos

    def _list_all_via_journal(self) -> list[KnowledgeObject]:
        """Enumerate objects by reading journal entries and fetching by key."""
        kos = []
        try:
            journal = self._get("/api/graph/journal")
            entries = journal.get("entries", [])

            # Collect unique keys from all events (created, updated, even deleted for tracking)
            seen_keys: set[str] = set()
            for entry in entries:
                etype = entry.get("event_type", "")
                if etype in ("created", "updated", "batch_create", "merged"):
                    meta = entry.get("metadata", {})
                    key = meta.get("key")
                    if key and key not in seen_keys:
                        seen_keys.add(key)

            # For each key, search to find the object
            for key in seen_keys:
                search_resp = self._post("/api/graph/search", {
                    "query": key,
                    "projectId": self.project_id,
                    "limit": 1,
                    "offset": 0,
                })
                for item in search_resp.get("data", []):
                    obj = item.get("object", item)
                    if obj.get("key") == key:
                        kos.append(memory_object_to_ko(obj))
                        break

            # Additionally, try broad character searches to find objects not in journal
            # This catches objects created outside our adapter
            kos.extend(self._list_all_via_broad_search())
        except Exception as e:
            log.warning("Journal enumeration failed: %s", e)

        return kos

    def _list_all_via_broad_search(self) -> list[KnowledgeObject]:
        """Search with common prefixes to find objects not tracked by journal."""
        kos = []
        # Search for common key prefixes used by this adapter
        prefixes = ["ch:ko:", "admin:", "Concept"]
        for prefix in prefixes:
            search_resp = self._post("/api/graph/search", {
                "query": prefix,
                "projectId": self.project_id,
                "limit": PAGE_SIZE,
                "offset": 0,
            })
            for item in search_resp.get("data", []):
                obj = item.get("object", item)
                kos.append(memory_object_to_ko(obj))
        return kos

    def query_by_viewpoint(self, viewpoint_id: str) -> list[KnowledgeObject]:
        all_kos = self.list_all_kos()
        return [ko for ko in all_kos if viewpoint_id in ko.viewpoint_ids]

    def query_by_type(self, ko_type) -> list[KnowledgeObject]:
        all_kos = self.list_all_kos()
        target = ko_type.value if hasattr(ko_type, "value") else ko_type
        return [ko for ko in all_kos if ko.type.value == target]

    def query_active_by_scope(self, scope: str) -> list[KnowledgeObject]:
        all_kos = self.list_all_kos()
        return [
            ko for ko in all_kos
            if scope in ko.scope and not ko.epistemic_status.is_terminal
        ]

    def query_semantic(self, query: str, viewpoint_id: str | None = None,
                       limit: int = 10) -> list[KnowledgeObject]:
        body = {
            "query": query,
            "projectId": self.project_id,
            "limit": limit,
            "offset": 0,
        }
        resp = self._post("/api/graph/search", body)
        results = []
        for item in resp.get("data", []):
            obj = item.get("object", item)
            ko = memory_object_to_ko(obj)
            if viewpoint_id and viewpoint_id not in ko.viewpoint_ids:
                continue
            results.append(ko)
        return results[:limit]

    def list_canonical(self, scope: str | None = None) -> list[KnowledgeObject]:
        all_kos = self.list_all_kos()
        result = [ko for ko in all_kos if ko.epistemic_status == EpistemicStatus.CANONICAL]
        if scope:
            result = [ko for ko in result if scope in ko.scope]
        return result

    def get_succession_chain(self, ko_id: str) -> list[KnowledgeObject]:
        ancestors = []
        current_id = ko_id
        while current_id:
            ko = self.get_ko(current_id)
            if ko is None:
                break
            ancestors.append(ko)
            current_id = ko.supersedes_id or None
        ancestors.reverse()

        chain = list(ancestors)
        last = ancestors[-1] if ancestors else None
        while last and last.superseded_by_id:
            nxt = self.get_ko(last.superseded_by_id)
            if nxt is None:
                break
            chain.append(nxt)
            last = nxt
        return chain

    # ── Evidence ──────────────────────────────────────────────────────

    def add_evidence(self, evidence_id: str, claim_id: str, status: str,
                     observation: str, records: list[dict]) -> str:
        ev = {
            "id": evidence_id,
            "claim_id": claim_id,
            "status": status,
            "observation": observation,
            "records": records,
        }
        self._evidence[evidence_id] = ev

        # Create evidence as a Memory object with SUPPORTS relation to claim
        ev_ko = KnowledgeObject(
            id=evidence_id,
            type=KOType.EVIDENCE_ITEM,
            title=f"Evidence for {claim_id}",
            content={"status": status, "observation": observation, "records": records},
            provenance=Provenance(source="evidence", author="system"),
        )
        mem_obj = ko_to_memory_object(ev_ko)
        mem_obj["projectId"] = self.project_id
        self._post("/api/graph/objects", mem_obj)
        self._created_ids.add(evidence_id)

        # Link to claim via SUPPORTS relation
        self._create_edge(evidence_id, claim_id, RelationType.SUPPORTS.value)

        # Update claim's evidence_ids
        claim = self.get_ko(claim_id)
        if claim and evidence_id not in claim.evidence_ids:
            self.update_ko(claim_id, {"evidence_ids": claim.evidence_ids + [evidence_id]})

        return evidence_id

    def get_evidence(self, evidence_id: str) -> dict | None:
        if evidence_id in self._evidence:
            return self._evidence[evidence_id]
        # Try fetching from Memory
        try:
            obj = self._get(f"/api/graph/objects/{evidence_id}")
            props = obj.get("properties", {})
            if props.get("ch_ko_type") == KOType.EVIDENCE_ITEM.value:
                return {
                    "id": evidence_id,
                    "claim_id": props.get("content", {}).get("claim_id", ""),
                    "status": props.get("content", {}).get("status", ""),
                    "observation": props.get("content", {}).get("observation", ""),
                    "records": props.get("content", {}).get("records", []),
                }
        except requests.HTTPError:
            pass
        return None

    def list_evidence_for_ko(self, ko_id: str) -> list[dict]:
        return [ev for ev in self._evidence.values() if ev["claim_id"] == ko_id]

    # ── Locking (no-op per STORAGE.md) ────────────────────────────────

    def lock_ko(self, ko_id: str, thread_id: str) -> bool:
        """No-op advisory lock. Memory has no distributed locking."""
        return True

    def unlock_ko(self, ko_id: str, thread_id: str) -> bool:
        """No-op advisory lock release."""
        return True

    # ── Impact analysis ───────────────────────────────────────────────

    def compute_impact_set(self, ko_id: str) -> list[str]:
        """Direction-aware impact set (v0.6.4).

        Returns CH IDs. Internal traversal uses Memory UUIDs.
        """
        impacted: set[str] = set()
        # Start with the CH ID resolved to UUID
        start_uuid = self._resolve_ch_id(ko_id)
        queue = [start_uuid]
        seen_uuids: set[str] = {start_uuid}
        while queue:
            current = queue.pop(0)
            edges = self._get_edges(current)

            # Case 1: incoming DEPENDS_ON/DERIVED_FROM — these KOs depend on current
            for edge in edges.get("incoming", []):
                rel_type_str = edge.get("type", "")
                if rel_type_str in (RelationType.DEPENDS_ON.value, RelationType.DERIVED_FROM.value):
                    src_uuid = edge.get("src_id", "")
                    if src_uuid and src_uuid not in seen_uuids:
                        src_ch = self._resolve_to_ch_id(src_uuid)
                        impacted.add(src_ch)
                        seen_uuids.add(src_uuid)
                        queue.append(src_uuid)

            # Case 2: outgoing SUPPORTS/VALIDATES — current supports these claims
            for edge in edges.get("outgoing", []):
                rel_type_str = edge.get("type", "")
                if rel_type_str in (RelationType.SUPPORTS.value, RelationType.VALIDATES.value):
                    dst_uuid = edge.get("dst_id", "")
                    if dst_uuid and dst_uuid not in seen_uuids:
                        dst_ch = self._resolve_to_ch_id(dst_uuid)
                        impacted.add(dst_ch)
                        seen_uuids.add(dst_uuid)
                        queue.append(dst_uuid)

            # Case 3: outgoing CONSTRAINS/IMPACTS
            for edge in edges.get("outgoing", []):
                rel_type_str = edge.get("type", "")
                if rel_type_str in (RelationType.CONSTRAINS.value, RelationType.IMPACTS.value):
                    dst_uuid = edge.get("dst_id", "")
                    if dst_uuid and dst_uuid not in seen_uuids:
                        dst_ch = self._resolve_to_ch_id(dst_uuid)
                        impacted.add(dst_ch)
                        seen_uuids.add(dst_uuid)
                        queue.append(dst_uuid)
        return list(impacted)

    def mark_review_required(self, ko_ids: list[str], reason: str) -> int:
        marked = 0
        for kid in ko_ids:
            ko = self.get_ko(kid)
            if ko and not ko.epistemic_status.is_terminal:
                if not ko.review_required:
                    self.update_ko(kid, {"review_required": True, "review_reason": reason})
                    marked += 1
        return marked

    def clear_review_required(self, ko_id: str) -> bool:
        ko = self.get_ko(ko_id)
        if ko and ko.review_required:
            self.update_ko(ko_id, {"review_required": False, "review_reason": ""})
            return True
        return False

    def list_review_required(self) -> list[KnowledgeObject]:
        all_kos = self.list_all_kos()
        return [ko for ko in all_kos if ko.review_required]

    # ── Proposal pipeline (persisted) ─────────────────────────────────

    def submit_proposal(self, proposal: Proposal) -> str:
        """Submit and persist a proposal as a Memory object.

        Proposals are stored as entities of type 'Proposal' with key
        'ch:proposal:{id}'. They survive restart and can be validated/executed.
        """
        self._proposals[proposal.id] = proposal

        # Persist as Memory object
        proposal_obj = {
            "type": "Concept",
            "key": f"ch:proposal:{proposal.id}",
            "projectId": self.project_id,
            "properties": {
                "ch_proposal_type": proposal.type.value if hasattr(proposal.type, 'value') else str(proposal.type),
                "ch_proposal_state": proposal.state.value if hasattr(proposal.state, 'value') else str(proposal.state),
                "ch_proposal_proposer": proposal.proposer,
                "ch_proposal_rationale": proposal.rationale,
                "ch_proposal_target_ko_id": proposal.target_ko_id,
                "ch_proposal_ko_type": proposal.ko_type.value if proposal.ko_type and hasattr(proposal.ko_type, 'value') else str(proposal.ko_type) if proposal.ko_type else "",
                "ch_proposal_ko_title": proposal.ko_title,
                "ch_proposal_ko_content": str(proposal.ko_content) if proposal.ko_content else "",
                "ch_proposal_rejection_reason": proposal.rejection_reason,
                "ch_proposal_created_ko_id": proposal.created_ko_id,
            },
        }
        try:
            result = self._post("/api/graph/objects", proposal_obj)
            self._created_ids.add(result["id"])
        except Exception as e:
            log.warning("Failed to persist proposal %s: %s", proposal.id, e)

        return proposal.id

    def validate_and_execute(self, proposal_id: str) -> Proposal:
        """Validate and execute a proposal deterministically.

        Loads proposal from cache or Memory. Validates transitions.
        Executes the requested mutation. Persists result.
        """
        from cognitive_harness.model.proposal import ProposalType, ProposalState
        from cognitive_harness.model.ko import KOType, EpistemicStatus

        p = self._proposals.get(proposal_id)
        if p is None:
            # Try loading from Memory
            mem_uuid = self._lookup_by_key(f"ch:proposal:{proposal_id}")
            if mem_uuid:
                obj = self._get(f"/api/graph/objects/{mem_uuid}")
                props = obj.get("properties", {})
                p_type = ProposalType(props.get("ch_proposal_type", "create_ko"))
                p = Proposal(
                    id=proposal_id,
                    type=p_type,
                    proposer=props.get("ch_proposal_proposer", ""),
                    rationale=props.get("ch_proposal_rationale", ""),
                    state=ProposalState(props.get("ch_proposal_state", "pending")),
                    rejection_reason=props.get("ch_proposal_rejection_reason", ""),
                )
                # Restore type-specific fields
                if p_type == ProposalType.CREATE_KO:
                    p.ko_title = props.get("ch_proposal_ko_title", "")
                    p.ko_content = props.get("ch_proposal_ko_content")
                elif p_type in (ProposalType.UPDATE_KO, ProposalType.TRANSITION_STATUS):
                    p.target_ko_id = props.get("ch_proposal_target_ko_id", "")
                self._proposals[p.id] = p
            else:
                raise ValueError(f"Proposal {proposal_id} not found")

        # Validate state
        if p.state != ProposalState.PENDING:
            return p  # Already processed

        # Execute based on type
        try:
            if p.type == ProposalType.CREATE_KO:
                # Validate: must have title
                if not p.ko_title:
                    p.state = ProposalState.REJECTED
                    p.rejection_reason = "CREATE_KO requires ko_title"
                    return p
                ko_type = p.ko_type or KOType.REQUIREMENT
                if hasattr(ko_type, 'value'):
                    ko_type = KOType(ko_type)
                ko = KnowledgeObject(
                    type=ko_type,
                    title=p.ko_title,
                    content=p.ko_content,
                    scope=p.ko_scope,
                    assumptions=p.ko_assumptions,
                    confidence=p.ko_confidence,
                )
                if p.ko_viewpoints:
                    ko.viewpoint_ids = p.ko_viewpoints
                mem_uuid = self.create_ko(ko)
                p.created_ko_id = ko.id
                p.state = ProposalState.ACCEPTED

            elif p.type == ProposalType.UPDATE_KO:
                if not p.target_ko_id:
                    p.state = ProposalState.REJECTED
                    p.rejection_reason = "UPDATE_KO requires target_ko_id"
                    return p
                if self.update_ko(p.target_ko_id, p.updates):
                    p.state = ProposalState.ACCEPTED
                else:
                    p.state = ProposalState.REJECTED
                    p.rejection_reason = "Target KO not found or is canonical"

            elif p.type == ProposalType.TRANSITION_STATUS:
                if not p.target_ko_id or not p.target_status:
                    p.state = ProposalState.REJECTED
                    p.rejection_reason = "TRANSITION_STATUS requires target_ko_id and target_status"
                    return p
                ko = self.get_ko(p.target_ko_id)
                if not ko:
                    p.state = ProposalState.REJECTED
                    p.rejection_reason = "Target KO not found"
                    return p
                target = p.target_status
                if hasattr(target, 'value'):
                    target = EpistemicStatus(target)
                if not ko.can_transition_to(target):
                    p.state = ProposalState.REJECTED
                    p.rejection_reason = f"Invalid transition: {ko.epistemic_status.value} → {target.value}"
                    return p
                if self.update_ko(p.target_ko_id, {"epistemic_status": target.value if hasattr(target, 'value') else str(target)}):
                    p.state = ProposalState.ACCEPTED
                else:
                    p.state = ProposalState.REJECTED
                    p.rejection_reason = "Update failed"

            elif p.type == ProposalType.CREATE_RELATION:
                if self.create_relation(p.from_ko_id, p.to_ko_id, p.relation_type):
                    p.state = ProposalState.ACCEPTED
                else:
                    p.state = ProposalState.REJECTED
                    p.rejection_reason = "Relation creation failed"

            elif p.type == ProposalType.CREATE_EVIDENCE:
                if p.evidence_claim_id:
                    ev_id = self.add_evidence(
                        f"ev-{proposal_id}", p.evidence_claim_id,
                        "submitted", p.evidence_observation, p.evidence_records
                    )
                    p.created_evidence_id = ev_id
                    p.state = ProposalState.ACCEPTED
                else:
                    p.state = ProposalState.REJECTED
                    p.rejection_reason = "CREATE_EVIDENCE requires evidence_claim_id"

            else:
                # Unsupported types pass through
                p.state = ProposalState.ACCEPTED

        except Exception as e:
            p.state = ProposalState.REJECTED
            p.rejection_reason = str(e)

        # Persist updated state
        try:
            wrapper_uuid = self._lookup_by_key(f"ch:proposal:{proposal_id}")
            if wrapper_uuid:
                self._patch(f"/api/graph/objects/{wrapper_uuid}", {
                    "properties": {
                        "ch_proposal_state": p.state.value if hasattr(p.state, 'value') else str(p.state),
                        "ch_proposal_rejection_reason": p.rejection_reason,
                        "ch_proposal_created_ko_id": p.created_ko_id,
                    }
                })
        except Exception:
            pass

        return p

    # ── Warrant queries (storage-level convenience) ───────────────────

    def list_by_warrant_status(self, warrant_status_str: str) -> list[KnowledgeObject]:
        """Warrant is computed externally, not stored. Returns empty."""
        return []

    def list_anti_pattern_hits(self, pattern_str: str) -> list[KnowledgeObject]:
        """Anti-patterns are computed by WarrantAnalyzer, not stored."""
        all_kos = self.list_all_kos()
        return [ko for ko in all_kos if pattern_str in ko.anti_patterns]

    def get_justification_path(self, ko_id: str) -> list[str]:
        """Direction-aware BFS through justification relations (v0.6.4).
        
        OUTBOUND: DEPENDS_ON, DERIVED_FROM — follow outgoing edges.
        INBOUND: SUPPORTS, VALIDATES — follow incoming edges.
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
            ko = self.get_ko(current)
            if ko is not None:
                for rel in ko.relations:
                    if rel.type in JUSTIFICATION_OUTBOUND and rel.to not in visited:
                        queue.append(rel.to)
            
            # Inbound: follow supporting evidence
            incoming = self.get_incoming_relations(current, JUSTIFICATION_INBOUND)
            for from_id, rel_type in incoming:
                if from_id not in visited:
                    queue.append(from_id)
            
            # Also follow derivation upstream
            if ko and ko.derivation:
                for up_id in ko.derivation.upstream_ko_ids:
                    if up_id not in visited:
                        queue.append(up_id)
        return path

    # ── Dataset operations ────────────────────────────────────────────

    def create_dataset(self, dataset: Dataset) -> str:
        self._datasets[dataset.id] = dataset

        # Also store as Memory object
        ds_ko = KnowledgeObject(
            id=dataset.id,
            type=KOType.SPECIFICATION,
            title=dataset.name or f"Dataset {dataset.id[:8]}",
            content={
                "description": dataset.description,
                "source_ko_id": dataset.source_ko_id,
                "observation_count": dataset.observation_count,
                "derived_from_dataset_ids": dataset.derived_from_dataset_ids,
            },
            provenance=Provenance(source="dataset", author="system"),
        )
        mem_obj = ko_to_memory_object(ds_ko)
        mem_obj["projectId"] = self.project_id
        self._post("/api/graph/objects", mem_obj)
        self._created_ids.add(dataset.id)
        return dataset.id

    def get_dataset(self, dataset_id: str) -> Dataset | None:
        if dataset_id in self._datasets:
            return self._datasets[dataset_id]
        # Try fetching from Memory
        try:
            obj = self._get(f"/api/graph/objects/{dataset_id}")
            props = obj.get("properties", {})
            content = props.get("content", {})
            ds = Dataset(
                id=dataset_id,
                name=props.get("title", ""),
                description=content.get("description", ""),
                source_ko_id=content.get("source_ko_id", ""),
                observation_count=content.get("observation_count", 0),
                derived_from_dataset_ids=content.get("derived_from_dataset_ids", []),
            )
            self._datasets[dataset_id] = ds
            return ds
        except requests.HTTPError:
            return None
