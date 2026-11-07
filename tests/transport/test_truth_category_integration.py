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
_repo_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _subprocess_script(script_file: str) -> dict:
    """Run a Python script in a fresh subprocess (no shared state)."""
    result = subprocess.run(
        [sys.executable, script_file],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        pytest.fail(f"Subprocess failed: {result.stderr}\n{result.stdout}")
    out = result.stdout.strip()
    if out:
        return json.loads(out)
    return {}


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
        """CREATE_KO with truth_category survives actual process restart.

        Phase 1 (subprocess): submit pending CREATE_KO proposal, wait for indexing.
        Phase 2 (subprocess): fresh process, empty cache — validate_and_execute
        finds proposal via _lookup_by_key (search), restores truth_category, executes.
        """
        suffix = str(uuid.uuid4())[:8]

        phase1_script = os.path.join(os.path.dirname(__file__),
                                     "_restart_phase1_ko.py")
        tmp_file = f"/tmp/sr_restart_ko_{suffix}.json"
        with open(phase1_script, "w") as f:
            f.write(f'''
import sys, uuid, json, time
sys.path.insert(0, {repr(_repo_dir)})
sys.path.insert(0, "/home/egiuth/.local/share/superretometer-runtime")
from memory_adapter import MemoryAdapter
from runtime_server import handle_submit_proposal
storage = MemoryAdapter(
    server_url="{_server_url}", api_key="{_token}",
    project_id="{_project_id}",
)
result = handle_submit_proposal({{"storage": storage}}, {{
    "proposal_type": "create_ko",
    "proposer": "restart-test",
    "rationale": f"Process restart KO test {{'{suffix}'}}",
    "ko_title": f"Restart-KO-{suffix}",
    "ko_truth_category": "sourced_material_data",
}})
proposal_id = result["proposal_id"]
# Wait for search indexing with retries
for attempt in range(10):
    mem_uuid = storage._lookup_by_key(f"ch:proposal:{{proposal_id}}")
    if mem_uuid:
        break
    time.sleep(1)
else:
    raise RuntimeError("Proposal not indexable after 10s")
with open({repr(tmp_file)}, "w") as out:
    json.dump({{"proposal_id": proposal_id}}, out)
print(json.dumps({{"proposal_id": proposal_id}}))
''')
        try:
            data1 = _subprocess_script(phase1_script)

            phase2_script = os.path.join(os.path.dirname(__file__),
                                         "_restart_phase2_ko.py")
            with open(phase2_script, "w") as f:
                f.write(f'''
import sys, json
sys.path.insert(0, {repr(_repo_dir)})
sys.path.insert(0, "/home/egiuth/.local/share/superretometer-runtime")
from memory_adapter import MemoryAdapter
from cognitive_harness.model.ko import TruthCategory
with open({repr(tmp_file)}) as f:
    data = json.load(f)
storage = MemoryAdapter(
    server_url="{_server_url}", api_key="{_token}",
    project_id="{_project_id}",
)
assert len(storage._proposals) == 0
assert len(storage._ko_id_map) == 0
assert len(storage._created_ids) == 0
exec_result = storage.validate_and_execute(data["proposal_id"])
ko = storage.get_ko(exec_result.created_ko_id)
result = {{
    "state": exec_result.state.value,
    "ko_truth_category": str(exec_result.ko_truth_category),
    "ko_graph_category": str(ko.truth_category) if ko else None,
    "created_ko_id": exec_result.created_ko_id,
    "error": exec_result.rejection_reason,
}}
print(json.dumps(result))
''')
            data2 = _subprocess_script(phase2_script)

            assert data2["state"] == "accepted", f"Rejected: {data2['error']}"
            assert "SOURCED_MATERIAL_DATA" in data2["ko_truth_category"], \
                f"truth_category not restored: {data2['ko_truth_category']}"
            assert "SOURCED_MATERIAL_DATA" in data2["ko_graph_category"], \
                f"KO in graph missing truth_category: {data2['ko_graph_category']}"
        finally:
            for f in (phase1_script, phase2_script):
                try: os.unlink(f)
                except OSError: pass

    def test_process_restart_evidence_contradicts(self):
        """CREATE_EVIDENCE with contradicts survives actual process restart.

        Phase 1 (subprocess): create claim, submit pending CREATE_EVIDENCE/contradicts,
        wait until proposal is searchable.
        Phase 2 (subprocess): fresh process, empty cache — validate_and_execute
        finds proposal via _lookup_by_key, resolves claim_id via _resolve_ch_id
        (search), restores relation_type, creates CONTRADICTS edge.
        """
        suffix = str(uuid.uuid4())[:8]

        phase1_script = os.path.join(os.path.dirname(__file__),
                                     "_restart_phase1_ev.py")
        tmp_file = f"/tmp/sr_restart_ev_{suffix}.json"
        with open(phase1_script, "w") as f:
            f.write(f'''
import sys, uuid, json, time
sys.path.insert(0, {repr(_repo_dir)})
sys.path.insert(0, "/home/egiuth/.local/share/superretometer-runtime")
from memory_adapter import MemoryAdapter
from runtime_server import handle_submit_proposal
from cognitive_harness.model.ko import KnowledgeObject, KOType
storage = MemoryAdapter(
    server_url="{_server_url}", api_key="{_token}",
    project_id="{_project_id}",
)
ko = KnowledgeObject(type=KOType.HYPOTHESIS, title=f"Restart-Ev-Claim-{suffix}")
storage.create_ko(ko)
claim_id = ko.id
result = handle_submit_proposal({{"storage": storage}}, {{
    "proposal_type": "create_evidence",
    "proposer": "restart-test",
    "rationale": f"Process restart evidence test {{'{suffix}'}}",
    "evidence_claim_id": claim_id,
    "evidence_observation": f"Contradicts after restart {{'{suffix}'}}",
    "evidence_relation_type": "contradicts",
}})
proposal_id = result["proposal_id"]
# Wait for search indexing with retries
for attempt in range(10):
    mem_uuid = storage._lookup_by_key(f"ch:proposal:{{proposal_id}}")
    if mem_uuid:
        break
    time.sleep(1)
else:
    raise RuntimeError("Proposal not indexable after 10s")
with open({repr(tmp_file)}, "w") as out:
    json.dump({{"proposal_id": proposal_id, "claim_id": claim_id}}, out)
print(json.dumps({{"proposal_id": proposal_id, "claim_id": claim_id}}))
''')
        try:
            data1 = _subprocess_script(phase1_script)

            phase2_script = os.path.join(os.path.dirname(__file__),
                                         "_restart_phase2_ev.py")
            with open(phase2_script, "w") as f:
                f.write(f'''
import sys, json
sys.path.insert(0, {repr(_repo_dir)})
sys.path.insert(0, "/home/egiuth/.local/share/superretometer-runtime")
from memory_adapter import MemoryAdapter
from cognitive_harness.model.ko import CONTRADICTION_INBOUND
with open({repr(tmp_file)}) as f:
    data = json.load(f)
storage = MemoryAdapter(
    server_url="{_server_url}", api_key="{_token}",
    project_id="{_project_id}",
)
assert len(storage._proposals) == 0
assert len(storage._ko_id_map) == 0
exec_result = storage.validate_and_execute(data["proposal_id"])
incoming = storage.get_incoming_relations(data["claim_id"], CONTRADICTION_INBOUND)
ev_ch_ids = [src for src, rt in incoming]
result = {{
    "state": exec_result.state.value,
    "evidence_relation_type": exec_result.evidence_relation_type,
    "created_evidence_id": exec_result.created_evidence_id,
    "contradicts_edge_found": exec_result.created_evidence_id in ev_ch_ids if exec_result.created_evidence_id else False,
    "error": exec_result.rejection_reason,
}}
print(json.dumps(result))
''')
            data2 = _subprocess_script(phase2_script)

            assert data2["state"] == "accepted", f"Rejected: {data2['error']}"
            assert data2["evidence_relation_type"] == "contradicts", \
                f"relation_type not restored: {data2['evidence_relation_type']}"
            assert data2["contradicts_edge_found"], \
                "CONTRADICTS edge not created after process restart"
        finally:
            for f in (phase1_script, phase2_script):
                try: os.unlink(f)
                except OSError: pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
