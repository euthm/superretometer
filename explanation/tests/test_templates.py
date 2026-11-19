# FILE: explanation/tests/test_templates.py
"""Test deterministic explanation templates against 5 CH report scenarios."""
from __future__ import annotations
from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus,
    ConfidenceLevel, WarrantStatus, SimulationGateReport,
    GateResult, GateStatus, AntiPatternDiagnosis, AntiPattern,
    Provenance, DerivationRelation, DerivationType,
)
from explanation.templates import (
    ExplanationInput, executive_explanation,
    engineering_explanation, audit_explanation, generate_all,
)


def _make_claim(title: str, status: EpistemicStatus = EpistemicStatus.PROPOSED,
                conf: ConfidenceLevel = ConfidenceLevel.SPECULATIVE) -> KnowledgeObject:
    return KnowledgeObject(
        id=f"test-{title.lower().replace(' ', '-')}",
        type=KOType.FINDING,
        title=title,
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=status,
        confidence=conf,
    )


def _make_gate_report(all_pass: bool = False,
                      any_block: bool = False,
                      any_unknown: bool = False) -> SimulationGateReport:
    if all_pass:
        status = GateStatus.PASS
    elif any_block:
        status = GateStatus.BLOCK
    elif any_unknown:
        status = GateStatus.UNKNOWN
    else:
        status = GateStatus.UNKNOWN
    return SimulationGateReport(
        claim_ko_id="test-claim",
        provenance=GateResult("provenance", status, "test reason"),
        scope=GateResult("scope", status, "test reason"),
        reality=GateResult("reality", status, "test reason"),
        falsifiability=GateResult("falsifiability", status, "test reason"),
    )


class TestWarrantedClaim:
    """Case 1: CP-010 style — all gates pass, evidence grounded."""

    def setup_method(self):
        self.claim = _make_claim("Connector liveness verified",
                                  EpistemicStatus.VALIDATED, ConfidenceLevel.HIGH)
        self.claim.provenance = Provenance(source="rocom-standard", author="test")
        self.gates = _make_gate_report(all_pass=True)
        self.evidence = [
            {"id": "ev-spec", "claim_id": self.claim.id, "status": "supports",
             "observation": "cp-registry.md committed", "records": []},
            {"id": "ev-impl", "claim_id": self.claim.id, "status": "supports",
             "observation": "topics.rs blob d3f36f35", "records": []},
            {"id": "ev-test", "claim_id": self.claim.id, "status": "supports",
             "observation": "cargo test 32/32 pass", "records": []},
        ]
        self.inp = ExplanationInput(
            claim=self.claim, gate_report=self.gates, evidence_items=self.evidence,
        )

    def test_executive_contains_warrant(self):
        out = executive_explanation(self.inp)
        assert "Connector liveness verified" in out
        assert "3 item(s)" in out

    def test_all_gates_pass(self):
        out = executive_explanation(self.inp)
        assert "PASS" in out

    def test_audit_no_anti_patterns(self):
        out = audit_explanation(self.inp)
        assert "ANTI-PATTERN AUDIT" not in out


class TestUnwarrantedClaim:
    """Case 2: Unwarranted claim — evidence exists but no independent verification."""

    def setup_method(self):
        self.claim = _make_claim("Thermal model accurate to 1K",
                                  EpistemicStatus.TENTATIVE, ConfidenceLevel.LOW)
        self.gates = _make_gate_report(any_unknown=True)
        self.evidence = [
            {"id": "ev-sim", "claim_id": self.claim.id, "status": "supports",
             "observation": "Simulation output matches target", "records": []},
        ]
        self.inp = ExplanationInput(
            claim=self.claim, gate_report=self.gates, evidence_items=self.evidence,
        )

    def test_shows_unwarranted(self):
        out = executive_explanation(self.inp)
        assert "1 item(s)" in out

    def test_audit_shows_incomplete_gates(self):
        out = audit_explanation(self.inp)
        assert "INCOMPLETE" in out


class TestContradictoryEvidence:
    """Case 3: Evidence items with contradicting status."""

    def setup_method(self):
        self.claim = _make_claim("Parameter range validated")
        self.evidence = [
            {"id": "ev-support", "claim_id": self.claim.id, "status": "supports",
             "observation": "Test suite passes within range", "records": []},
            {"id": "ev-contradict", "claim_id": self.claim.id, "status": "contradicts",
             "observation": "Edge case fails at boundary", "records": []},
        ]
        self.inp = ExplanationInput(
            claim=self.claim, evidence_items=self.evidence,
        )

    def test_audit_identifies_contradiction(self):
        out = audit_explanation(self.inp)
        assert "CONTRADICTION EVIDENCE" in out
        assert "contradicts" in out

    def test_executive_shows_both(self):
        out = executive_explanation(self.inp)
        assert "2 item(s)" in out


class TestSharedEvidenceRoots:
    """Case 4: Evidence items sharing the same provenance root."""

    def setup_method(self):
        self.claim = _make_claim("System throughput meets spec")
        self.evidence = [
            {"id": "ev-bench1", "claim_id": self.claim.id, "status": "supports",
             "observation": "Benchmark A: 10k ops/s", "records": []},
            {"id": "ev-bench2", "claim_id": self.claim.id, "status": "supports",
             "observation": "Benchmark A: 10k ops/s", "records": []},
            {"id": "ev-bench3", "claim_id": self.claim.id, "status": "supports",
             "observation": "Benchmark B: 12k ops/s", "records": []},
        ]
        self.inp = ExplanationInput(
            claim=self.claim, evidence_items=self.evidence,
        )

    def test_independence_warning(self):
        out = audit_explanation(self.inp)
        assert "WARNING" in out
        assert "may not be independent" in out


class TestMissingProvenance:
    """Case 5: Claim with no provenance record."""

    def setup_method(self):
        self.claim = _make_claim("Design decision D-001")
        self.claim.provenance = None
        self.inp = ExplanationInput(claim=self.claim, evidence_items=[])

    def test_audit_notes_missing_provenance(self):
        out = audit_explanation(self.inp)
        assert "PROVENANCE CHAIN" not in out

    def test_executive_still_produces(self):
        out = executive_explanation(self.inp)
        assert "Design decision D-001" in out


class TestGenerateAll:
    """Integration: generate_all produces all three types."""

    def test_returns_three_keys(self):
        claim = _make_claim("Integration test")
        inp = ExplanationInput(claim=claim)
        result = generate_all(inp)
        assert set(result.keys()) == {"executive", "engineering", "audit"}

    def test_all_deterministic(self):
        claim = _make_claim("Determinism check")
        inp = ExplanationInput(claim=claim)
        ts = "2026-01-01T00:00:00+00:00"
        r1 = generate_all(inp, timestamp=ts)
        r2 = generate_all(inp, timestamp=ts)
        assert r1 == r2
