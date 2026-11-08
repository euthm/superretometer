# FILE: cognitive-harness/integration/opencode.py
"""OpenCode integration — checkpoint context injection with compaction fallback.

ARCHITECTURE:
    CheckpointManager.generate_restore_context()  →  pure context generation
    OpenCodeContextInjector.inject()              →  validation + budget + compaction
    [OpenCode MCP / subagent hook]                →  UNIMPLEMENTED

The context generation layer (CheckpointManager) is decoupled from the
OpenCode integration layer.  The injector handles:

1. Validation against expected project, budget, and source accessibility
2. Budget gate (mandatory content check)
3. Compaction fallback when context exceeds budget
4. Final preamble budget check — the complete preamble is verified before return

OPENCODE INTEGRATION STATUS:
    Automatic injection via MCP tool or subagent hook: UNIMPLEMENTED.
    The injector provides the preamble string; the caller is responsible
    for injecting it into the agent session.

TOKEN ESTIMATION:
    A single CharProxyEstimator instance (self.estimator) is shared across
    validation, context generation, compaction, and final preamble check.
    No divergence between stages.

    Token counts are estimates (len(text) // 4).  The budget check covers
    the checkpoint context injection only.  The caller must ensure the full
    request fits the context window.
"""
from __future__ import annotations

import logging
from pathlib import Path

from cognitive_harness.model.checkpoint import (
    Checkpoint,
    CheckpointIntegrityError,
    CharProxyEstimator,
    TokenEstimator,
)
from cognitive_harness.orchestration.checkpoint_manager import (
    CheckpointManager,
    CheckpointError,
    CheckpointBudgetError,
)
from cognitive_harness.orchestration.restore_validator import (
    RestoreValidator,
    ValidationReport,
    Severity,
)

log = logging.getLogger(__name__)

INTEGRATION_VERSION = "0.1.0"
INTEGRATION_STATUS = "manual"
MIN_OPENCODE_VERSION = "0.1.0"


class ContextInjectionError(Exception):
    """Raised when context injection fails."""


