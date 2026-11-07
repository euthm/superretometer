# FILE: tests/transport/test_truth_category_integration.py
"""Integration tests requiring live Memory server.

Tests UUID mismatch, edge failure, and proposal persistence via validate_and_execute's
own reload path.  Restart is simulated by creating a fresh adapter whose
_created_ids includes the proposal's Memory UUID (as a session-metadata service
would provide after reconnection).
"""
import os, uuid, pytest

from cognitive_harness.model.ko import KnowledgeObject, KOType, TruthCategory, JUSTIFICATION_INBOUND, CONTRADICTION_INBOUND
from cognitive_harness.model.proposal import Proposal, ProposalType
from memory_adapter import MemoryAdapter
from runtime_server import handle_submit_proposal

# ── Detect live Memory server ──────────────────────────────────────────────

try:
    import requests
    _token = ""
    try:
        with open("/home/egiuth/.memory/config.yaml") as f:
            import yaml
            cfg = yaml.safe_load(f)
            _token = cfg.get("api_key", "")
    except Exception:
        pass
    if not _token:
        _token = os.environ.get("MEMORY_API_KEY", "")

    _server_url = "http://localhost:3002"
    if _token:
        _resp = requests.get(f"{_server_url}/api/graph/objects/count",
                            headers={"Authorization": f"Bearer {_token}"}, timeout=5)
        if _resp.status_code in (200, 401, 403):
            HAS_MEMORY = True
        else:
            HAS_MEMORY = False
    else:
        HAS_MEMORY = False
except Exception:
    HAS_MEMORY = False

_project_id = "229d3378-5eda-42ab-9bfa-133f6360cd34"
_run_suffix = str(uuid.uuid4())[:8]


def find_proposal_mem_uuid(storage, proposal_id):
    """Find a proposal's Memory UUID by scanning created_ids."""
    target_key = f"ch:proposal:{proposal_id}"
    for cid in storage._created_ids:
        try:
            obj = storage._get(f"/api/graph/objects/{cid}")
            if obj.get("key") == target_key:
                return cid
        except Exception:
            continue
    return None


@pytest.mark.live_memory
@pytest.mark.skipif(not HAS_MEMORY, reason="Memory server not available")
class TestEvidenceEdgeUUIDLive:
    """Memory returns UUID != CH-ID; edge must use the Memory UUID."""

    def test_evidence_edge_uses_memory_uuid(self):
        storage = MemoryAdapter(
            server_url=_server_url, api_key=_token, project_id=_project_id,
        )

        claim_id = f"live-claim-uuid-{_run_suffix}"
        storage.create_ko(KnowledgeObject(id=claim_id, type=KOType.HYPOTHESIS,
                                          title="Live UUID test claim"))

        ch_evidence_id = f"live-ev-uuid-{_run_suffix}"
        storage.add_evidence(ch_evidence_id, claim_id, "confirmed",
                             "UUID test", [], relation_type="supports")

        assert ch_evidence_id in storage._ko_id_map
        ev_mem_uuid = storage._ko_id_map[ch_evidence_id]
        assert ev_mem_uuid != ch_evidence_id

        incoming = storage.get_incoming_relations(claim_id, JUSTIFICATION_INBOUND)
        ch_sources = [src for src, rt in incoming]
        assert ch_evidence_id in ch_sources

    def test_failed_edge_raises(self):
        """add_evidence raises RuntimeError when edge creation fails."""
        from unittest.mock import patch

        storage = MemoryAdapter(
            server_url=_server_url, api_key=_token, project_id=_project_id,
        )

        claim_id = f"live-claim-edgefail-{_run_suffix}"
        storage.create_ko(KnowledgeObject(id=claim_id, type=KOType.HYPOTHESIS,
                                          title="Claim for edge failure test"))

        ch_evidence_id = f"live-ev-edgefail-{_run_suffix}"
        with patch.object(storage, '_create_edge', return_value=False):
            with pytest.raises(RuntimeError, match="Failed to create.*edge"):
                storage.add_evidence(ch_evidence_id, claim_id, "confirmed",
                                     "edge failure test", [], relation_type="supports")


