# FILE: examples/nibio_demo.py
"""Live demo: NIBIO simulation agreement does not validate biological yield.

Builds a small evidence graph in the active Memory project and runs
check_warrant on the conclusion. Demonstrates that root_sets and
shared_ancestors are now returned by both the packaged MCP server and
the runtime OrchestrationEngine.

Usage:
    python examples/nibio_demo.py

Requires: Memory server running, active project configured.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer
from cognitive_harness.orchestration.engine import _build_warrant_response
from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus,
    ConfidenceLevel, RelationType, Provenance, Relation,
)
from transports.memory_adapter import MemoryAdapter


def main():
    # Connect to active Memory project
    adapter = MemoryAdapter(
        server_url="http://localhost:3002",
        api_key="emt_c5e902110641e9add7cbc5ad5903c2169455cc207e1633893c9f95bb736b68ed",
        project_id="5dba4c18-a92e-458c-836c-1a32e31b7214",
    )

    # ── Build NIBIO evidence graph ──

    # Source: simulation comparison (simuleringsrapport v9, side 8)
    adapter.create_ko(KnowledgeObject(
        id="nibio-sim-comparison",
        type=KOType.FINDING,
        title="Python-OpenModelica model comparison",
        content="1344 points compared. Max deviation 0.032. Mean steady-state deviation 0.012.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(
            source="simuleringsrapport-v9-p8", author="nibio-team", independent=True,
        ),
    ))

    adapter.create_ko(KnowledgeObject(
        id="nibio-max-dev",
        type=KOType.FINDING,
        title="Max deviation 0.032 over 1344 points",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="simuleringsrapport-v9-p8", author="nibio-team"),
        relations=[Relation(to="nibio-sim-comparison", type=RelationType.DERIVED_FROM)],
    ))

    adapter.create_ko(KnowledgeObject(
        id="nibio-mean-dev",
        type=KOType.FINDING,
        title="Mean steady-state deviation 0.012",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="simuleringsrapport-v9-p8", author="nibio-team"),
        relations=[Relation(to="nibio-sim-comparison", type=RelationType.DERIVED_FROM)],
    ))

    adapter.create_ko(KnowledgeObject(
        id="nibio-yield-validated",
        type=KOType.CONCLUSION,
        title="Python-OpenModelica agreement validates biological yield",
        content="Numerical agreement between implementations validates biological yield model.",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.PROPOSED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="nibio-analysis", author="reviewer"),
    ))

    # Edges
    for fid in ("nibio-max-dev", "nibio-mean-dev"):
        adapter.create_relation(fid, "nibio-sim-comparison", RelationType.DERIVED_FROM)
        adapter.create_relation(fid, "nibio-yield-validated", RelationType.SUPPORTS)

    # ── Run warrant analysis ──
    wa = WarrantAnalyzer(adapter)
    raw = wa.compute_warrant("nibio-yield-validated")
    result = _build_warrant_response(raw)

    print(json.dumps(result, indent=2, default=str))
    print()
    print("Decision:")
    print("  Use the comparison as support for numerical consistency.")
    print("  Keep biological yield as an open assumption until validated")
    print("  against independent measurements.")

    return result


if __name__ == "__main__":
    main()