class OpenCodeContextInjector:
    """Inject checkpoint context into OpenCode agent sessions.

    On injection:
    1. Load checkpoint by ID (integrity verified)
    2. Validate against expected project, budget, and source accessibility
    3. Budget gate: mandatory content must fit
    4. If budget exceeded: apply compaction
    5. Final preamble budget check — verify complete preamble fits
    6. Return (preamble, validation_report)
    """

    def __init__(
        self,
        checkpoint_dir: Path | None = None,
        expected_project_id: str = "",
        budget_tokens: int = 16_000,
        git_repo_path: str = "",
        estimator: TokenEstimator | None = None,
    ):
        self.manager = CheckpointManager(checkpoint_dir=checkpoint_dir)
        self.estimator = estimator or CharProxyEstimator()
        self.validator = RestoreValidator(
            expected_project_id=expected_project_id,
            budget_tokens=budget_tokens,
            git_repo_path=git_repo_path,
            estimator=self.estimator,
        )
        self.budget_tokens = budget_tokens

    def inject(self, checkpoint_id: str) -> tuple[str, ValidationReport]:
        """Inject checkpoint context.  Returns (preamble, report).

        Raises ContextInjectionError if validation has failures, integrity
        check fails, or compaction cannot rescue the context.
        """
        try:
            cp = self.manager.load(checkpoint_id)
        except (CheckpointError, CheckpointIntegrityError) as e:
            raise ContextInjectionError(str(e)) from e

        report = self.validator.validate(cp)

        if report.has_failures:
            failures = [
                r.message
                for r in report.results
                if r.severity == Severity.FAIL
            ]
            raise ContextInjectionError(
                f"Cannot inject checkpoint {checkpoint_id}: {'; '.join(failures)}"
            )

        # Reserve tokens for the preamble header wrapper
        header_template = (
            f"# CONTEXT RESTORED FROM CHECKPOINT\n"
            f"Checkpoint ID: ???\n"
            f"Content Hash: ???\n"
            f"---\n\n"
        )
        header_cost = self.estimator.estimate(header_template)
        context_budget = self.budget_tokens - header_cost

        # Generate context with budget gate (mandatory check against context budget)
        try:
            context = self.manager.generate_restore_context(
                cp, budget_tokens=context_budget, estimator=self.estimator,
            )
        except CheckpointBudgetError as e:
            raise ContextInjectionError(str(e)) from e

        preamble = self._build_preamble(context, cp)
        preamble_tokens = self.estimator.estimate(preamble)

        # Try compaction if full preamble exceeds budget
        if preamble_tokens > self.budget_tokens:
            compacted = self._compact_context(cp, self.budget_tokens)
            if compacted is not None:
                log.warning(
                    "Context compacted to fit budget: %d tokens",
                    self.estimator.estimate(compacted),
                )
                return compacted, report
            raise ContextInjectionError(
                f"Checkpoint {checkpoint_id} cannot be compacted to fit "
                f"{self.budget_tokens}-token budget"
            )

        log.info(
            "Context injected: %s (%d tokens, %d warnings)",
            checkpoint_id,
            preamble_tokens,
            sum(
                1
                for r in report.results
                if r.severity == Severity.WARNING
            ),
        )
        return preamble, report

    def inject_latest(
        self,
        *,
        project_id: str | None = None,
        branch: str | None = None,
    ) -> tuple[str, ValidationReport]:
        checkpoints = self.manager.list_checkpoints()
        candidates = []
        for cp_info in checkpoints:
            if project_id and cp_info.get("project_id") != project_id:
                continue
            if branch and cp_info.get("branch") != branch:
                continue
            candidates.append(cp_info)

        if not candidates:
            filter_desc = []
            if project_id:
                filter_desc.append(f"project_id={project_id}")
            if branch:
                filter_desc.append(f"branch={branch}")
            raise ContextInjectionError(
                f"No checkpoint found matching "
                f"{', '.join(filter_desc) or 'any criteria'}"
            )

        candidates.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        latest = candidates[0]["checkpoint_id"]
        return self.inject(latest)

    def _build_preamble(self, context: str, cp: Checkpoint) -> str:
        return (
            f"# CONTEXT RESTORED FROM CHECKPOINT\n"
            f"Checkpoint ID: {cp.checkpoint_id}\n"
            f"Content Hash: {cp.content_hash[:16]}\n"
            f"---\n\n"
            f"{context}"
        )

    def _compact_context(
        self,
        cp: Checkpoint,
        target_tokens: int,
    ) -> str | None:
        """Compact checkpoint context to fit within target token budget.

        Builds context body, reserves space for preamble header, then
        verifies the complete preamble against the budget.

        Mandatory-first rendering:
            1. Metadata header + goals + constraints + last_user_message +
               active_tool_actions  (mandatory — cannot be dropped).
            2. If mandatory exceeds budget → None (blocked).
            3. Decisions, tasks, sources  (optional — appended if they fit).
            4. Wrap in preamble header, verify final preamble fits.

        Returns the final preamble string, or None if mandatory alone exceeds budget.
        """
        # Reserve tokens for the preamble header wrapper
        header_template = (
            f"# CONTEXT RESTORED FROM CHECKPOINT\n"
            f"Checkpoint ID: {cp.checkpoint_id}\n"
            f"Content Hash: {cp.content_hash[:16]}\n"
            f"---\n\n"
        )
        header_cost = self.estimator.estimate(header_template)
        context_budget = target_tokens - header_cost

        lines: list[str] = []

        def _count() -> int:
            return self.estimator.estimate("\n".join(lines))

        # ── Metadata header ──────────────────────────────────────────
        lines.append(f"# Checkpoint: {cp.checkpoint_id} (COMPACTED)")
        lines.append(f"# Content Hash: {cp.content_hash[:16]}")
        lines.append(f"# Project: {cp.project_name} ({cp.project_id})")
        lines.append(f"# Repo: {cp.repo} @ {cp.branch}:{cp.sha[:12]}")
        lines.append("")

        # ── Mandatory sections ───────────────────────────────────────
        if cp.goals:
            lines.append("## Goals")
            for i, g in enumerate(cp.goals, 1):
                lines.append(f"{i}. {g}")
            lines.append("")

        if cp.constraints:
            lines.append("## Constraints")
            for c in cp.constraints:
                lines.append(f"- {c}")
            lines.append("")

        if cp.last_user_message:
            lines.append("## Last User Message")
            lines.append(f"> {cp.last_user_message}")
            lines.append("")

        if cp.active_tool_actions:
            lines.append("## Active Tool Actions")
            for a in cp.active_tool_actions:
                tool = a.get("tool", "unknown")
                status = a.get("status", "unknown")
                artifact = a.get("artifact", "")
                lines.append(f"- [{status}] {tool}" + (f" → {artifact}" if artifact else ""))
            lines.append("")

        # Mandatory gate (against context budget, not total)
        if _count() > context_budget:
            log.error(
                "Mandatory context (%d tokens) exceeds context budget (%d tokens)",
                _count(), context_budget,
            )
            return None

        # ── Optional sections — append if they fit ───────────────────
        def _append_section(block: list[str]) -> None:
            nonlocal lines
            trial = lines + block
            if self.estimator.estimate("\n".join(trial)) <= context_budget:
                lines.extend(block)

        if cp.decisions:
            sec = ["## Decisions"]
            for did, d in cp.decisions.items():
                outcome = d.get("outcome", "")
                sec.append(f"- **{did}**: {outcome}")
            sec.append("")
            _append_section(sec)

        if cp.open_tasks:
            sec = ["## Open Tasks"]
            for t in cp.open_tasks:
                status = t.get("status", "pending")
                desc = t.get("description", "")
                sec.append(f"- [{status}] {desc}")
            sec.append("")
            _append_section(sec)

        if cp.source_references:
            sec = ["## Source References"]
            for sr in cp.source_references:
                sha_tag = f"@{sr.sha[:8]}" if sr.sha else ""
                sec.append(f"- `{sr.path}` {sha_tag}")
            sec.append("")
            _append_section(sec)

        # Wrap in preamble and verify final fits
        preamble = self._build_preamble("\n".join(lines), cp)
        if self.estimator.estimate(preamble) > target_tokens:
            log.error(
                "Compacted preamble (%d tokens) exceeds budget (%d tokens)",
                self.estimator.estimate(preamble), target_tokens,
            )
            return None

        return preamble


# ── CLI helper ────────────────────────────────────────────────────────────


def inject_checkpoint_cli(
    checkpoint_id: str,
    checkpoint_dir: str = "",
    project_id: str = "",
    budget: int = 16_000,
    repo_path: str = "",
) -> None:
    """CLI entry point: inject checkpoint context to stdout."""
    injector = OpenCodeContextInjector(
        checkpoint_dir=Path(checkpoint_dir) if checkpoint_dir else None,
        expected_project_id=project_id,
        budget_tokens=budget,
        git_repo_path=repo_path,
    )
    try:
        preamble, report = injector.inject(checkpoint_id)
        print(preamble)
        print(
            f"\n# Validation: safe={report.is_safe_to_restore}, "
            f"failures={sum(1 for r in report.results if r.severity == Severity.FAIL)}, "
            f"warnings={sum(1 for r in report.results if r.severity == Severity.WARNING)}"
        )
    except ContextInjectionError as e:
        import sys
        print(f"# ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m cognitive_harness.integration.opencode <checkpoint_id> [options]")
        raise SystemExit(1)
    inject_checkpoint_cli(sys.argv[1])
