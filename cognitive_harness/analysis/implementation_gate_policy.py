# FILE: cognitive-harness/analysis/implementation_gate_policy.py
"""ImplementationGatePolicy — N-PROV for code implementation claims.

Six gates for implementation-bearing claims:
  provenance → scope → worktree → test → falsifiability → dependency

Remote mismatch = BLOCK. The remote URL in the ImplementationProvenance
must match the remote declared in the claim's scope or a scope-declared
allowlist.

Normative rule (N-IMPL-PROV):
  An "implemented" claim is informative only unless the commit's remote
  matches a scope-declared remote, worktree state is reproducible,
  test evidence is complete, falsification criteria exist, and
  dependency state is intact.
"""
from __future__ import annotations
import logging
import re
from typing import Optional, Tuple
from cognitive_harness.model.ko import (
    KnowledgeObject, GateStatus, GateResult, ScopeDeclaration,
    ImplementationProvenance, FalsifiableValidator,
)
from cognitive_harness.storage.interface import StorageInterface

log = logging.getLogger(__name__)


# ── Canonical Remote Normalization ─────────────────────────────────────────

def canonical_remote(remote: str) -> str:
    """Normalize a Git remote URL to a canonical repository identity.

    Canonical form: hostname/owner/repo

    Normalizes transport syntax only — never invents repository identity.

    Examples:
        git@github.com:euthm/foo.git     -> github.com/euthm/foo
        https://github.com/euthm/foo.git -> github.com/euthm/foo
        ssh://git@github.com/euthm/foo   -> github.com/euthm/foo
        http://github.com/euthm/foo.git  -> github.com/euthm/foo
        git://github.com/euthm/foo       -> github.com/euthm/foo
        git@gitlab.example.com:grp/repo.git -> gitlab.example.com/grp/repo
        github.com/euthm/foo             -> github.com/euthm/foo (already canonical)
        GitHub.com/euthm/foo             -> github.com/euthm/foo (hostname lowercased)
        ssh://git@git.example.com:2222/group/repo.git -> git.example.com/group/repo

    Rules:
        - lowercase hostname
        - remove transport/user credentials
        - remove trailing .git
        - remove trailing slash
        - remove SSH port (transport metadata, not identity)
        - preserve repository owner/path case
        - never preserve credentials/tokens
        - unknown hosts pass through after transport removal
    """
    r = remote.strip()
    if not r:
        return ""

    # Strip trailing .git
    if r.endswith(".git"):
        r = r[:-4]

    # SCP-style: git@host:path (no :// present)
    scp_match = re.match(r'^[^@/]+@([^:]+):(.+)$', r)
    if scp_match and "://" not in r:
        host = scp_match.group(1).lower()
        path = scp_match.group(2)
        return f"{host}/{path}".rstrip("/")

    # URL-style protocols (handles ssh://host:port/path, https://host/path, etc.)
    url_match = re.match(r'^(?:https?|ssh|git)://(?:(?:[^@/]+)@)?([^/:]+)(?::\d+)?(/[^?#]+)?', r)
    if url_match:
        host = url_match.group(1).lower()
        path = url_match.group(2) or ""
        return f"{host}{path}".rstrip("/")

    # Already canonical or unrecognized: lowercase hostname portion
    # Canonical form is hostname/path — lowercase only the hostname (first segment)
    slash_pos = r.find("/")
    if slash_pos > 0:
        host = r[:slash_pos].lower()
        path = r[slash_pos:]
        return f"{host}{path}".rstrip("/")

    return r.lower().rstrip("/")


def normalize_remote(remote: str) -> str:
    """Backward-compatible alias: normalizes git@ -> https:// for string comparison.

    Deprecated in favor of canonical_remote(). Kept for backward compatibility
    with existing remote-matching logic.
    """
    r = remote.strip()
    if r.startswith("git@"):
        r = r.replace(":", "/", 1).replace("git@", "https://", 1)
    if r.endswith(".git"):
        r = r[:-4]
    return r.rstrip("/")


