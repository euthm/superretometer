# FILE: cognitive-harness/analysis/implementation_gate_policy.py
"""ImplementationGatePolicy — N-PROV for code implementation claims.

Mirrors SimulationGatePolicy for claims about implemented code:
  claim → commit → remote (MUST match scope-declared remote) → test run.

Remote mismatch = BLOCK. The remote URL in the ImplementationProvenance
must match the remote declared in the claim's scope or a scope-declared
allowlist.

Normative rule (N-IMPL-PROV):
  An "implemented" claim is informative only unless the commit's remote
  matches a scope-declared remote and a test run exists with passing result.
"""
from __future__ import annotations
import logging
from cognitive_harness.model.ko import (
    KnowledgeObject, GateStatus, GateResult, ScopeDeclaration,
    ImplementationProvenance,
)
from cognitive_harness.storage.interface import StorageInterface

log = logging.getLogger(__name__)


class ImplementationGatePolicy:
    """Evaluates implementation provenance for code-bearing claims."""

    def __init__(self, storage: StorageInterface):
        self.storage = storage

    # ── Public API ─────────────────────────────────────────────────────

    def evaluate_gates(self, claim_ko_id: str) -> dict:
        """Return an ImplementationGateReport as dict.

        Gates:
          provenance  — commit chain present and complete
          scope       — remote matches scope-declared remote
          test        — test run exists with passing result
        """
        ko = self.storage.get_ko(claim_ko_id)
        if ko is None:
            return _report(
                claim_ko_id,
                provenance=_gate("provenance", GateStatus.BLOCK, "Claim KO not found."),
                scope=_gate("scope", GateStatus.BLOCK, "Claim KO not found."),
                test=_gate("test", GateStatus.BLOCK, "Claim KO not found."),
            )

        impl_prov = self._get_implementation_provenance(ko)

        provenance = self._gate_provenance(ko, impl_prov)
        scope = self._gate_scope(ko, impl_prov)
        test = self._gate_test(ko, impl_prov)

        result = _report(claim_ko_id, provenance, scope, test)
        result["design_bearing"] = all(
            r["status"] == "pass" for r in [provenance, scope, test]
        )
        return result

    # ── Gate 1: Provenance ─────────────────────────────────────────────
    # N-IMPL-PROV: claim → commit → remote must be traceable.

    def _gate_provenance(
        self, ko: KnowledgeObject, prov: ImplementationProvenance | None,
    ) -> dict:
        if prov is None:
            return _gate(
                "provenance", GateStatus.BLOCK,
                "No implementation provenance attached. "
                "Cannot trace claim to commit.",
            )

        missing = []
        for attr in ("repo_remote", "repo_path", "branch", "commit"):
            if not getattr(prov, attr, ""):
                missing.append(attr)

        if missing:
            return _gate(
                "provenance", GateStatus.BLOCK,
                f"Provenance chain incomplete. Missing: {', '.join(missing)}.",
            )

        return _gate(
            "provenance", GateStatus.PASS,
            f"Complete provenance chain: {prov.repo_remote} @{prov.commit}",
            evidence=[prov.commit, prov.repo_remote],
        )

    # ── Gate 2: Scope ─────────────────────────────────────────────────
    # N-IMPL-SCOPE: remote MUST match scope-declared remote.

    def _gate_scope(
        self, ko: KnowledgeObject, prov: ImplementationProvenance | None,
    ) -> dict:
        if prov is None:
            return _gate(
                "scope", GateStatus.BLOCK,
                "No implementation provenance to check scope against.",
            )

        scope_decl = self._get_scope_declaration(ko)
        # Gather allowed remotes from scope — try multiple sources
        allowed_remotes = self._extract_allowed_remotes(ko, scope_decl)
        if not allowed_remotes:
            return _gate(
                "scope", GateStatus.UNKNOWN,
                "No remotes declared in scope. Cannot evaluate remote match.",
            )

        prov_remote = prov.repo_remote
        if not prov_remote:
            return _gate(
                "scope", GateStatus.BLOCK,
                "Provenance has no repo_remote. Cannot match against scope.",
            )

        # Normalize and compare
        if not self._remote_matches(prov_remote, allowed_remotes):
            return _gate(
                "scope", GateStatus.BLOCK,
                f"Remote mismatch: provenance remote '{prov_remote}' "
                f"not in scope-declared remotes: {allowed_remotes}. "
                "Implementation claim cannot be design-bearing.",
            )

        return _gate(
            "scope", GateStatus.PASS,
            f"Provenance remote '{prov_remote}' matches scope-declared remote.",
            evidence=[prov_remote],
        )

    # ── Gate 3: Test ──────────────────────────────────────────────────
    # N-IMPL-TEST: a test run must exist with a passing result.

    def _gate_test(
        self, ko: KnowledgeObject, prov: ImplementationProvenance | None,
    ) -> dict:
        if prov is None:
            return _gate(
                "test", GateStatus.BLOCK,
                "No implementation provenance to verify test.",
            )

        if not prov.test_run_id:
            return _gate(
                "test", GateStatus.BLOCK,
                "No test_run_id in implementation provenance. "
                "Cannot verify implementation passes tests.",
            )

        if prov.test_run_id and not self.storage.get_ko(prov.test_run_id):
            return _gate(
                "test", GateStatus.BLOCK,
                f"Test run KO '{prov.test_run_id}' not found in graph.",
            )

        if prov.test_result_sha256:
            return _gate(
                "test", GateStatus.PASS,
                f"Test run {prov.test_run_id} with result SHA256 {prov.test_result_sha256[:16]}…",
                evidence=[prov.test_run_id, prov.test_result_sha256],
            )

        return _gate(
            "test", GateStatus.UNKNOWN,
            f"Test run {prov.test_run_id} exists but has no result SHA256.",
        )

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _get_implementation_provenance(
        ko: KnowledgeObject,
    ) -> ImplementationProvenance | None:
        """Extract ImplementationProvenance from KO content."""
        if isinstance(ko.content, dict) and "implementation_provenance" in ko.content:
            d = ko.content["implementation_provenance"]
            sp = d.get("submodule_pins", {})
            return ImplementationProvenance(
                repo_remote=d.get("repo_remote", ""),
                repo_path=d.get("repo_path", ""),
                branch=d.get("branch", ""),
                commit=d.get("commit", ""),
                submodule_pins={k: v for k, v in sp.items()},
                test_run_id=d.get("test_run_id", ""),
                test_result_sha256=d.get("test_result_sha256", ""),
                session_id=d.get("session_id", ""),
                epf_ready_id=d.get("epf_ready_id", ""),
            )
        return None

    @staticmethod
    def _get_scope_declaration(ko: KnowledgeObject) -> ScopeDeclaration | None:
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

    @staticmethod
    def _extract_allowed_remotes(
        ko: KnowledgeObject, scope_decl: ScopeDeclaration | None,
    ) -> list[str]:
        """Extract allowed remotes from scope declaration.

        Sources:
          1. scope_declaration.allowed_claim_classes containing remote URLs
          2. included_components containing remote URLs (git@ or https://)
          3. scope string itself if it contains a remote URL
          4. content.declared_remotes (explicit field)
        """
        remotes = []

        # Explicit declared_remotes field in content
        if isinstance(ko.content, dict):
            declared = ko.content.get("declared_remotes", [])
            if isinstance(declared, list):
                remotes.extend(declared)

        # included_components may contain remote URLs
        if scope_decl:
            for comp in scope_decl.included_components:
                if comp.startswith(("git@", "https://", "git://")):
                    remotes.append(comp)

        # scope string may be a remote URL
        if ko.scope and ko.scope.startswith(("git@", "https://", "git://")):
            remotes.append(ko.scope)

        return remotes

    @staticmethod
    def _remote_matches(prov_remote: str, allowed: list[str]) -> bool:
        """Check if prov_remote matches any allowed remote (with normalization)."""
        normalized_prov = ImplementationGatePolicy._normalize_remote(prov_remote)
        for a in allowed:
            if normalized_prov == ImplementationGatePolicy._normalize_remote(a):
                return True
        return False

    @staticmethod
    def _normalize_remote(remote: str) -> str:
        """Normalize remote URL for comparison.
        git@github.com:user/repo.git → https://github.com/user/repo.git
        Strips trailing .git for comparison.
        """
        r = remote.strip()
        if r.startswith("git@"):
            r = r.replace(":", "/", 1).replace("git@", "https://", 1)
        if r.endswith(".git"):
            r = r[:-4]
        return r.rstrip("/")


def _gate(name: str, status: GateStatus, reason: str, evidence: list[str] | None = None) -> dict:
    return {
        "gate": name,
        "status": status.value,
        "reason": reason,
        "evidence": evidence or [],
    }


def _report(claim_ko_id: str, provenance: dict, scope: dict, test: dict) -> dict:
    return {
        "claim_ko_id": claim_ko_id,
        "provenance": provenance,
        "scope": scope,
        "test": test,
        "design_bearing": all(r["status"] == "pass" for r in [provenance, scope, test]),
    }
