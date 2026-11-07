# FILE: tests/transport/test_truth_category_integration.py
"""Integration tests requiring live Memory server.

Tests UUID mismatch, edge failure, and proposal persistence across process restart.

Process restart is tested via subprocess: Phase 1 submits proposals, Phase 2
is a fresh Python process that finds and executes them through _lookup_by_key
alone — no _created_ids, _ko_id_map, or _memory_id_map transfer.

If a session-metadata service persists identifiers across restarts, it would
be documented and used here. Currently no such service exists; _lookup_by_key
(search → direct UUID fallback → _created_ids scan) is the sole mechanism.
"""
import json, os, subprocess, sys, time, uuid, pytest

from cognitive_harness.model.ko import KnowledgeObject, KOType, TruthCategory, JUSTIFICATION_INBOUND, CONTRADICTION_INBOUND
from cognitive_harness.model.proposal import Proposal, ProposalType
from transports.memory_adapter import MemoryAdapter
from transports.runtime_server import handle_submit_proposal

# Live writes require explicit opt-in and an explicitly selected project/token.
_token = os.environ.get("MEMORY_API_KEY", "")
_server_url = os.environ.get("MEMORY_SERVER_URL", "http://localhost:3002")
_project_id = os.environ.get("MEMORY_PROJECT_ID", "")
HAS_MEMORY = (os.environ.get("MEMORY_LIVE_TESTS") == "1"
              and bool(_token) and bool(_project_id))
_run_suffix = str(uuid.uuid4())[:8]
_repo_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _subprocess_phase(phase: str, data: dict) -> dict:
    """Run checkout code in a fresh process; secrets never enter script files."""
    env = os.environ.copy()
    env.update(MEMORY_API_KEY=_token, MEMORY_SERVER_URL=_server_url,
               MEMORY_PROJECT_ID=_project_id, PYTHONPATH=_repo_dir)
    result = subprocess.run(
        [sys.executable, "-m", "tests.transport.memory_restart_worker", phase],
        input=json.dumps(data), cwd=_repo_dir, env=env,
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        pytest.fail(f"Subprocess failed: {result.stderr}\n{result.stdout}")
    return json.loads(result.stdout)


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

        mem_uuid = storage._lookup_by_key(f"ch:proposal:{proposal_id}")
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

        mem_uuid = storage._lookup_by_key(f"ch:proposal:{proposal_id}")
        assert mem_uuid is not None
        obj = storage._get(f"/api/graph/objects/{mem_uuid}")
        props = obj.get("properties", {})
        assert props.get("ch_proposal_evidence_relation_type") == "contradicts"
        assert props.get("ch_proposal_evidence_claim_id") == claim_id

        exec_result = storage.validate_and_execute(proposal_id)
        assert exec_result.state.value == "accepted", exec_result.rejection_reason
        assert exec_result.created_evidence_id

    def test_process_restart_create_ko_truth_category(self):
        """Submit and execute in separate processes using checkout modules only."""
        submitted = _subprocess_phase("submit_ko", {})
        restored = _subprocess_phase("execute_ko", submitted)
        assert restored["state"] == "accepted", restored
        assert restored["type"] == "observation"
        assert restored["scope"] == "restart-test-boundary"
        assert restored["truth_category"] == "sourced_material_data"

    def test_process_restart_evidence_contradicts(self):
        """A third process reads the evidence without inheriting either cache."""
        submitted = _subprocess_phase("submit_evidence", {})
        executed = _subprocess_phase("execute_evidence", submitted)
        assert executed["state"] == "accepted", executed
        restored = _subprocess_phase("read_evidence", executed)
        assert restored["claim_id"] == submitted["claim_id"]
        assert restored["relation_type"] == "contradicts"
        assert restored["edge_found"]
        assert restored["listed"]
