# FILE: explanation/templates.py
"""Deterministic explanation templates for frozen CH reports.

Produces executive, engineering, and audit explanations from CH gate reports
and warrant analysis results. No LLM calls — pure Jinja2 templating over
structured data. Guaranteed factual fidelity: every statement traces to a
field in the input data.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, WarrantStatus, GateStatus,
    SimulationGateReport, AntiPattern, AntiPatternDiagnosis,
)


@dataclass
class ExplanationInput:
    """Frozen CH report data for explanation generation."""
    claim: KnowledgeObject
    gate_report: SimulationGateReport | None = None
    evidence_items: list[dict] = field(default_factory=list)
    anti_patterns: list[AntiPatternDiagnosis] = field(default_factory=list)
    tensions: list[KnowledgeObject] = field(default_factory=list)
    upstream_kos: list[KnowledgeObject] = field(default_factory=list)


def _fmt_status(s: str) -> str:
    return s.upper().replace("_", " ")


def _fmt_warrant(ws: WarrantStatus) -> str:
    return ws.value.upper().replace("_", " ")


def _evidence_summary(ev: dict) -> str:
    parts = [f"[{ev.get('id', '?')}]"]
    if ev.get("status"):
        parts.append(f"status={ev['status']}")
    if ev.get("observation"):
        obs = ev["observation"]
        parts.append(f"observation=\"{obs[:80]}{'...' if len(obs) > 80 else ''}\"")
    return " ".join(parts)


def executive_explanation(inp: ExplanationInput) -> str:
    """One-page executive summary of a claim's warrant status."""
    lines = [
        f"CLAIM: {inp.claim.title}",
        f"  ID: {inp.claim.id}",
        f"  Warrant: {_fmt_warrant(inp.claim.epistemic_status if hasattr(inp.claim, 'epistemic_status') else inp.claim.epistemic_status)}",
        f"  Type: {inp.claim.type.value}",
        f"  Status: {_fmt_status(inp.claim.epistemic_status.value)}",
        "",
    ]

    if inp.gate_report:
        gr = inp.gate_report
        lines.append("GATE EVALUATION:")
        for gate_name, gate in [
            ("Provenance", gr.provenance),
            ("Scope", gr.scope),
            ("Reality", gr.reality),
            ("Falsifiability", gr.falsifiability),
        ]:
            status_icon = "PASS" if gate.status == GateStatus.PASS else "BLOCK" if gate.status == GateStatus.BLOCK else "???"
            lines.append(f"  {gate_name}: {status_icon} — {gate.reason}")
        lines.append("")

    lines.append(f"EVIDENCE: {len(inp.evidence_items)} item(s)")
    for ev in inp.evidence_items:
        lines.append(f"  {_evidence_summary(ev)}")
    lines.append("")

    if inp.anti_patterns:
        lines.append("ANTI-PATTERNS:")
        for ap in inp.anti_patterns:
            lines.append(f"  {ap.pattern.value}: {ap.violated_condition}")
            if ap.resolution_hint:
                lines.append(f"    Resolution: {ap.resolution_hint}")
        lines.append("")

    if inp.tensions:
        lines.append(f"TENSIONS: {len(inp.tensions)} open")
        for t in inp.tensions:
            lines.append(f"  - {t.title}")
        lines.append("")

    return "\n".join(lines)


def engineering_explanation(inp: ExplanationInput) -> str:
    """Technical detail: derivation chain, evidence provenance, gate mechanics."""
    lines = [
        "ENGINEERING EXPLANATION",
        f"Claim: {inp.claim.id} — {inp.claim.title}",
        f"Truth category: {inp.claim.truth_category.value}",
        f"Epistemic status: {inp.claim.epistemic_status.value}",
        f"Confidence: {inp.claim.confidence.value}",
        "",
    ]

    if inp.claim.derivation:
        d = inp.claim.derivation
        lines.append(f"Derivation: {d.derivation_type.value}")
        if d.upstream_ko_ids:
            lines.append(f"  Upstream KOs: {', '.join(d.upstream_ko_ids)}")
        if d.training_dataset_id:
            lines.append(f"  Training dataset: {d.training_dataset_id}")
        if d.test_dataset_id:
            lines.append(f"  Test dataset: {d.test_dataset_id}")
        lines.append("")

    lines.append("EVIDENCE PROVENANCE:")
    for ev in inp.evidence_items:
        lines.append(f"  [{ev.get('id', '?')}]")
        lines.append(f"    claim_id: {ev.get('claim_id', '(none)')}")
        lines.append(f"    status: {ev.get('status', '(none)')}")
        if ev.get("records"):
            for rec in ev["records"]:
                rec_str = json.dumps(rec) if isinstance(rec, dict) else str(rec)
                lines.append(f"    record: {rec_str}")
    lines.append("")

    if inp.gate_report:
        gr = inp.gate_report
        lines.append("GATE MECHANICS:")
        for gate_name, gate in [
            ("Provenance", gr.provenance),
            ("Scope", gr.scope),
            ("Reality", gr.reality),
            ("Falsifiability", gr.falsifiability),
        ]:
            lines.append(f"  {gate_name}:")
            lines.append(f"    Status: {gate.status.value}")
            lines.append(f"    Reason: {gate.reason}")
            if gate.evidence:
                lines.append(f"    Evidence refs: {', '.join(gate.evidence)}")
        lines.append("")

    if inp.upstream_kos:
        lines.append("UPSTREAM DEPENDENCIES:")
        for u in inp.upstream_kos:
            lines.append(f"  {u.id} ({u.type.value}): {u.title} — status={u.epistemic_status.value}")
        lines.append("")

    return "\n".join(lines)


