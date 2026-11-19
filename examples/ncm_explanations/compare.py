# FILE: examples/ncm_explanations/compare.py
"""Score explanation outputs against the verified verdict.

For each output (baseline template and NCM summary), check:
1. Does it state the correct warrant verdict?
2. Does it mention the correct number of evidence roots?
3. Does it identify the correct root IDs?
4. Does it state whether evidence is shared or independent?

A fluent summary that gets one of these wrong is flagged.
"""
from __future__ import annotations
import re


def score_output(text: str, record: dict, label: str) -> dict:
    """Score an explanation output against the verified warrant record.

    Returns a dict with boolean checks and error messages.
    """
    indep = record.get("independence", {})
    root_count = indep.get("independent_root_count", 0)
    ev_count = indep.get("evidence_count", 0)
    verdict = record["warrant_status"]
    root_sets = indep.get("root_sets", {})
    shared = indep.get("shared_ancestors", {})

    # Collect all root IDs referenced in the record
    all_root_ids = set()
    for roots in root_sets.values():
        all_root_ids.update(roots)

    # Determine ground truth: shared vs independent
    is_shared_origin = len(shared) > 0
    is_independent_origin = not is_shared_origin and root_count >= ev_count

    score = {
        "label": label,
        "output_length": len(text),
        "errors": [],
    }

    text_lower = text.lower()

    # 1. Verdict check
    verdict_found = verdict in text_lower
    if not verdict_found:
        score["errors"].append(
            f"Missing verdict '{verdict}'. Output does not contain the verified warrant status."
        )
    score["verdict_correct"] = verdict_found

    # 2. Root count check
    # Look for the number of independent roots mentioned
    root_count_str = str(root_count)
    root_count_found = root_count_str in text
    if not root_count_found and ev_count > 0:
        score["errors"].append(
            f"Missing root count '{root_count}'. Output should reference the number of independent provenance roots."
        )
    score["root_count_correct"] = root_count_found

    # 3. Root IDs check
    # Check if at least some root IDs are referenced
    root_ids_found = 0
    for rid in all_root_ids:
        if rid in text:
            root_ids_found += 1
    score["root_ids_referenced"] = root_ids_found
    score["root_ids_total"] = len(all_root_ids)
    if all_root_ids and root_ids_found == 0:
        score["errors"].append(
            f"No evidence root IDs referenced. Root IDs present: {sorted(all_root_ids)}."
        )

    # 4. Shared vs independent origin
    if is_shared_origin:
        # Should indicate shared/single origin
        shared_indicators = ["shared", "single", "same", "one root", "common", "correlated"]
        indicates_shared = any(ind in text_lower for ind in shared_indicators)
        if not indicates_shared:
            score["errors"].append(
                "Output does not indicate shared/single provenance origin. "
                "Ground truth: all evidence derives from one simulation."
            )
        score["origin_classification_correct"] = indicates_shared
    elif is_independent_origin:
        # Should indicate independent origins
        independent_indicators = ["independent", "separate", "distinct", "different sources"]
        indicates_independent = any(ind in text_lower for ind in independent_indicators)
        if not indicates_independent:
            score["errors"].append(
                "Output does not indicate independent provenance origins. "
                "Ground truth: each statement derives from a separate measurement."
            )
        score["origin_classification_correct"] = indicates_independent

    # 5. Check for fabricated IDs (IDs not in the record)
    # This is a soft check: we look for patterns like "ID: xxx" or KO IDs
    ko_ids_in_record = set(record.get("all_ko_ids", [])) | all_root_ids
    # Don't flag this as an error yet — NCM summaries may paraphrase

    # 6. Check for verdict reversal
    if verdict == "warranted" and "unwarranted" in text_lower:
        score["errors"].append("VERDICT REVERSAL: output says 'unwarranted' but verified verdict is 'warranted'.")
    elif verdict == "unwarranted" and "warranted" in text_lower and "conditionally" not in text_lower:
        # Be careful: "conditionally_warranted" contains "warranted"
        pass  # The verdict check above handles this

    score["total_errors"] = len(score["errors"])
    score["passed"] = len(score["errors"]) == 0

    return score
