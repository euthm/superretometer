"""Regression test: OrchestrationEngine and MCP server return identical
provenance-tracing fields from the same warrant result.

Verifies that root_sets and shared_ancestors are present in both code paths.
"""
from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus,
    ConfidenceLevel, RelationType, Provenance, Relation,
)
from cognitive_harness.storage.inmemory import InMemoryStorage
from cognitive_harness.reasoning.rule_engine import RuleEngineReasoner
from cognitive_harness.orchestration.engine import OrchestrationEngine, _build_warrant_response
from cognitive_harness.mcp.server import MCPServer


def build_test_graph():
    """Build a small graph with shared provenance."""
    storage = InMemoryStorage()

    # Shared source
    storage.create_ko(KnowledgeObject(
        id="sim-1", type=KOType.MODEL_RESULT,
        title="Simulation run",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="sim-engine", author="team", independent=True),
    ))

    # Two findings from same sim
    for fid, ftitle in [("f1", "Temp OK"), ("f2", "Stress OK")]:
        storage.create_ko(KnowledgeObject(
            id=fid, type=KOType.FINDING, title=ftitle,
            truth_category=TruthCategory.MODEL_DERIVED,
            epistemic_status=EpistemicStatus.PROPOSED,
            confidence=ConfidenceLevel.HIGH,
            provenance=Provenance(source="sim-engine", author="team"),
            relations=[Relation(to="sim-1", type=RelationType.DERIVED_FROM)],
        ))
        storage.create_relation(fid, "sim-1", RelationType.DERIVED_FROM)

    # Conclusion
    storage.create_ko(KnowledgeObject(
        id="conc", type=KOType.CONCLUSION,
        title="System is safe",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="analysis", author="reviewer"),
    ))
    for fid in ["f1", "f2"]:
        storage.create_relation(fid, "conc", RelationType.SUPPORTS)

    return storage


def test_orchestration_has_root_sets():
    """OrchestrationEngine.check_warrant must include root_sets and shared_ancestors."""
    storage = build_test_graph()
    reasoner = RuleEngineReasoner(storage)
    engine = OrchestrationEngine(storage, reasoner)

    result = engine.check_warrant("conc")

    assert "independence" in result, "Missing independence block"
    indep = result["independence"]
    assert "root_sets" in indep, "OrchestrationEngine check_warrant missing root_sets"
    assert "shared_ancestors" in indep, "OrchestrationEngine check_warrant missing shared_ancestors"

    # Verify content
    assert indep["evidence_count"] >= 2
    assert indep["independent_root_count"] == 1  # single shared root
    assert "sim-engine" in indep["root_sets"].values().__iter__().__class__.__name__ or \
           any("sim-engine" in v for v in indep["root_sets"].values()), \
           "Expected sim-engine root not found in root_sets"

    print(f"  root_sets: {indep['root_sets']}")
    print(f"  shared_ancestors: {indep['shared_ancestors']}")
    print("  PASS: OrchestrationEngine returns full provenance tracing")


def test_mcp_server_has_root_sets():
    """Packaged MCP server must also include root_sets and shared_ancestors."""
    server = MCPServer()

    # Build graph in the server's storage
    storage = build_test_graph()
    # Replace server storage with our test graph
    server.storage = storage
    from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer
    server.wa = WarrantAnalyzer(storage)

    result = server._handle_check_warrant({"conclusion_ko_id": "conc"})

    assert "independence" in result, "MCP server missing independence block"
    indep = result["independence"]
    assert "root_sets" in indep, "MCP server missing root_sets"
    assert "shared_ancestors" in indep, "MCP server missing shared_ancestors"

    print(f"  root_sets: {indep['root_sets']}")
    print(f"  shared_ancestors: {indep['shared_ancestors']}")
    print("  PASS: MCP server returns full provenance tracing")


def test_both_paths_agree():
    """Both code paths must return the same provenance-tracing fields."""
    storage = build_test_graph()

    # OrchestrationEngine path
    reasoner = RuleEngineReasoner(storage)
    engine = OrchestrationEngine(storage, reasoner)
    oe_result = engine.check_warrant("conc")

    # Direct builder path (what MCP server uses)
    from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer
    wa = WarrantAnalyzer(storage)
    raw = wa.compute_warrant("conc")
    mcp_result = _build_warrant_response(raw)

    # Compare independence blocks
    assert oe_result["independence"] == mcp_result["independence"], (
        f"independence blocks differ:\nOE: {oe_result['independence']}\nMCP: {mcp_result['independence']}"
    )

    # Compare warrant status and classifications
    assert oe_result["warrant_status"] == mcp_result["warrant_status"]
    assert oe_result["independent_kos"] == mcp_result["independent_kos"]
    assert oe_result["dependent_kos"] == mcp_result["dependent_kos"]

    print("  PASS: Both paths return identical provenance-tracing fields")


if __name__ == "__main__":
    test_orchestration_has_root_sets()
    print()
    test_mcp_server_has_root_sets()
    print()
    test_both_paths_agree()
    print("\nProvenance tracing parity: PASS")
