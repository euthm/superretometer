# FILE: tests/transport/test_truth_category_integration.py
"""Integration tests requiring live Memory server.

Tests the actual UUID mismatch between CH-ID and Memory-returned UUID,
and proposal persistence field serialization.

Run: python -m pytest tests/transport/test_truth_category_integration.py -v
Skip if no Memory server available.
"""
import os, uuid, pytest

from cognitive_harness.model.ko import KnowledgeObject, KOType, TruthCategory, JUSTIFICATION_INBOUND
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

        # Memory should return a UUID different from the CH-ID string
        assert ch_evidence_id in storage._ko_id_map
        ev_mem_uuid = storage._ko_id_map[ch_evidence_id]
        assert ev_mem_uuid != ch_evidence_id

        # Edge resolves back to the CH-ID via _resolve_to_ch_id
        incoming = storage.get_incoming_relations(claim_id, JUSTIFICATION_INBOUND)
        ch_sources = [src for src, rt in incoming]
        assert ch_evidence_id in ch_sources


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

        # Find proposal in Memory
        mem_uuid = find_proposal_mem_uuid(storage, proposal_id)
        assert mem_uuid is not None, "Proposal not in created_ids"

        obj = storage._get(f"/api/graph/objects/{mem_uuid}")
        props = obj.get("properties", {})
        assert props.get("ch_proposal_ko_truth_category") == "sourced_material_data", \
            f"truth_category not serialized: got '{props.get('ch_proposal_ko_truth_category')}'"

        # Execute in same adapter (cache has it)
        exec_result = storage.validate_and_execute(proposal_id)
        assert exec_result.state.value == "accepted", exec_result.rejection_reason
        ko = storage.get_ko(exec_result.created_ko_id)
        assert ko is not None
        assert ko.truth_category == TruthCategory.SOURCED_MATERIAL_DATA, \
            f"Expected sourced_material_data, got {ko.truth_category}"

        # Verify restore path: simulate loading from Memory properties
        # by manually constructing from persisted props
        from cognitive_harness.model.ko import TruthCategory as TC
        tc_restored = TC(props["ch_proposal_ko_truth_category"])
        assert tc_restored == TruthCategory.SOURCED_MATERIAL_DATA

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
        assert props.get("ch_proposal_evidence_relation_type") == "contradicts", \
            f"relation_type not serialized: got '{props.get('ch_proposal_evidence_relation_type')}'"
        assert props.get("ch_proposal_evidence_claim_id") == claim_id
        assert props.get("ch_proposal_evidence_observation") == "Test observation"

        # Execute in same adapter
        exec_result = storage.validate_and_execute(proposal_id)
        assert exec_result.state.value == "accepted", exec_result.rejection_reason
        assert exec_result.created_evidence_id

    def test_cross_adapter_restore_with_direct_fetch(self):
        """New adapter can load and execute a persisted proposal via direct fetch."""
        from cognitive_harness.model.proposal import ProposalState
        # Adapter 1: submit and persist
        storage1 = MemoryAdapter(
            server_url=_server_url, api_key=_token, project_id=_project_id,
        )

        result = handle_submit_proposal({"storage": storage1}, {
            "proposal_type": "create_ko",
            "proposer": "integration-test",
            "rationale": "Cross-adapter test",
            "ko_title": f"Cross-adapter KO {_run_suffix}",
            "ko_truth_category": "validation_result",
        })
        proposal_id = result["proposal_id"]
        mem_uuid = find_proposal_mem_uuid(storage1, proposal_id)
        assert mem_uuid is not None

        # Adapter 2: fresh instance — preload proposal from Memory into cache
        storage2 = MemoryAdapter(
            server_url=_server_url, api_key=_token, project_id=_project_id,
        )
        # Manually reconstruct proposal from persisted Memory properties
        obj = storage2._get(f"/api/graph/objects/{mem_uuid}")
        props = obj.get("properties", {})
        p_type = ProposalType(props["ch_proposal_type"])
        p = Proposal(
            id=proposal_id, type=p_type,
            proposer=props.get("ch_proposal_proposer", ""),
            rationale=props.get("ch_proposal_rationale", ""),
            state=ProposalState(props.get("ch_proposal_state", "pending")),
        )
        if p_type == ProposalType.CREATE_KO:
            p.ko_title = props.get("ch_proposal_ko_title", "")
            tc_raw = props.get("ch_proposal_ko_truth_category", "")
            if tc_raw:
                p.ko_truth_category = TruthCategory(tc_raw)

        storage2._proposals[p.id] = p

        # Execute
        exec_result = storage2.validate_and_execute(proposal_id)
        assert exec_result.state.value == "accepted", exec_result.rejection_reason
        ko = storage2.get_ko(exec_result.created_ko_id)
        assert ko is not None
        assert ko.truth_category == TruthCategory.VALIDATION_RESULT, \
            f"Cross-adapter: expected validation_result, got {ko.truth_category}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
