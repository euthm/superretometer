"""Exercise both warrant query handlers against the same live in-process graph."""
import pytest

from cognitive_harness.mcp.server import MCPServer
from cognitive_harness.model.ko import KnowledgeObject, KOType, Provenance, RelationType
from transports.runtime_server import handle_check_warrant


@pytest.mark.parametrize("sources", [("s1", "s1", "s1"), ("s1", "s2", "s3")])
def test_warrant_root_details(sources):
    server = MCPServer()
    server.storage.create_ko(KnowledgeObject(id="claim", type=KOType.CONCLUSION))
    expected = {"claim": ["claim"]}
    for index, source in enumerate(sources):
        finding = f"finding-{index}"
        server.storage.create_ko(KnowledgeObject(
            id=finding, type=KOType.OBSERVATION,
            provenance=Provenance(source=source, author="test", independent=True),
        ))
        server.storage.create_relation(finding, "claim", RelationType.SUPPORTS)
        expected[finding] = [source]

    packaged = server._handle_check_warrant({"conclusion_ko_id": "claim"})
    runtime = handle_check_warrant({"orchestrator": server.engine}, {"ko_id": "claim"})
    assert packaged["warrant_status"] == runtime["warrant_status"]
    for response in (packaged, runtime):
        info = response["independence"]
        assert info["evidence_count"] == 3
        assert info["independent_root_count"] == len(set(sources))
        assert info["root_sets"] == expected
        shared = info["shared_ancestors"]
        if len(set(sources)) == 1:
            assert sorted(shared["s1"]) == ["finding-0", "finding-1", "finding-2"]
        else:
            assert shared == {}


def test_missing_ko_preserves_each_response_shape():
    server = MCPServer()
    packaged = server._handle_check_warrant({"conclusion_ko_id": "unknown"})
    runtime = handle_check_warrant({"orchestrator": server.engine}, {"ko_id": "unknown"})
    assert packaged["independence"] is None
    assert runtime["independence"] == {"evidence_count": 0, "independent_root_count": 0}