def sanitize_remote(remote: str) -> str:
    """Remove credentials/tokens from a remote URL for safe storage.

    repo_remote_sanitized stores the observed transport locator with secrets
    removed.  Never persist the raw credential-bearing URL.

    For https/http URLs, any user@ in the authority is a credential and must
    be stripped.  For ssh:// URLs, the user (e.g., git) is structural to the
    SSH protocol and is preserved.

    Examples:
        https://TOKEN@github.com/example/foo.git -> https://github.com/example/foo.git
        https://user:pass@github.com/example/foo.git -> https://github.com/example/foo.git
        git@github.com:euthm/foo.git -> git@github.com:euthm/foo.git (SCP, no tokens)
        ssh://git@git.example.com/path -> ssh://git@git.example.com/path (SSH user preserved)
    """
    r = remote.strip()
    if not r:
        return r

    # Strip user:password@ or user@ from https/http URL-style remotes
    # (For https/http, any auth component is a credential.)
    url_match = re.match(r'^(https?)://(?:[^@/]+)@(.+)$', r)
    if url_match:
        protocol = url_match.group(1)
        rest = url_match.group(2)
        return f"{protocol}://{rest}"

    # ssh:// and SCP-style: git@host:path or ssh://git@host/path — user is structural
    # Pass through unchanged
    return r


