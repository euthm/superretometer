# FILE: cognitive-harness/analysis/simulation_gate_policy.py
"""SimulationGatePolicy v0.6 — Four-gate evaluation for simulation-bearing claims.

Evaluates four gates: Provenance, Scope, Reality, Falsifiability.
All four must PASS for a simulation-backed claim to be design-bearing.

BLOCK is NOT "simulation failed." It is an epistemic judgment about the warrant chain.
"""
from __future__ import annotations
import json
import logging
from cognitive_harness.model.ko import (
    KnowledgeObject, GateStatus, GateResult, ScopeDeclaration,
    SimulationProvenance, FrozenBaseline, SimulationGateReport,
    TruthCategory, WarrantStatus, AntiPattern, AntiPatternDiagnosis,
)
from cognitive_harness.storage.interface import StorageInterface
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer

log = logging.getLogger(__name__)


class SimulationGatePolicy:
    """Evaluates the four gates for a simulation-bearing claim."""

    def __init__(self, storage: StorageInterface):
        self.storage = storage
        self.warrant_analyzer = WarrantAnalyzer(storage)

    # ── Public API ─────────────────────────────────────────────────────

    def evaluate_gates(self, claim_ko_id: str) -> SimulationGateReport:
        report = SimulationGateReport(claim_ko_id=claim_ko_id)
        report.provenance = self._gate_provenance(claim_ko_id)
        report.scope = self._gate_scope(claim_ko_id)
        report.reality = self._gate_reality(claim_ko_id)
        report.falsifiability = self._gate_falsifiability(claim_ko_id)
        report.design_bearing = report.all_pass()
        return report

    def create_frozen_baseline(
        self,
        claim_ko_id: str,
        model_id: str,
        source_commit: str,
        parameter_set_id: str,
        run_command: str,
        result_artifact: str,
        result_sha256: str,
    ) -> FrozenBaseline:
        gate_report = self.evaluate_gates(claim_ko_id)
        baseline = FrozenBaseline(
            model_id=model_id,
            source_commit=source_commit,
            parameter_set_id=parameter_set_id,
            run_command=run_command,
            result_artifact=result_artifact,
            result_sha256=result_sha256,
            gate_report=json.dumps(gate_report.to_dict()),
            allowed_claims=(
                ["all"] if gate_report.all_pass()
                else ["informative_only"]
            ),
        )
        baseline.immutable = True
        return baseline

    def verify_baseline_integrity(self, baseline: FrozenBaseline) -> bool:
        if not baseline.immutable:
            return False
        try:
            jr = json.loads(baseline.gate_report)
            return "claim_ko_id" in jr
        except (json.JSONDecodeError, TypeError):
            return False

    # ── Gate 1: Provenance ─────────────────────────────────────────────

    def _gate_provenance(self, claim_ko_id: str) -> GateResult:
        ko = self.storage.get_ko(claim_ko_id)
        if ko is None:
            return GateResult("provenance", GateStatus.BLOCK, "Claim KO not found.")

        prov = self._get_simulation_provenance(ko)
        if prov is None:
            return GateResult(
                "provenance", GateStatus.BLOCK,
                "No simulation provenance attached. "
                "Cannot trace result to source commit.",
            )

        missing = []
        for attr in ("result_artifact", "result_sha256", "run_id",
                      "model_id", "source_path", "source_commit"):
            if not getattr(prov, attr, ""):
                missing.append(attr)

        if missing:
            return GateResult(
                "provenance", GateStatus.BLOCK,
                f"Provenance chain incomplete. Missing: {', '.join(missing)}.",
            )

        broken_links = []
        for ref_id, label in [
            (prov.run_id, "run record"),
            (prov.model_id, "model"),
            (prov.parameter_set_id, "parameter set"),
        ]:
            if ref_id and not self.storage.get_ko(ref_id):
                broken_links.append(f"{label} ({ref_id})")

        if broken_links:
            return GateResult(
                "provenance", GateStatus.BLOCK,
                f"Broken provenance links: {', '.join(broken_links)}.",
            )

        return GateResult(
            "provenance", GateStatus.PASS,
            "Complete provenance chain traceable to source commit.",
            evidence=[prov.result_sha256, prov.source_commit],
        )

    # ── Gate 2: Scope ──────────────────────────────────────────────────

    def _gate_scope(self, claim_ko_id: str) -> GateResult:
        ko = self.storage.get_ko(claim_ko_id)
        if ko is None:
            return GateResult("scope", GateStatus.BLOCK, "Claim KO not found.")

        scope_decl = self._get_scope_declaration(ko)
        if scope_decl is None or not scope_decl.system_boundary:
            return GateResult(
                "scope", GateStatus.BLOCK,
                "No scope declaration. Cannot verify claim is within model scope.",
            )

        claim_scope = ko.scope
        if claim_scope and not self._scope_compatible(claim_scope, scope_decl):
            return GateResult(
                "scope", GateStatus.BLOCK,
                f"Claim scope '{claim_scope}' exceeds model scope "
                f"'{scope_decl.system_boundary}'.",
            )

        if scope_decl.disallowed_claim_classes:
            claim_type = ko.type.value if hasattr(ko.type, 'value') else str(ko.type)
            if claim_type in scope_decl.disallowed_claim_classes:
                return GateResult(
                    "scope", GateStatus.BLOCK,
                    f"Claim type '{claim_type}' is disallowed by model scope.",
                )

        return GateResult(
            "scope", GateStatus.PASS,
            f"Claim within declared scope: {scope_decl.system_boundary}",
            evidence=[scope_decl.system_boundary],
        )

    @staticmethod
    def _scope_compatible(claim_scope: str, scope_decl: ScopeDeclaration) -> bool:
        if not claim_scope or not scope_decl.system_boundary:
            return False
        # Exact match
        if claim_scope == scope_decl.system_boundary:
            return True
        # Claim scope is contained within system boundary (claim is narrower)
        if claim_scope in scope_decl.system_boundary:
            return True
        # Exclusion check FIRST: if claim mentions excluded components, BLOCK
        for excl in scope_decl.excluded_components:
            if excl in claim_scope:
                return False
        # System boundary contained in claim scope (claim is broader) — BLOCK
        # unless the claim scope is essentially the same domain
        # Do NOT allow scope_decl.system_boundary in claim_scope as a PASS,
        # because that means the claim exceeds the model boundary.
        # Check included components with strict matching
        for comp in scope_decl.included_components:
            if claim_scope == comp:
                return True
        # Modeled domain: exact match only, not substring
        if scope_decl.modeled_domain and scope_decl.modeled_domain == claim_scope:
            return True
        return False

    # ── Gate 3: Reality ────────────────────────────────────────────────

    def _gate_reality(self, claim_ko_id: str) -> GateResult:
        warrant = self.warrant_analyzer.compute_warrant(claim_ko_id)

        if warrant.warrant_status == WarrantStatus.WARRANTED:
            return GateResult(
                "reality", GateStatus.PASS,
                "All carrying quantities independently grounded.",
            )
        if warrant.warrant_status == WarrantStatus.CONDITIONALLY_WARRANTED:
            conditions = warrant.conditional_assumptions
            return GateResult(
                "reality", GateStatus.UNKNOWN,
                f"Explicitly assumed, not independently grounded: {conditions}",
                evidence=[str(c) for c in conditions],
            )
        if warrant.warrant_status == WarrantStatus.UNWARRANTED:
            anti = [d.pattern.value for d in warrant.anti_pattern_diagnoses]
            return GateResult(
                "reality", GateStatus.BLOCK,
                f"Structural defects in grounding: {anti}",
                evidence=[str(d.violated_condition) for d in warrant.anti_pattern_diagnoses],
            )
        return GateResult(
            "reality", GateStatus.UNKNOWN,
            "Insufficient graph information for warrant evaluation.",
        )

    # ── Gate 4: Falsifiability ─────────────────────────────────────────

    def _gate_falsifiability(self, claim_ko_id: str) -> GateResult:
        ko = self.storage.get_ko(claim_ko_id)
        if ko is None:
            return GateResult("falsifiability", GateStatus.BLOCK, "Claim KO not found.")

        # Check: does the KO have falsifiable validators?
        has_falsifiable = False
        for v in ko.validators:
            if v.what_would_falsify:
                has_falsifiable = True
                break

        if not has_falsifiable:
            # Check justification path for validators
            path, _cycles = self.warrant_analyzer._collect_justification_path(claim_ko_id)
            for pid in path:
                pko = self.storage.get_ko(pid)
                if pko:
                    for v in pko.validators:
                        if v.what_would_falsify:
                            has_falsifiable = True
                            break
                if has_falsifiable:
                    break

        if not has_falsifiable:
            return GateResult(
                "falsifiability", GateStatus.BLOCK,
                "No falsifiable validators declared. "
                "A check that cannot fail cannot increase epistemic confidence.",
            )

        # Check invariant validity against system boundary
        scope_decl = self._get_scope_declaration(ko)
        if scope_decl and scope_decl.system_boundary:
            invariant_issues = self._check_invariant_validity(ko, scope_decl)
            if invariant_issues:
                return GateResult(
                    "falsifiability", GateStatus.BLOCK,
                    f"Invalid invariant for system boundary: {invariant_issues}",
                    evidence=[invariant_issues],
                )

        return GateResult(
            "falsifiability", GateStatus.PASS,
            "Falsifiable validators declared. Invariants valid for system boundary.",
        )

    def _check_invariant_validity(
        self, ko: KnowledgeObject, scope_decl: ScopeDeclaration,
    ) -> str | None:
        """Check if invariants attached to this KO are valid for the system boundary.

        Returns an issue string if an invariant is invalid, None if all valid.
        """
        # Check if the KO itself declares invariant validity
        if isinstance(ko.content, dict) and ko.content.get("invariant_valid_for_boundary") is False:
            return (
                f"KO declares invariant invalid for system boundary "
                f"'{scope_decl.system_boundary}'"
            )

        # Check validators that reference invariants
        for v in ko.validators:
            desc_lower = v.description.lower()
            falsify_lower = v.what_would_falsify.lower()
            invariant_keywords = ("invariant", "balance", "conservation", "mass balance",
                                   "energy balance", "carbon balance", "cin", "cout")
            if any(kw in desc_lower or kw in falsify_lower for kw in invariant_keywords):
                if isinstance(ko.content, dict) and ko.content.get("invariant_valid_for_boundary") is False:
                    return (
                        f"Validator '{v.description}' references an invariant "
                        f"that is not valid for system boundary '{scope_decl.system_boundary}'"
                    )

        # Check upstream KOs for invariant validity
        if ko.derivation and ko.derivation.upstream_ko_ids:
            for up_id in ko.derivation.upstream_ko_ids:
                up_ko = self.storage.get_ko(up_id)
                if up_ko and isinstance(up_ko.content, dict):
                    if up_ko.content.get("invariant_valid_for_boundary") is False:
                        return (
                            f"Upstream KO {up_id} ({up_ko.title}) declares "
                            f"invariant invalid for boundary '{scope_decl.system_boundary}'"
                        )

        return None

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _get_simulation_provenance(ko: KnowledgeObject) -> SimulationProvenance | None:
        """Extract SimulationProvenance from KO content or attached data."""
        if isinstance(ko.content, dict) and "simulation_provenance" in ko.content:
            d = ko.content["simulation_provenance"]
            return SimulationProvenance(
                result_artifact=d.get("result_artifact", ""),
                result_sha256=d.get("result_sha256", ""),
                run_id=d.get("run_id", ""),
                parameter_set_id=d.get("parameter_set_id", ""),
                build_artifact=d.get("build_artifact", ""),
                model_id=d.get("model_id", ""),
                source_path=d.get("source_path", ""),
                source_commit=d.get("source_commit", ""),
                source_version=d.get("source_version", ""),
            )
        return None

    @staticmethod
    def _get_scope_declaration(ko: KnowledgeObject) -> ScopeDeclaration | None:
        """Extract ScopeDeclaration from KO content or attached data."""
        if isinstance(ko.content, dict) and "scope_declaration" in ko.content:
            d = ko.content["scope_declaration"]
            return ScopeDeclaration(
                modeled_domain=d.get("modeled_domain", ""),
                modeled_extent=d.get("modeled_extent", ""),
                included_components=d.get("included_components", []),
                excluded_components=d.get("excluded_components", []),
                system_boundary=d.get("system_boundary", ""),
                allowed_claim_classes=d.get("allowed_claim_classes", []),
                disallowed_claim_classes=d.get("disallowed_claim_classes", []),
            )
        return None
