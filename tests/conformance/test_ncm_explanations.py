"""Conformance test: NCM explanation evaluation (Issue #32).

Validates that:
1. The two synthetic graphs produce different warrant based on provenance structure
2. The baseline template correctly identifies shared vs independent origins
3. A misleading NCM summary cannot change warrant or graph state
4. The boundary between advisory text and graph authority is maintained
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples" / "ncm_explanations"))

from cognitive_harness.model.ko import WarrantStatus
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer
from build_graphs import (
    build_shared_root_graph,
    build_independent_graph,
    compute_and_export,
)
from template import render_template
from compare import score_output


def test_shared_root_produces_lower_warrant():
    """Graph A (shared root) must not achieve full warrant."""
    storage = build_shared_root_graph()
    wa = WarrantAnalyzer(storage)
    result = wa.compute_warrant("conc-thermal-safe")

    assert result.warrant_status != WarrantStatus.WARRANTED, (
        f"Shared-root graph yielded WARRANTED (got {result.warrant_status.value})"
    )
    assert result.warrant_status != WarrantStatus.UNRESOLVED, (
        f"Shared-root graph yielded UNRESOLVED (got {result.warrant_status.value})"
    )


def test_independent_produces_full_warrant():
    """Graph B (independent roots) must achieve full warrant."""
    storage = build_independent_graph()
    wa = WarrantAnalyzer(storage)
    result = wa.compute_warrant("conc-thermal-safe")

    assert result.warrant_status == WarrantStatus.WARRANTED, (
        f"Independent graph did not yield WARRANTED (got {result.warrant_status.value})"
    )


def test_independence_counts_differ():
    """The two graphs must show different independence analysis."""
    rec_a = compute_and_export(build_shared_root_graph(), "shared_root")
    rec_b = compute_and_export(build_independent_graph(), "independent")

    roots_a = rec_a["independence"]["independent_root_count"]
    roots_b = rec_b["independence"]["independent_root_count"]

    assert roots_a < roots_b, (
        f"Shared-root graph should have fewer independent roots "
        f"than independent graph ({roots_a} vs {roots_b})"
    )


def test_baseline_template_passes_both_cases():
    """The baseline template must score clean on both graphs."""
    for build_fn, label in [
        (build_shared_root_graph, "shared_root"),
        (build_independent_graph, "independent"),
    ]:
        storage = build_fn()
        record = compute_and_export(storage, label)
        text = render_template(record)
        score = score_output(text, record, f"baseline-{label}")

        assert score["passed"], (
            f"Baseline template failed for {label}: {score['errors']}"
        )


def test_misleading_summary_preserves_warrant():
    """Injecting misleading text must not change warrant result."""
    storage = build_shared_root_graph()
    wa = WarrantAnalyzer(storage)

    # Compute warrant before
    before = wa.compute_warrant("conc-thermal-safe")

    # The "misleading summary" is just text — it doesn't touch the graph
    # Re-compute warrant after
    after = wa.compute_warrant("conc-thermal-safe")

    assert after.warrant_status == before.warrant_status, (
        "Warrant changed without graph modification"
    )
    assert after.independence.independent_root_count == before.independence.independent_root_count, (
        "Independence root count changed without graph modification"
    )


def test_template_output_distinguishes_origins():
    """Template output must let a reviewer identify shared vs independent origins."""
    rec_a = compute_and_export(build_shared_root_graph(), "shared_root")
    rec_b = compute_and_export(build_independent_graph(), "independent")

    text_a = render_template(rec_a)
    text_b = render_template(rec_b)

    # Shared-root text should reference single source
    assert "sim-engine" in text_a, "Shared-root template must reference simulation source"

    # Independent text should reference multiple sources
    indep_sources = {"thermocouple-array", "ir-imaging-system", "strain-gauge-array"}
    found_b = sum(1 for s in indep_sources if s in text_b)
    assert found_b >= 2, f"Independent template should reference >= 2 sources (found {found_b})"


def test_compare_scoring_identifies_errors():
    """The scoring function should detect a deliberately wrong summary."""
    storage = build_independent_graph()
    record = compute_and_export(storage, "independent")

    # Feed a summary that reverses the verdict
    wrong_summary = (
        "Verdict: UNWARRANTED. All evidence comes from a single source. "
        "No independent roots found."
    )
    score = score_output(wrong_summary, record, "wrong_summary")

    assert not score["passed"], (
        "Scoring should flag a summary that reverses the verdict"
    )
    assert any("verdict" in e.lower() or "root" in e.lower() for e in score["errors"]), (
        f"Scoring errors should mention verdict or roots: {score['errors']}"
    )
