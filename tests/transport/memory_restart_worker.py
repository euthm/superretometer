"""Subprocess worker for opt-in Memory restart tests. Never generates source files."""
import json
import os
from pathlib import Path
import sys
import time

from transports import memory_adapter, runtime_server
from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, CONTRADICTION_INBOUND,
)


def fresh_storage():
    checkout = Path(__file__).resolve().parents[2]
    for module in (memory_adapter, runtime_server):
        assert Path(module.__file__).resolve().is_relative_to(checkout)
    return memory_adapter.MemoryAdapter(
        server_url=os.environ["MEMORY_SERVER_URL"],
        api_key=os.environ["MEMORY_API_KEY"],
        project_id=os.environ["MEMORY_PROJECT_ID"],
    )


def wait_for_search(keys):
    # A fresh adapter cannot succeed through the submitter's _created_ids cache.
    reader = fresh_storage()
    for _ in range(20):
        if all(reader._lookup_by_key(key) for key in keys):
            return
        time.sleep(0.5)
    raise RuntimeError("Submitted objects not searchable after 10 seconds")


def run(phase, data):
    storage = fresh_storage()
    assert not storage._proposals and not storage._ko_id_map and not storage._created_ids
    if phase in ("submit_ko", "submit_evidence"):
        args = {"proposer": "restart-test", "rationale": "Restart regression"}
        keys = []
        if phase == "submit_ko":
            args.update(proposal_type="create_ko", ko_type="observation",
                        ko_title="Process restart observation",
                        ko_scope="restart-test-boundary",
                        ko_truth_category="sourced_material_data")
        else:
            claim = KnowledgeObject(type=KOType.HYPOTHESIS, title="Restart evidence claim")
            storage.create_ko(claim)
            data["claim_id"] = claim.id
            keys.append(f"ch:ko:{claim.id}")
            args.update(proposal_type="create_evidence", evidence_claim_id=claim.id,
                        evidence_observation="Counter-evidence after restart",
                        evidence_relation_type="contradicts")
        result = runtime_server.handle_submit_proposal({"storage": storage}, args)
        assert "error" not in result, result
        data["proposal_id"] = result["proposal_id"]
        keys.append(f"ch:proposal:{data['proposal_id']}")
        wait_for_search(keys)
        return data
    if phase in ("execute_ko", "execute_evidence"):
        result = storage.validate_and_execute(data["proposal_id"])
        data["state"] = result.state.value
        assert data["state"] == "accepted", result.rejection_reason
        if phase == "execute_ko":
            ko = storage.get_ko(result.created_ko_id)
            data.update(type=ko.type.value, scope=ko.scope,
                        truth_category=ko.truth_category.value)
        else:
            data["evidence_id"] = result.created_evidence_id
            wait_for_search([f"ch:ko:{result.created_evidence_id}"])
        return data
    if phase == "read_evidence":
        evidence = storage.get_evidence(data["evidence_id"])
        assert evidence is not None
        evidence["edge_found"] = any(
            source == data["evidence_id"] for source, _ in
            storage.get_incoming_relations(data["claim_id"], CONTRADICTION_INBOUND))
        evidence["listed"] = any(
            ev["id"] == data["evidence_id"] for ev in
            storage.list_evidence_for_ko(data["claim_id"]))
        return evidence
    raise ValueError(f"Unknown phase: {phase}")


if __name__ == "__main__":
    print(json.dumps(run(sys.argv[1], json.load(sys.stdin))))
