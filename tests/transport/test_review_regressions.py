"""Review regressions against checkout code and a local, deterministic Memory API.

The HTTP fixture assigns UUIDs independently of CH IDs and keeps state across
adapter instances and subprocesses. No AI1 credentials or service is required.
"""
from copy import deepcopy
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import uuid

import pytest

from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, ConfidenceLevel, EpistemicStatus,
    RelationType,
)
from cognitive_harness.model.proposal import Proposal, ProposalType, ProposalState
from transports.memory_adapter import (
    MemoryAdapter, proposal_to_properties, proposal_from_properties,
)


@pytest.fixture(scope="module")
def memory_api():
    objects, edges = {}, []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, data, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def body(self):
            return json.loads(self.rfile.read(int(self.headers["Content-Length"])))

        def do_POST(self):
            data = self.body()
            if self.path == "/api/graph/objects":
                ident = str(uuid.uuid4())
                objects[ident] = deepcopy(dict(data, id=ident, canonical_id=ident))
                return self.respond(objects[ident], 201)
            if self.path == "/api/graph/search":
                hits = [o for o in objects.values() if o["key"] == data["query"]]
                offset, limit = data.get("offset", 0), data.get("limit", 200)
                return self.respond({"data": [{"object": o} for o in hits[offset:offset + limit]]})
            if self.path == "/api/graph/relationships":
                if data["src_id"] not in objects or data["dst_id"] not in objects:
                    return self.respond({"error": "UUID required"}, 400)
                edges.append(dict(data, id=str(uuid.uuid4())))
                return self.respond(edges[-1], 201)
            self.respond({}, 404)

        def do_GET(self):
            ident = self.path.removeprefix("/api/graph/objects/")
            if ident.endswith("/edges"):
                ident = ident.removesuffix("/edges")
                return self.respond({
                    "incoming": [e for e in edges if e["dst_id"] == ident],
                    "outgoing": [e for e in edges if e["src_id"] == ident],
                })
            self.respond(objects.get(ident, {}), 200 if ident in objects else 404)

        def do_PATCH(self):
            ident = self.path.removeprefix("/api/graph/objects/")
            if ident not in objects:
                return self.respond({}, 404)
            objects[ident]["properties"].update(self.body()["properties"])
            self.respond(objects[ident])

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    yield url, objects, edges
    server.shutdown()
    server.server_close()
    thread.join()


def adapter(memory_api):
    return MemoryAdapter(server_url=memory_api[0], api_key="fixture-token", project_id="fixture-project")


@pytest.mark.parametrize("content", [None, False, 0, "", {}, [], "plain text"])
def test_proposal_preserves_type_boundary_and_falsy_content(memory_api, content):
    writer = adapter(memory_api)
    proposal = Proposal(
        type=ProposalType.CREATE_KO, ko_type=KOType.OBSERVATION,
        ko_title="Observation", ko_scope="test-only-boundary", ko_content=content,
        ko_truth_category=TruthCategory.VALIDATION_RESULT,
        ko_assumptions=["fixture assumption"], ko_viewpoints=["fixture viewpoint"],
        ko_confidence=ConfidenceLevel.LOW,
        ko_valid_from="2026-01-01T00:00:00+00:00", ko_valid_to="2027-01-01T00:00:00+00:00",
    )
    writer.submit_proposal(proposal)
    reader = adapter(memory_api)
    result = reader.validate_and_execute(proposal.id)
    assert result.state == ProposalState.ACCEPTED, result.rejection_reason
    ko = reader.get_ko(result.created_ko_id)
    assert ko.type == KOType.OBSERVATION
    assert ko.scope == proposal.ko_scope
    assert ko.content == content
    assert ko.truth_category == proposal.ko_truth_category
    assert ko.confidence == proposal.ko_confidence
    assert ko.assumptions == proposal.ko_assumptions
    assert ko.viewpoint_ids == proposal.ko_viewpoints
    assert ko.valid_from.isoformat() == proposal.ko_valid_from
    assert ko.valid_to.isoformat() == proposal.ko_valid_to
    # Accepted result IDs survive yet another restart; no second mutation.
    count = len(memory_api[1])
    again = adapter(memory_api).validate_and_execute(proposal.id)
    assert again.created_ko_id == result.created_ko_id
    assert len(memory_api[1]) == count


def test_all_proposal_fields_roundtrip():
    proposal = Proposal(
        type=ProposalType.CREATE_RELATION, ko_type=KOType.FINDING,
        ko_content={"empty": False}, ko_scope="boundary",
        ko_truth_category=TruthCategory.PHYSICAL_OBSERVATION,
        ko_viewpoints=["v"], ko_assumptions=["a"], ko_confidence=ConfidenceLevel.HIGH,
        ko_valid_from="start", ko_valid_to="end", target_ko_id="target",
        updates={"confidence": ConfidenceLevel.LOW, "title": "new"},
        target_status=EpistemicStatus.TENTATIVE,
        from_ko_id="from", to_ko_id="to", relation_type=RelationType.CONTRADICTS,
        tension_title="t", tension_description="desc", tension_ko_ids=["k"],
        tension_viewpoints=["v"], evidence_claim_id="claim",
        evidence_observation="obs", evidence_records=[{"value": 0}],
        evidence_relation_type="contradicts", successor_ko_id="next",
        created_ko_id="ko-result", created_evidence_id="ev-result", created_tension_id="t-result",
    )
    persisted = json.loads(json.dumps(proposal_to_properties(proposal)))
    assert asdict(proposal_from_properties(proposal.id, persisted)) == asdict(proposal)


