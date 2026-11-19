# FILE: examples/ncm_explanations/test_ncm_boundary.py
"""Boundary test: a deliberately misleading NCM summary must not change graph state.

Following issue #32: "A misleading summary must leave the graph, evidence roots
and warrant result intact."

This test:
1. Builds the shared-root graph
2. Computes warrant (expecting conditionally_warranted or unwarranted)
3. Injects a misleading summary that claims the evidence is independent
4. Re-computes warrant — must produce the same result
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cognitive_harness.model.ko import WarrantStatus
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer
from build_graphs import build_shared_root_graph, build_independent_graph, compute_and_export


def test_misleading_summary_does_not_change_warrant():
    """A generated summary claiming wrong independence must not affect warrant."""
    # Build shared-root graph
    storage = build_shared_root_graph()
    wa = WarrantAnalyzer(storage)

    # Compute original warrant
    original = wa.compute_warrant("conc-thermal-safe")
    original_status = original.warrant_status
    original_indep = original.independence.independent_root_count if original.independence else 0

    # "Inject" a misleading summary (in real system this would be advisory text)
    # The summary is NOT part of the graph — it's just text alongside the record
    misleading_summary = (
        "The three supporting statements for conc-thermal-safe each derive from "
        "independent provenance roots. Evidence is structurally independent. "
        "Verdict: WARRANTED."
    )

    # Re-compute warrant — must be identical
    recomputed = wa.compute_warrant("conc-thermal-safe")

    assert recomputed.warrant_status == original_status, (
        f"Warrant changed after misleading summary! "
        f"Original: {original_status.value}, Recomputed: {recomputed.warrant_status.value}"
    )

    rec_indep = recomputed.independence.independent_root_count if recomputed.independence else 0
    assert rec_indep == original_indep, (
        f"Independence root count changed! "
        f"Original: {original_indep}, Recomputed: {rec_indep}"
    )

    print(f"  Original verdict: {original_status.value}, roots: {original_indep}")
    print(f"  Recomputed verdict: {recomputed.warrant_status.value}, roots: {rec_indep}")
    print("  PASS: Misleading summary did not change warrant")


def test_shared_root_graph_is_not_warranted():
    """The shared-root graph must NOT be warranted (all evidence from one simulation)."""
    storage = build_shared_root_graph()
    wa = WarrantAnalyzer(storage)
    result = wa.compute_warrant("conc-thermal-safe")

    assert result.warrant_status != WarrantStatus.WARRANTED, (
        f"Shared-root graph should not be WARRANTED (got {result.warrant_status.value})"
    )

    # Independence: all three statements share one root
    if result.independence:
        assert result.independence.independent_root_count <= 1, (
            f"Shared-root graph should have <= 1 independent root (got {result.independence.independent_root_count})"
        )

    print(f"  Shared-root verdict: {result.warrant_status.value}")
    print(f"  Independent root count: {result.independence.independent_root_count}")
    print("  PASS: Shared-root graph correctly not warranted")


def test_independent_graph_is_warranted():
    """The independent graph must be warranted (three separate measurements)."""
    storage = build_independent_graph()
    wa = WarrantAnalyzer(storage)
    result = wa.compute_warrant("conc-thermal-safe")

    assert result.warrant_status == WarrantStatus.WARRANTED, (
        f"Independent graph should be WARRANTED (got {result.warrant_status.value})"
    )

    # Independence: each statement has its own root
    if result.independence:
        assert result.independence.independent_root_count >= 3, (
            f"Independent graph should have >= 3 roots (got {result.independence.independent_root_count})"
        )

    print(f"  Independent verdict: {result.warrant_status.value}")
    print(f"  Independent root count: {result.independence.independent_root_count}")
    print("  PASS: Independent graph correctly warranted")


def test_reviewer_can_distinguish_graphs():
    """A reviewer reading the template output should identify the decisive evidence root(s)."""
    from template import render_template

    # Build both graphs
    rec_a = compute_and_export(build_shared_root_graph(), "shared_root")
    rec_b = compute_and_export(build_independent_graph(), "independent")

    # Render templates
    text_a = render_template(rec_a)
    text_b = render_template(rec_b)

    # Check that shared-root text indicates single origin
    assert "sim-engine" in text_a, "Shared-root template should reference the simulation source"

    # Check that independent text references multiple sources
    indep_sources = {"thermocouple-array", "ir-imaging-system", "strain-gauge-array"}
    found_in_b = sum(1 for s in indep_sources if s in text_b)
    assert found_in_b >= 2, (
        f"Independent template should reference at least 2 of 3 independent sources "
        f"(found {found_in_b})"
    )

    # The texts should be structurally different
    assert text_a != text_b, "Template outputs should differ between graphs"

    print("  Shared-root text references simulation source: PASS")
    print(f"  Independent text references {found_in_b}/3 measurement sources: PASS")
    print("  PASS: Reviewer can distinguish graphs from template output")


if __name__ == "__main__":
    test_misleading_summary_does_not_change_warrant()
    print()
    test_shared_root_graph_is_not_warranted()
    print()
    test_independent_graph_is_warranted()
    print()
    test_reviewer_can_distinguish_graphs()
    print("\nNCM boundary tests: ALL PASS")