def audit_explanation(inp: ExplanationInput, timestamp: str | None = None) -> str:
    """Audit trail: provenance chain, independence analysis, warrant basis."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()
    lines = [
        "AUDIT EXPLANATION",
        f"Generated: {timestamp}",
        f"Claim: {inp.claim.id}",
        f"Warrant basis: {len(inp.evidence_items)} evidence, {len(inp.anti_patterns)} anti-pattern(s), {len(inp.tensions)} tension(s)",
        "",
    ]

    # Provenance chain
    if inp.claim.provenance:
        p = inp.claim.provenance
        lines.append("PROVENANCE CHAIN:")
        lines.append(f"  Source: {p.source}")
        lines.append(f"  Author: {p.author}")
        lines.append(f"  Timestamp: {p.timestamp.isoformat()}")
        lines.append(f"  Revision: {p.revision}")
        if p.derived_from:
            lines.append(f"  Derived from: {p.derived_from}")
        if p.independent is not None:
            lines.append(f"  Independent: {p.independent}")
        lines.append("")

    # Independence analysis
    lines.append("INDEPENDENCE ANALYSIS:")
    evidence_sources = set()
    for ev in inp.evidence_items:
        src = ev.get("observation", "")[:50]
        evidence_sources.add(src)
    lines.append(f"  Distinct evidence observations: {len(evidence_sources)}")
    if len(evidence_sources) < len(inp.evidence_items):
        lines.append("  WARNING: Evidence items share observation text — may not be independent")
    lines.append("")

    # Anti-pattern audit
    if inp.anti_patterns:
        lines.append("ANTI-PATTERN AUDIT:")
        for ap in inp.anti_patterns:
            lines.append(f"  {ap.pattern.value}")
            lines.append(f"    Offending KOs: {', '.join(ap.offending_ko_ids)}")
            lines.append(f"    Justification path: {' → '.join(ap.justification_path)}")
            lines.append(f"    Shared roots: {', '.join(ap.shared_roots)}")
            lines.append(f"    Violated: {ap.violated_condition}")
        lines.append("")

    # Contradiction check
    contradictions = [ev for ev in inp.evidence_items if ev.get("status") == "contradicts"]
    if contradictions:
        lines.append("CONTRADICTION EVIDENCE:")
        for c in contradictions:
            lines.append(f"  {_evidence_summary(c)}")
        lines.append("")

    # Final assessment
    lines.append("FINAL ASSESSMENT:")
    lines.append(f"  Warrant: {_fmt_warrant(inp.claim.epistemic_status if hasattr(inp.claim, 'epistemic_status') else inp.claim.epistemic_status)}")
    has_blocks = inp.gate_report and inp.gate_report.any_block()
    has_unknowns = inp.gate_report and inp.gate_report.any_unknown()
    if has_blocks:
        lines.append("  Gates: BLOCKED — claim cannot be advanced")
    elif has_unknowns:
        lines.append("  Gates: INCOMPLETE — additional evidence required")
    elif inp.gate_report and inp.gate_report.all_pass():
        lines.append("  Gates: ALL PASS — warrant supported by gate evaluation")
    lines.append("")

    return "\n".join(lines)


def generate_all(inp: ExplanationInput, timestamp: str | None = None) -> dict[str, str]:
    """Generate all three explanation types from frozen CH report."""
    return {
        "executive": executive_explanation(inp),
        "engineering": engineering_explanation(inp),
        "audit": audit_explanation(inp, timestamp=timestamp),
    }
