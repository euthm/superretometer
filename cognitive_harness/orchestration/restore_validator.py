# FILE: cognitive-harness/orchestration/restore_validator.py
"""RestoreValidator — verify restored context integrity.

After loading a checkpoint, this module validates:
1. Project ID matches expected scope
2. SHA is not stale (has successor commits)
3. Source references are accessible
4. Context fits within token budget
5. No critical information is missing

Each check returns a ValidationResult: pass, warning, or fail.
A restore with any 'fail' result should not proceed silently.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from cognitive_harness.model.checkpoint import Checkpoint, CheckpointIntegrityError

log = logging.getLogger(__name__)


class Severity(Enum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


@dataclass
class ValidationResult:
    """Result of a single validation check."""

    check_name: str
    severity: Severity
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check_name,
            "severity": self.severity.value,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class ValidationReport:
    """Aggregated validation results for a restore operation."""

    checkpoint_id: str
    results: list[ValidationResult] = field(default_factory=list)
    context_tokens: int = 0
    budget_tokens: int = 0

    @property
    def has_failures(self) -> bool:
        return any(r.severity == Severity.FAIL for r in self.results)

    @property
    def has_warnings(self) -> bool:
        return any(r.severity == Severity.WARNING for r in self.results)

    @property
    def is_safe_to_restore(self) -> bool:
        """Return True if no validation failures.

        Budget exceeded is NOT a failure — it triggers compaction, not rejection.
        Only semantic failures (wrong project, missing fields, etc.) block restore.
        """
        return not self.has_failures

    def to_json(self) -> str:
        return json.dumps({
            "checkpoint_id": self.checkpoint_id,
            "safe_to_restore": self.is_safe_to_restore,
            "has_failures": self.has_failures,
            "has_warnings": self.has_warnings,
            "context_tokens": self.context_tokens,
            "budget_tokens": self.budget_tokens,
            "results": [r.to_dict() for r in self.results],
        }, indent=2)


class RestoreValidator:
    """Validate a checkpoint before restoring context.

    Args:
        expected_project_id: The Memory project UUID the restoring session expects.
        budget_tokens: Maximum token budget for the restored context.
        git_repo_path: Path to the repository for SHA verification.
    """

    def __init__(
        self,
        expected_project_id: str = "",
        budget_tokens: int = 16_000,
        git_repo_path: str = "",
    ):
        self.expected_project_id = expected_project_id
        self.budget_tokens = budget_tokens
        self.git_repo_path = git_repo_path

    def validate(self, cp: Checkpoint) -> ValidationReport:
        """Run all validation checks against a checkpoint.

        Returns a ValidationReport with pass/warning/fail results.
        """
        report = ValidationReport(
            checkpoint_id=cp.checkpoint_id,
            budget_tokens=self.budget_tokens,
        )

        report.results.append(self._check_integrity(cp))
        report.results.append(self._check_project_id(cp))
        report.results.append(self._check_sha_freshness(cp))
        report.results.append(self._check_source_references(cp))
        report.results.append(self._check_context_budget(cp))
        report.results.append(self._check_required_fields(cp))
        report.results.append(self._check_version(cp))

        # Estimate token cost of generated context
        from cognitive_harness.orchestration.checkpoint_manager import CheckpointManager
        mgr = CheckpointManager()
        context = mgr.generate_restore_context(cp)
        report.context_tokens = len(context) // 4

        return report

    # ── Individual checks ──────────────────────────────────────────────

    def _check_project_id(self, cp: Checkpoint) -> ValidationResult:
        """Verify project ID matches expected scope."""
        if not self.expected_project_id:
            return ValidationResult(
                check_name="project_id",
                severity=Severity.WARNING,
                message="No expected project ID set — cannot verify scope",
                details={"checkpoint_project_id": cp.project_id},
            )
        if cp.project_id != self.expected_project_id:
            return ValidationResult(
                check_name="project_id",
                severity=Severity.FAIL,
                message=f"Project ID mismatch: checkpoint={cp.project_id}, expected={self.expected_project_id}",
                details={"checkpoint_project_id": cp.project_id, "expected": self.expected_project_id},
            )
        return ValidationResult(
            check_name="project_id",
            severity=Severity.PASS,
            message=f"Project ID matches: {cp.project_id}",
        )

    def _check_sha_freshness(self, cp: Checkpoint) -> ValidationResult:
        """Check if the checkpoint SHA has successor commits.

        Returns WARNING if the SHA is behind HEAD on the same branch.
        Returns PASS if the SHA is current or branch is not accessible.
        """
        if not cp.sha or not self.git_repo_path:
            return ValidationResult(
                check_name="sha_freshness",
                severity=Severity.WARNING if cp.sha else Severity.PASS,
                message="SHA freshness check skipped (no repo path or empty SHA)",
                details={"sha": cp.sha[:12] if cp.sha else ""},
            )

        import subprocess

        try:
            result = subprocess.run(
                ["git", "rev-parse", "--verify", cp.sha],
                cwd=self.git_repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return ValidationResult(
                    check_name="sha_freshness",
                    severity=Severity.WARNING,
                    message=f"SHA {cp.sha[:12]} not found in repo {self.git_repo_path}",
                    details={"sha": cp.sha[:12]},
                )

            # Check if there are commits after this SHA on the branch
            if cp.branch:
                branch_sha = subprocess.run(
                    ["git", "rev-parse", cp.branch],
                    cwd=self.git_repo_path,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if branch_sha.returncode == 0:
                    branch_commit = branch_sha.stdout.strip()
                    if branch_commit != cp.sha:
                        # Count commits between checkpoint SHA and branch HEAD
                        count_result = subprocess.run(
                            ["git", "rev-list", f"{cp.sha}..{branch_commit}", "--count"],
                            cwd=self.git_repo_path,
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )
                        behind_count = int(count_result.stdout.strip()) if count_result.returncode == 0 else -1
                        if behind_count > 0:
                            return ValidationResult(
                                check_name="sha_freshness",
                                severity=Severity.WARNING,
                                message=f"SHA {cp.sha[:12]} is {behind_count} commit(s) behind {cp.branch}",
                                details={
                                    "checkpoint_sha": cp.sha[:12],
                                    "branch_sha": branch_commit[:12],
                                    "behind_commits": behind_count,
                                },
                            )

            return ValidationResult(
                check_name="sha_freshness",
                severity=Severity.PASS,
                message=f"SHA {cp.sha[:12]} is current on {cp.branch or 'unknown branch'}",
                details={"sha": cp.sha[:12]},
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            return ValidationResult(
                check_name="sha_freshness",
                severity=Severity.WARNING,
                message=f"Could not verify SHA freshness: {e}",
                details={"sha": cp.sha[:12]},
            )

    def _check_source_references(self, cp: Checkpoint) -> ValidationResult:
        """Verify that source reference paths are accessible."""
        if not cp.source_references:
            return ValidationResult(
                check_name="source_references",
                severity=Severity.PASS,
                message="No source references to verify",
            )

        missing = []
        accessible = 0
        base = Path(self.git_repo_path) if self.git_repo_path else Path.cwd()

        for sr in cp.source_references:
            p = base / sr.path
            if not p.exists():
                missing.append(sr.path)
            else:
                accessible += 1

        if missing:
            return ValidationResult(
                check_name="source_references",
                severity=Severity.FAIL,
                message=f"{len(missing)} source reference(s) not accessible: {', '.join(missing[:5])}",
                details={"missing": missing, "accessible": accessible, "total": len(cp.source_references)},
            )
        return ValidationResult(
            check_name="source_references",
            severity=Severity.PASS,
            message=f"All {accessible}/{len(cp.source_references)} source references accessible",
            details={"accessible": accessible},
        )

    def _check_context_budget(self, cp: Checkpoint) -> ValidationResult:
        """Check if checkpoint context fits within budget.

        Budget exceeded is a WARNING, not a FAIL — the injector can compact.
        Only semantic failures (wrong project, missing fields) block restore.
        """
        estimated = cp.estimated_tokens()
        if estimated > self.budget_tokens:
            return ValidationResult(
                check_name="context_budget",
                severity=Severity.WARNING,
                message=f"Checkpoint context ({estimated} tokens) exceeds budget ({self.budget_tokens} tokens) — compaction needed",
                details={"estimated_tokens": estimated, "budget": self.budget_tokens},
            )
        if estimated > self.budget_tokens * 0.8:
            return ValidationResult(
                check_name="context_budget",
                severity=Severity.WARNING,
                message=f"Checkpoint context ({estimated} tokens) is {estimated/self.budget_tokens*100:.0f}% of budget",
                details={"estimated_tokens": estimated, "budget": self.budget_tokens},
            )
        return ValidationResult(
            check_name="context_budget",
            severity=Severity.PASS,
            message=f"Context fits budget: {estimated}/{self.budget_tokens} tokens",
            details={"estimated_tokens": estimated, "budget": self.budget_tokens},
        )

    def _check_required_fields(self, cp: Checkpoint) -> ValidationResult:
        """Verify that required fields are present and non-empty."""
        required = {
            "project_id": "Project ID is required for scoped restore",
            "sha": "Git SHA is required for provenance tracking",
            "repo": "Repository path is required for source verification",
        }
        missing = []
        for field_name, error_msg in required.items():
            val = getattr(cp, field_name, None)
            if not val:
                missing.append((field_name, error_msg))

        if missing:
            messages = [f"{f}: {m}" for f, m in missing]
            return ValidationResult(
                check_name="required_fields",
                severity=Severity.FAIL,
                message=f"Missing required fields: {'; '.join(messages)}",
                details={"missing_fields": [m[0] for m in missing]},
            )
        return ValidationResult(
            check_name="required_fields",
            severity=Severity.PASS,
            message="All required fields present",
        )

    def _check_integrity(self, cp: Checkpoint) -> ValidationResult:
        """Verify content hash matches (tampering detection)."""
        try:
            cp.verify_integrity()
            return ValidationResult(
                check_name="integrity",
                severity=Severity.PASS,
                message=f"Content hash verified: {cp.content_hash[:16]}",
                details={"content_hash": cp.content_hash[:16]},
            )
        except CheckpointIntegrityError as e:
            return ValidationResult(
                check_name="integrity",
                severity=Severity.FAIL,
                message=str(e),
                details={"stored_hash": cp.content_hash[:16] if cp.content_hash else ""},
            )

    def _check_version(self, cp: Checkpoint) -> ValidationResult:
        """Validate checkpoint format version."""
        if cp.version < 1:
            return ValidationResult(
                check_name="version",
                severity=Severity.FAIL,
                message=f"Unsupported checkpoint version: {cp.version}",
                details={"version": cp.version},
            )
        if cp.version > 2:
            return ValidationResult(
                check_name="version",
                severity=Severity.WARNING,
                message=f"Checkpoint version {cp.version} is newer than validator (supports v1-v2)",
                details={"version": cp.version, "max_supported": 2},
            )
        return ValidationResult(
            check_name="version",
            severity=Severity.PASS,
            message=f"Checkpoint version {cp.version} is supported",
        )