@pytest.mark.live_memory
@pytest.mark.skipif(not HAS_MEMORY, reason="Memory server not available")
class TestProposalPersistenceLive:
    """Proposal fields are correctly serialized and persisted to Memory."""

    def test_truth_category_serialized_in_proposal(self):
        """ko_truth_category is persisted in proposal properties."""
        storage = MemoryAdapter(
            server_url=_server_url, api_key=_token, project_id=_project_id,
        )

        result = handle_submit_proposal({"storage": storage}, {
            "proposal_type": "create_ko",
            "proposer": "integration-test",
            "rationale": "Test truth_category serialization",
            "ko_title": f"Serialized TC KO {_run_suffix}",
            "ko_truth_category": "sourced_material_data",
        })
        assert "error" not in result, result
        proposal_id = result["proposal_id"]

        mem_uuid = find_proposal_mem_uuid(storage, proposal_id)
        assert mem_uuid is not None

        obj = storage._get(f"/api/graph/objects/{mem_uuid}")
        props = obj.get("properties", {})
        assert props.get("ch_proposal_ko_truth_category") == "sourced_material_data"

        exec_result = storage.validate_and_execute(proposal_id)
        assert exec_result.state.value == "accepted", exec_result.rejection_reason
        ko = storage.get_ko(exec_result.created_ko_id)
        assert ko.truth_category == TruthCategory.SOURCED_MATERIAL_DATA

    def test_evidence_relation_type_serialized(self):
        """evidence_relation_type is persisted in proposal properties."""
        storage = MemoryAdapter(
            server_url=_server_url, api_key=_token, project_id=_project_id,
        )

        claim_id = f"live-claim-evid-{_run_suffix}"
        storage.create_ko(KnowledgeObject(id=claim_id, type=KOType.HYPOTHESIS,
                                          title="Claim for evidence test"))

        result = handle_submit_proposal({"storage": storage}, {
            "proposal_type": "create_evidence",
            "proposer": "integration-test",
            "rationale": "Test evidence_relation_type serialization",
            "evidence_claim_id": claim_id,
            "evidence_observation": "Test observation",
            "evidence_relation_type": "contradicts",
        })
        assert "error" not in result, result
        proposal_id = result["proposal_id"]

        mem_uuid = find_proposal_mem_uuid(storage, proposal_id)
        assert mem_uuid is not None

        obj = storage._get(f"/api/graph/objects/{mem_uuid}")
        props = obj.get("properties", {})
        assert props.get("ch_proposal_evidence_relation_type") == "contradicts"
        assert props.get("ch_proposal_evidence_claim_id") == claim_id

        exec_result = storage.validate_and_execute(proposal_id)
        assert exec_result.state.value == "accepted", exec_result.rejection_reason
        assert exec_result.created_evidence_id

    def test_restart_restore_create_ko_truth_category(self):
        """submit CREATE_KO → new adapter with empty cache → validate_and_execute
        reloads from Memory (via _lookup_by_key _created_ids fallback) → category preserved."""
        # Adapter 1: submit
        storage1 = MemoryAdapter(
            server_url=_server_url, api_key=_token, project_id=_project_id,
        )

        result = handle_submit_proposal({"storage": storage1}, {
            "proposal_type": "create_ko",
            "proposer": "integration-test",
            "rationale": "Restart restore CREATE_KO",
            "ko_title": f"Restart KO {_run_suffix}",
            "ko_truth_category": "validation_result",
        })
        proposal_id = result["proposal_id"]
        assert "error" not in result, result

        mem_uuid = find_proposal_mem_uuid(storage1, proposal_id)
        assert mem_uuid is not None

        # Adapter 2: fresh, empty cache.
        # Add mem_uuid to _created_ids to simulate session-metadata reconnection
        # (the real session service would supply this list after reconnect).
        storage2 = MemoryAdapter(
            server_url=_server_url, api_key=_token, project_id=_project_id,
        )
        assert proposal_id not in storage2._proposals
        storage2._created_ids.add(mem_uuid)

        # validate_and_execute MUST use its own Memory reload path:
        #   _proposals.get() → None
        #   _lookup_by_key() → scans _created_ids → finds mem_uuid
        #   loads properties, restores ko_truth_category
        #   executes CREATE_KO
        exec_result = storage2.validate_and_execute(proposal_id)

        assert exec_result.state.value == "accepted", exec_result.rejection_reason
        assert exec_result.ko_truth_category == TruthCategory.VALIDATION_RESULT, \
            f"truth_category not restored: {exec_result.ko_truth_category}"

        ko = storage2.get_ko(exec_result.created_ko_id)
        assert ko is not None
        assert ko.truth_category == TruthCategory.VALIDATION_RESULT, \
            f"KO truth_category: {ko.truth_category}"

    def test_restart_restore_evidence_contradicts(self):
        """submit CREATE_EVIDENCE/contradicts → new adapter → validate_and_execute
        restores relation_type and creates CONTRADICTS edge."""
        # Adapter 1: submit
        storage1 = MemoryAdapter(
            server_url=_server_url, api_key=_token, project_id=_project_id,
        )

        claim_id = f"live-claim-restart-ev-{_run_suffix}"
        storage1.create_ko(KnowledgeObject(id=claim_id, type=KOType.HYPOTHESIS,
                                          title="Claim for restart evidence test"))

        result = handle_submit_proposal({"storage": storage1}, {
            "proposal_type": "create_evidence",
            "proposer": "integration-test",
            "rationale": "Restart restore CREATE_EVIDENCE",
            "evidence_claim_id": claim_id,
            "evidence_observation": "Contradicts after restart.",
            "evidence_relation_type": "contradicts",
        })
        proposal_id = result["proposal_id"]
        assert "error" not in result, result

        mem_uuid = find_proposal_mem_uuid(storage1, proposal_id)
        assert mem_uuid is not None

        # Adapter 2: fresh, empty cache, with proposal UUID
        storage2 = MemoryAdapter(
            server_url=_server_url, api_key=_token, project_id=_project_id,
        )
        assert proposal_id not in storage2._proposals
        storage2._created_ids.add(mem_uuid)

        # Also add the claim's UUID so _resolve_ch_id can find it
        claim_mem = storage1._resolve_ch_id(claim_id)
        storage2._ko_id_map[claim_id] = claim_mem
        storage2._memory_id_map[claim_mem] = claim_id

        exec_result = storage2.validate_and_execute(proposal_id)

        assert exec_result.state.value == "accepted", exec_result.rejection_reason
        assert exec_result.evidence_relation_type == "contradicts", \
            f"relation_type not restored: {exec_result.evidence_relation_type}"
        assert exec_result.evidence_claim_id == claim_id
        assert exec_result.evidence_observation == "Contradicts after restart."

        # Verify CONTRADICTS edge was created
        assert exec_result.created_evidence_id
        incoming = storage2.get_incoming_relations(claim_id, CONTRADICTION_INBOUND)
        evidence_ch_ids = [src for src, rt in incoming]
        assert exec_result.created_evidence_id in evidence_ch_ids, \
            f"CONTRADICTS edge not created: incoming={evidence_ch_ids}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