@pytest.mark.parametrize("kind", [ProposalType.UPDATE_KO, ProposalType.TRANSITION_STATUS, ProposalType.CREATE_RELATION])
def test_non_create_proposals_execute_after_restart(memory_api, kind):
    writer = adapter(memory_api)
    claim = KnowledgeObject(title="Before")
    other = KnowledgeObject(title="Other")
    writer.create_ko(claim)
    writer.create_ko(other)
    proposal = Proposal(type=kind, target_ko_id=claim.id, updates={"title": "After"},
                        target_status=EpistemicStatus.TENTATIVE,
                        from_ko_id=other.id, to_ko_id=claim.id,
                        relation_type=RelationType.SUPPORTS)
    writer.submit_proposal(proposal)
    reader = adapter(memory_api)
    result = reader.validate_and_execute(proposal.id)
    assert result.state == ProposalState.ACCEPTED, result.rejection_reason
    if kind == ProposalType.UPDATE_KO:
        assert reader.get_ko(claim.id).title == "After"
    elif kind == ProposalType.TRANSITION_STATUS:
        assert reader.get_ko(claim.id).epistemic_status == EpistemicStatus.TENTATIVE
    else:
        assert (other.id, RelationType.SUPPORTS) in reader.get_incoming_relations(claim.id)


@pytest.mark.parametrize("relation", ["supports", "contradicts"])
def test_evidence_read_list_and_result_survive_fresh_adapters(memory_api, relation):
    writer = adapter(memory_api)
    claim = KnowledgeObject(title="Claim")
    writer.create_ko(claim)
    proposal = Proposal(type=ProposalType.CREATE_EVIDENCE, evidence_claim_id=claim.id,
                        evidence_observation="Observed result", evidence_records=[{"measured": 17}],
                        evidence_relation_type=relation)
    writer.submit_proposal(proposal)
    execution = adapter(memory_api).validate_and_execute(proposal.id)
    assert execution.state == ProposalState.ACCEPTED, execution.rejection_reason
    eid = execution.created_evidence_id
    reader = adapter(memory_api)
    evidence = reader.get_evidence(eid)
    assert evidence["claim_id"] == claim.id
    assert evidence["records"] == [{"measured": 17}]
    assert evidence["relation_type"] == relation
    assert reader._ko_id_map[eid] != eid
    assert adapter(memory_api).list_evidence_for_ko(claim.id) == [evidence]
    again = adapter(memory_api).validate_and_execute(proposal.id)
    assert again.created_evidence_id == eid


def test_legacy_evidence_recovers_missing_claim_from_edge(memory_api):
    writer = adapter(memory_api)
    claim = KnowledgeObject(title="Legacy claim")
    writer.create_ko(claim)
    eid = f"legacy-{uuid.uuid4()}"
    writer.add_evidence(eid, claim.id, "verified", "Legacy observation", [])
    ident = writer._ko_id_map[eid]
    memory_api[1][ident]["properties"]["content"].pop("claim_id")
    evidence = adapter(memory_api).get_evidence(eid)
    assert evidence["claim_id"] == claim.id
    assert evidence["relation_type"] == "supports"


def test_evidence_source_and_failed_edge_are_not_hidden_by_cache(memory_api, monkeypatch):
    writer = adapter(memory_api)
    claim = KnowledgeObject(title="Claim")
    writer.create_ko(claim)
    eid = f"source-{uuid.uuid4()}"
    writer.add_evidence(eid, claim.id, "verified", "Source", [], source_ko_id="source-id")
    assert adapter(memory_api).get_evidence(eid)["source_ko_id"] == "source-id"
    monkeypatch.setattr(writer, "_create_edge", lambda *args: False)
    failed = f"failed-{uuid.uuid4()}"
    with pytest.raises(RuntimeError, match="graph link missing"):
        writer.add_evidence(failed, claim.id, "pending", "Failed edge", [])
    assert failed not in writer._evidence


def test_legacy_proposal_fields_restore_without_new_metadata():
    proposal = proposal_from_properties("legacy", {
        "ch_proposal_type": "create_ko", "ch_proposal_state": "pending",
        "ch_proposal_ko_type": "observation", "ch_proposal_ko_title": "Old proposal",
        "ch_proposal_ko_content": "unencoded text", "ch_proposal_ko_truth_category": "",
    })
    assert proposal.ko_type == KOType.OBSERVATION
    assert proposal.ko_content == "unencoded text"
    assert proposal.ko_truth_category is None


def test_checkout_workers_restart_without_generating_secret_files(memory_api, monkeypatch, tmp_path):
    from tests.transport import test_truth_category_integration as live
    monkeypatch.setattr(live, "_server_url", memory_api[0])
    monkeypatch.setattr(live, "_token", "fixture-secret-never-written")
    monkeypatch.setattr(live, "_project_id", "fixture-project")
    # A stale flat runtime module must not override package imports.
    (tmp_path / "memory_adapter.py").write_text("raise RuntimeError('wrong runtime')")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    directory = Path(live.__file__).parent
    before = set(directory.glob("_restart_phase*.py"))
    submitted = live._subprocess_phase("submit_ko", {})
    restored = live._subprocess_phase("execute_ko", submitted)
    assert restored["type"] == "observation"
    assert restored["scope"] == "restart-test-boundary"
    submitted = live._subprocess_phase("submit_evidence", {})
    executed = live._subprocess_phase("execute_evidence", submitted)
    restored = live._subprocess_phase("read_evidence", executed)
    assert restored["relation_type"] == "contradicts"
    assert restored["edge_found"] and restored["listed"]
    assert set(directory.glob("_restart_phase*.py")) == before
