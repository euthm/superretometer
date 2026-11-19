# FILE: examples/ncm_explanations/template.py
"""Baseline plain-text explanation template.

Takes a structured warrant record (from build_graphs.compute_and_export) and
renders a deterministic, human-readable explanation. This is the baseline
against which NCM-generated summaries are compared.
"""
from __future__ import annotations


def render_template(record: dict) -> str:
    """Render a warrant record as a plain-text explanation.

    The template is intentionally mechanical: it exposes every field that
    a reviewer needs to verify the verdict, including evidence root IDs
    and derivation links.  No prose generation — just structured facts.
    """
    lines = []
    lines.append(f"Explanatory record for {record['label']}")
    lines.append("=" * 50)
    lines.append("")

    # Verdict
    lines.append(f"VERDICT: {record['warrant_status'].upper()}")
    lines.append(f"Conclusion ID: {record['conclusion_id']}")
    lines.append("")

    # Evidence summary
    lines.append("EVIDENCE SUMMARY")
    lines.append("-" * 30)
    indep = record.get("independence", {})
    lines.append(f"Supporting KOs: {indep.get('evidence_count', 0)}")
    lines.append(f"Independent provenance roots: {indep.get('independent_root_count', 0)}")
    lines.append("")

    # Evidence root detail
    lines.append("EVIDENCE ROOTS BY STATEMENT")
    lines.append("-" * 30)
    root_sets = indep.get("root_sets", {})
    for ev_id, roots in sorted(root_sets.items()):
        lines.append(f"  {ev_id} -> roots: {', '.join(roots) if roots else 'NONE'}")
    lines.append("")

    # Shared ancestors
    shared = indep.get("shared_ancestors", {})
    if shared:
        lines.append("SHARED PROVENANCE ANCESTORS")
        lines.append("-" * 30)
        for root, kos in sorted(shared.items()):
            lines.append(f"  Root '{root}' shared by: {', '.join(kos)}")
        lines.append("")
    else:
        lines.append("NO SHARED PROVENANCE ANCESTORS")
        lines.append("")

    # Classification
    lines.append("CLASSIFICATION")
    lines.append("-" * 30)
    if record["independent_kos"]:
        lines.append(f"Independently grounded: {', '.join(record['independent_kos'])}")
    if record["dependent_kos"]:
        lines.append(f"Dependent/ungrounded: {', '.join(record['dependent_kos'])}")
    lines.append("")

    # Anti-patterns
    if record["anti_pattern_diagnoses"]:
        lines.append("ANTI-PATTERN DIAGNOSES")
        lines.append("-" * 30)
        for d in record["anti_pattern_diagnoses"]:
            lines.append(f"  [{d['pattern']}]")
            lines.append(f"    Offending: {', '.join(d['offending_ko_ids'])}")
            lines.append(f"    Condition: {d['violated_condition']}")
        lines.append("")

    # Conditional assumptions
    if record["conditional_assumptions"]:
        lines.append("CONDITIONAL ASSUMPTIONS / GAPS")
        lines.append("-" * 30)
        for a in record["conditional_assumptions"]:
            lines.append(f"  - {a}")
        lines.append("")

    # Justification path
    lines.append("JUSTIFICATION PATH")
    lines.append("-" * 30)
    lines.append("  " + " -> ".join(record["justification_path"]))
    lines.append("")

    # Key finding for reviewer
    lines.append("REVIEWER KEY FINDING")
    lines.append("-" * 30)
    root_count = indep.get("independent_root_count", 0)
    ev_count = indep.get("evidence_count", 0)
    if root_count <= 1 and ev_count > 1:
        lines.append(
            f"ALL {ev_count} supporting statements derive from "
            f"a single provenance root. "
            f"Opening root ID(s): {', '.join(sorted(root_sets.values())[0] if root_sets else [])}"
        )
    elif root_count >= ev_count:
        lines.append(
            f"Each of the {ev_count} supporting statements traces to "
            f"an independent provenance root ({root_count} distinct roots). "
            f"Evidence roots are structurally independent."
        )
    else:
        lines.append(
            f"{ev_count} statements, {root_count} roots. "
            f"Some statements share provenance — partial independence."
        )
    lines.append("")

    return "\n".join(lines)