def _sanitize_submodule_pins(pins: dict) -> dict:
    """Sanitize submodule pins: strip credentials, normalize canonical remotes."""
    result = {}
    for name, pin in pins.items():
        if not isinstance(pin, dict):
            continue
        p = dict(pin)
        remote = p.get("remote", p.get("repo_remote_sanitized", ""))
        p["repo_remote_sanitized"] = sanitize_remote(remote)
        canon = p.get("repo_remote_canonical", "")
        if not canon and remote:
            canon = canonical_remote(remote)
        p["repo_remote_canonical"] = canon
        result[name] = p
    return result


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
          worktree    — code state is reproducibly identified
          test        — test evidence is complete and matches claim state
        """
        ko = self.storage.get_ko(claim_ko_id)
        if ko is None:
            return _report(
                claim_ko_id,
                provenance=_gate("provenance", GateStatus.BLOCK, "Claim KO not found."),
                scope=_gate("scope", GateStatus.BLOCK, "Claim KO not found."),
                worktree=_gate("worktree", GateStatus.BLOCK, "Claim KO not found."),
                test=_gate("test", GateStatus.BLOCK, "Claim KO not found."),
                falsifiability=_gate("falsifiability", GateStatus.BLOCK, "Claim KO not found."),
                dependency=_gate("dependency", GateStatus.BLOCK, "Claim KO not found."),
            )

        impl_prov = self._get_implementation_provenance(ko)

        provenance = self._gate_provenance(ko, impl_prov)
        scope = self._gate_scope(ko, impl_prov)
        worktree = self._gate_worktree(ko, impl_prov)
        test = self._gate_test(ko, impl_prov)
        falsifiability = self._gate_falsifiability(ko, impl_prov)
        dependency = self._gate_dependency(ko, impl_prov)

        result = _report(claim_ko_id, provenance, scope, worktree, test,
                         falsifiability, dependency)
        result["design_bearing"] = all(
            r["status"] == "pass" for r in [provenance, scope, worktree, test,
                                            falsifiability, dependency]
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
        for attr in ("repo_remote_canonical", "commit"):
            if not getattr(prov, attr, ""):
                missing.append(attr)

        if missing:
            return _gate(
                "provenance", GateStatus.BLOCK,
                f"Provenance chain incomplete. Missing: {', '.join(missing)}.",
            )

        canon = prov.repo_remote_canonical
        evidence = [prov.commit, canon]
        if prov.branch:
            evidence.append(f"branch: {prov.branch}")

        return _gate(
            "provenance", GateStatus.PASS,
            f"Complete provenance chain: {canon} @{prov.commit}",
            evidence=evidence,
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
        allowed_remotes = self._extract_allowed_remotes(ko, scope_decl)
        if not allowed_remotes:
            return _gate(
                "scope", GateStatus.UNKNOWN,
                "No remotes declared in scope. Cannot evaluate remote match.",
            )

        prov_canon = prov.repo_remote_canonical
        if not prov_canon:
            return _gate(
                "scope", GateStatus.BLOCK,
                "Provenance has no canonical remote. Cannot match against scope.",
            )

        if not self._remote_matches_canonical(prov_canon, allowed_remotes):
            return _gate(
                "scope", GateStatus.BLOCK,
                f"Remote mismatch: provenance canonical '{prov_canon}' "
                f"not in scope-declared remotes: {allowed_remotes}. "
                "Implementation claim cannot be design-bearing.",
            )

        return _gate(
            "scope", GateStatus.PASS,
            f"Provenance canonical remote '{prov_canon}' matches scope-declared remote.",
            evidence=[prov_canon],
        )

    # ── Gate 3: Worktree ────────────────────────────────────────────────
    # N-IMPL-WORKTREE: code state must be reproducibly identified.

    def _gate_worktree(
        self, ko: KnowledgeObject, prov: ImplementationProvenance | None,
    ) -> dict:
        if prov is None:
            return _gate(
                "worktree", GateStatus.BLOCK,
                "No implementation provenance to check worktree state.",
            )

        clean = prov.worktree_clean
        diff_hash = prov.worktree_diff_sha256

        # Clean = True: exact commit represents tested state
        if clean is True:
            return _gate(
                "worktree", GateStatus.PASS,
                f"Clean worktree: commit {prov.commit[:8]}… represents exact code state.",
                evidence=[prov.commit],
            )

        # Dirty with diff hash: state identified but not clean
        if clean is False and diff_hash:
            return _gate(
                "worktree", GateStatus.UNKNOWN,
                f"Dirty worktree with diff snapshot ({diff_hash[:8]}…). "
                "State is identified but not a clean commit — cannot PASS.",
            )

        # Dirty without diff hash: BLOCK
        if clean is False and not diff_hash:
            return _gate(
                "worktree", GateStatus.BLOCK,
                "Dirty worktree without diff hash. "
                "Tested code state cannot be reproducibly identified.",
            )

        # None/unobserved: UNKNOWN
        return _gate(
            "worktree", GateStatus.UNKNOWN,
            "Worktree state not observed. Cannot establish code-state reproducibility.",
        )

    # ── Gate 4: Test ────────────────────────────────────────────────────
    # N-IMPL-TEST: complete test evidence chain, validated against exact state.

    def _gate_test(
        self, ko: KnowledgeObject, prov: ImplementationProvenance | None,
    ) -> dict:
        if prov is None:
            return _gate(
                "test", GateStatus.BLOCK,
                "No implementation provenance to verify test.",
            )

        # ── Required evidence presence checks ──
        # validator_ko_id absent → UNKNOWN
        if not prov.validator_ko_id:
            return _gate(
                "test", GateStatus.UNKNOWN,
                "No validator_ko_id. No CH evidence KO linked to this claim.",
            )

        # test_run_id absent → UNKNOWN
        if not prov.test_run_id:
            return _gate(
                "test", GateStatus.UNKNOWN,
                "No test_run_id. External runner identity missing.",
            )

        # test_command absent → UNKNOWN
        if not prov.test_command:
            return _gate(
                "test", GateStatus.UNKNOWN,
                "No test_command. Test execution command not recorded.",
            )

        # test_result_sha256 absent → UNKNOWN
        if not prov.test_result_sha256:
            return _gate(
                "test", GateStatus.UNKNOWN,
                "No test_result_sha256. Test result artifact not captured.",
            )

        # ── validator KO resolution ──
        validator = self.storage.get_ko(prov.validator_ko_id)
        if not validator:
            return _gate(
                "test", GateStatus.UNKNOWN,
                f"validator_ko_id '{prov.validator_ko_id}' not found in graph. "
                "Evidence KO must exist.",
            )

        # ── Commit binding invariant ──
        if not prov.tested_commit:
            return _gate(
                "test", GateStatus.UNKNOWN,
                "No tested_commit. Cannot verify tests ran against claim commit.",
            )

        if prov.tested_commit != prov.commit:
            return _gate(
                "test", GateStatus.BLOCK,
                f"tested_commit '{prov.tested_commit[:8]}…' != claim commit "
                f"'{prov.commit[:8]}…'. Tests ran against different revision.",
            )

        # ── Worktree state binding ──
        if prov.worktree_clean is False:
            # Dirty: claim diff must match tested diff
            if not prov.tested_worktree_diff_sha256:
                return _gate(
                    "test", GateStatus.BLOCK,
                    "Dirty worktree but no tested_worktree_diff_sha256. "
                    "Cannot verify tests ran against same dirty state.",
                )
            if prov.tested_worktree_diff_sha256 != prov.worktree_diff_sha256:
                return _gate(
                    "test", GateStatus.BLOCK,
                    "tested_worktree_diff != claim worktree_diff. "
                    "Tests ran against different code state.",
                )

        # ── Exit code ──
        if prov.test_exit_code is None:
            return _gate(
                "test", GateStatus.UNKNOWN,
                "test_exit_code not recorded. Cannot determine pass/fail.",
            )

        if prov.test_exit_code != 0:
            return _gate(
                "test", GateStatus.BLOCK,
                f"test_exit_code={prov.test_exit_code}. Tests did not pass.",
            )

        # ── Timestamp ──
        if not prov.test_timestamp:
            return _gate(
                "test", GateStatus.UNKNOWN,
                "test_timestamp not recorded. Incomplete validation provenance.",
            )
        # Timezone-aware timestamp required for complete portable provenance
        if _is_complete_portable_timestamp(prov.test_timestamp):
            pass  # Good
        elif _is_any_timestamp(prov.test_timestamp):
            # Naive timestamp: valid format but not portable
            return _gate(
                "test", GateStatus.UNKNOWN,
                f"test_timestamp '{prov.test_timestamp}' lacks timezone offset. "
                "Not portable across machines — incomplete provenance.",
            )
        else:
            return _gate(
                "test", GateStatus.BLOCK,
                f"test_timestamp '{prov.test_timestamp}' is not valid ISO 8601.",
            )

        # All evidence present and consistent
        evidence = [
            prov.test_run_id,
            prov.validator_ko_id,
            prov.test_result_sha256[:16] + "…",
            f"exit_code: {prov.test_exit_code}",
        ]
        return _gate(
            "test", GateStatus.PASS,
            f"Complete test evidence: run {prov.test_run_id}, "
            f"command '{prov.test_command}', exit 0, "
            f"tested against {prov.tested_commit[:8]}…",
            evidence=evidence,
        )

    # ── Gate 5: Falsifiability ──────────────────────────────────────────
    # N-IMPL-FALSIFY: at least one validator must declare what would falsify.
    # Uses existing FalsifiableValidator model on the claim KO.

    def _gate_falsifiability(
        self, ko: KnowledgeObject, prov: ImplementationProvenance | None,
    ) -> dict:
        # No validators on the claim at all
        if not ko.validators:
            return _gate(
                "falsifiability", GateStatus.UNKNOWN,
                "No validators on claim. UNGROUNDED.",
            )

        # Check for at least one with non-empty what_would_falsify
        for v in ko.validators:
            if isinstance(v, FalsifiableValidator) and v.what_would_falsify:
                return _gate(
                    "falsifiability", GateStatus.PASS,
                    f"Falsifier declared: {v.what_would_falsify[:100]}",
                    evidence=[v.id],
                )

        # Validators exist but all have empty what_would_falsify
        return _gate(
            "falsifiability", GateStatus.UNKNOWN,
            "Validators exist but none declare what would falsify. "
            "Cannot establish falsifiability.",
        )

    # ── Gate 6: Dependency ──────────────────────────────────────────────
    # N-IMPL-DEPENDENCY: submodule/dependency state must be consistent
    # between claim and tested state.

    def _gate_dependency(
        self, ko: KnowledgeObject, prov: ImplementationProvenance | None,
    ) -> dict:
        if prov is None:
            return _gate("dependency", GateStatus.BLOCK, "No provenance.")

        claim_pins = prov.submodule_pins
        tested_pins = prov.tested_submodule_pins

        # No submodules → PASS
        if not claim_pins:
            return _gate(
                "dependency", GateStatus.PASS,
                "No submodules declared. Not applicable.",
            )

        # Claim has submodules but no tested evidence → UNKNOWN
        if not tested_pins:
            return _gate(
                "dependency", GateStatus.UNKNOWN,
                f"Claim declares {len(claim_pins)} submodule(s) but "
                "no tested_submodule_pins. Cannot verify dependency state.",
            )

        # Set of submodule names must match
        claim_names = set(claim_pins.keys())
        tested_names = set(tested_pins.keys())
        if claim_names != tested_names:
            missing = claim_names - tested_names
            extra = tested_names - claim_names
            details = []
            if missing:
                details.append(f"missing tested pins: {missing}")
            if extra:
                details.append(f"unexpected tested pins: {extra}")
            return _gate(
                "dependency", GateStatus.BLOCK,
                f"Submodule sets differ: {'; '.join(details)}.",
            )

        # Compare each pin
        for name in claim_names:
            c = claim_pins[name]
            t = tested_pins[name]
            c_canon = c.get("repo_remote_canonical", "")
            t_canon = t.get("repo_remote_canonical", "")
            c_commit = c.get("commit", "")
            t_commit = t.get("commit", "")

            # Canonical remote mismatch
            if c_canon and t_canon and c_canon != t_canon:
                return _gate(
                    "dependency", GateStatus.BLOCK,
                    f"Submodule '{name}': canonical remote mismatch "
                    f"({c_canon} vs {t_canon}).",
                )

            # Commit mismatch
            if c_commit and t_commit and c_commit != t_commit:
                return _gate(
                    "dependency", GateStatus.BLOCK,
                    f"Submodule '{name}': commit mismatch "
                    f"({c_commit[:8]} vs {t_commit[:8]}).",
                )

        return _gate(
            "dependency", GateStatus.PASS,
            f"All {len(claim_names)} submodule(s) verified consistent.",
            evidence=[f"{n}: {claim_pins[n].get('repo_remote_canonical', '')}@{claim_pins[n].get('commit', '')[:8]}"
                      for n in claim_names],
        )

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _get_implementation_provenance(
        ko: KnowledgeObject,
    ) -> ImplementationProvenance | None:
        """Extract ImplementationProvenance from KO content.

        Handles backward compatibility: if only repo_remote is provided
        (no repo_remote_sanitized or repo_remote_canonical), it is interpreted
        as the observed value, sanitized, and normalized into repo_remote_canonical.

        Credential sanitization: any credentials/tokens in the input URL are
        stripped before storage.  Never persist credential-bearing URLs.

        Conflict detection: if both sanitized and canonical are explicitly set,
        they must be consistent.  Mismatch -> fail closed.
        """
        if isinstance(ko.content, dict) and "implementation_provenance" in ko.content:
            d = ko.content["implementation_provenance"]
            sp = d.get("submodule_pins", {})

            # Accept new or deprecated field names
            sanitized = d.get("repo_remote_sanitized", d.get("repo_remote_raw", ""))
            canon = d.get("repo_remote_canonical", "")
            compat = d.get("repo_remote", "")

            # Sanitize credentials before any processing
            sanitized = sanitize_remote(sanitized)
            compat = sanitize_remote(compat)

            # Conflict check: sanitized explicitly set and differs from canonical
            if sanitized and canon:
                san_canon = canonical_remote(sanitized)
                if san_canon and san_canon != canon:
                    log.warning(
                        "Implementation provenance conflict: sanitized '%s' -> '%s' != canonical '%s'",
                        sanitized, san_canon, canon,
                    )
                    return ImplementationProvenance(
                        repo_remote_sanitized=sanitized,
                        repo_remote_canonical="",
                        repo_remote_raw=sanitized,
                        repo_remote=compat,
                        repo_path="",
                        branch="",
                        commit="",
                        submodule_pins={},
                        test_run_id="",
                        test_result_sha256="",
                        session_id="",
                        epf_ready_id="",
                    )

            # Backward compat: if new fields absent, repo_remote is the observed source
            if not sanitized and not canon and compat:
                sanitized = compat
                canon = canonical_remote(compat)
            elif not canon and compat:
                canon = canonical_remote(compat)
            elif not canon and sanitized:
                canon = canonical_remote(sanitized)

            return ImplementationProvenance(
                repo_remote_sanitized=sanitized,
                repo_remote_canonical=canon,
                repo_remote_raw=sanitized,
                repo_remote=compat,
                repo_path=d.get("repo_path", ""),
                branch=d.get("branch", ""),
                commit=d.get("commit", ""),
                worktree_clean=d.get("worktree_clean"),
                worktree_diff_sha256=d.get("worktree_diff_sha256", ""),
                submodule_pins=_sanitize_submodule_pins(sp),
                tested_submodule_pins=_sanitize_submodule_pins(
                    d.get("tested_submodule_pins", {})),
                test_run_id=d.get("test_run_id", ""),
                validator_ko_id=d.get("validator_ko_id", ""),
                test_command=d.get("test_command", ""),
                test_exit_code=d.get("test_exit_code"),
                test_result_sha256=d.get("test_result_sha256", ""),
                tested_commit=d.get("tested_commit", ""),
                tested_worktree_diff_sha256=d.get("tested_worktree_diff_sha256", ""),
                test_timestamp=d.get("test_timestamp", ""),
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
          1. content.declared_remotes (explicit field)
          2. included_components containing remote URLs (git@, https://, etc.)
          3. scope string itself if it contains a remote URL
          4. Canonical-format remotes (hostname/path) are also accepted
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
        """Legacy: normalize and compare transport URLs.
        Deprecated — use _remote_matches_canonical instead.
        """
        normalized_prov = ImplementationGatePolicy._normalize_remote(prov_remote)
        for a in allowed:
            if normalized_prov == ImplementationGatePolicy._normalize_remote(a):
                return True
        return False

    @staticmethod
    def _remote_matches_canonical(prov_canon: str, allowed: list[str]) -> bool:
        """Compare canonical repository identity against scope-declared remotes.

        Each allowed remote is canonicalized before comparison.
        Raw transport syntax is irrelevant; only canonical identity matters.
        """
        for a in allowed:
            if prov_canon == canonical_remote(a):
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


def _report(claim_ko_id: str, provenance: dict, scope: dict,
           worktree: dict, test: dict,
           falsifiability: dict, dependency: dict) -> dict:
    return {
        "claim_ko_id": claim_ko_id,
        "provenance": provenance,
        "scope": scope,
        "worktree": worktree,
        "test": test,
        "falsifiability": falsifiability,
        "dependency": dependency,
        "design_bearing": all(r["status"] == "pass" for r in
                              [provenance, scope, worktree, test,
                               falsifiability, dependency]),
    }


def _is_valid_iso8601(ts: str, require_tz: bool = True) -> bool:
    """ISO 8601 validation.

    With require_tz=True (default): timezone-aware timestamps only.
    2026-01-01T00:00:00Z or 2026-01-01T00:00:00+02:00

    With require_tz=False: also accepts naive timestamps.
    2026-01-01T00:00:00
    """
    if not ts or not isinstance(ts, str):
        return False

    tz_pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$'
    naive_pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$'

    if re.match(tz_pattern, ts):
        return True
    if not require_tz and re.match(naive_pattern, ts):
        return True
    return False


def _is_complete_portable_timestamp(ts: str) -> bool:
    """Full portable timestamp: timezone-aware ISO 8601."""
    return _is_valid_iso8601(ts, require_tz=True)


def _is_any_timestamp(ts: str) -> bool:
    """Any ISO 8601 timestamp, including naive."""
    return _is_valid_iso8601(ts, require_tz=False)
