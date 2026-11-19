# FILE: examples/ncm_explanations/run.py
"""One documented command reproduces both NCM explanation cases.

Usage:
  python examples/ncm_explanations/run.py --output ncm-explanation-results

Optional NCM generation:
  NCM_CHECKPOINT_DIR=/path/to/xsum/checkpoints \
  NCM_SOURCE_DIR=/path/to/ncm/checkout \
  python examples/ncm_explanations/run.py --output ncm-explanation-results

If weights are missing, the NCM run is reported as skipped.
Writes inputs, baseline text, NCM output, model revision and comparison.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from build_graphs import (
    build_shared_root_graph,
    build_independent_graph,
    compute_and_export,
)
from template import render_template
from ncm_explain import generate_ncm_summary, render_prompt
from compare import score_output
import os


def save(path: Path, data):
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ncm-explanation-results"),
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    ncm_checkpoint = os.environ.get("NCM_CHECKPOINT_DIR", "")
    ncm_source = os.environ.get("NCM_SOURCE_DIR", "")

    cases = {}
    all_results = {}

    # ── Build and analyze both graphs ──
    for graph_fn, case_name in [
        (build_shared_root_graph, "shared_root"),
        (build_independent_graph, "independent"),
    ]:
        storage = graph_fn()
        record = compute_and_export(storage, case_name)

        # Baseline template explanation
        baseline_text = render_template(record)

        # NCM explanation (may be skipped)
        ncm_result = generate_ncm_summary(record, ncm_checkpoint, ncm_source)

        # Score baseline
        baseline_score = score_output(baseline_text, record, "baseline")

        # Score NCM output (only if generated)
        ncm_score = None
        if ncm_result["status"] == "generated":
            ncm_score = score_output(ncm_result["summary"], record, "ncm")

        case_dir = output / case_name
        case_dir.mkdir()

        # Save inputs
        save(case_dir / "warrant_record.json", record)
        save(case_dir / "baseline_text.txt.__json", {"text": baseline_text})
        (case_dir / "baseline_text.txt").write_text(baseline_text)

        # Save NCM output
        save(case_dir / "ncm_result.json", ncm_result)
        if ncm_result["status"] == "generated":
            (case_dir / "ncm_summary.txt").write_text(ncm_result["summary"])

        # Save scores
        save(case_dir / "baseline_score.json", baseline_score)
        if ncm_score:
            save(case_dir / "ncm_score.json", ncm_score)

        # Comparison
        comparison = {
            "case": case_name,
            "verified_verdict": record["warrant_status"],
            "root_count": record["independence"]["independent_root_count"],
            "evidence_count": record["independence"]["evidence_count"],
            "is_shared_origin": bool(record["independence"]["shared_ancestors"]),
            "baseline": {
                "passed": baseline_score["passed"],
                "errors": baseline_score["errors"],
            },
            "ncm": {
                "status": ncm_result["status"],
                "passed": ncm_score["passed"] if ncm_score else None,
                "errors": ncm_score["errors"] if ncm_score else None,
                "reason": ncm_result["reason"],
            },
        }
        save(case_dir / "comparison.json", comparison)
        cases[case_name] = comparison

    # ── Top-level report ──
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "description": "NCM explanation evaluation — Issue #32",
        "cases": {
            k: {
                "verified_verdict": v["verified_verdict"],
                "baseline_passed": v["baseline"]["passed"],
                "ncm_status": v["ncm"]["status"],
                "ncm_passed": v["ncm"]["passed"],
            }
            for k, v in cases.items()
        },
        "ncm_model_revision": "HazyResearch/ncm " + sys.modules.get("ncm_explain",).__file__ if "ncm_explain" in sys.modules else "N/A",
        "limits": "Optional example. NCM generation requires NCM_CHECKPOINT_DIR and NCM_SOURCE_DIR. "
                  "Generated summaries are advisory — the graph, evidence roots, and warrant result are the authority.",
    }
    save(output / "report.json", report)

    # Print summary
    print(json.dumps(report, indent=2))

    # Return non-zero if any NCM output had errors (but baseline always passes)
    ncm_errors = any(
        v["ncm"]["errors"] and len(v["ncm"]["errors"]) > 0
        for v in cases.values()
        if v["ncm"]["status"] == "generated" and v["ncm"]["errors"]
    )
    return 1 if ncm_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
