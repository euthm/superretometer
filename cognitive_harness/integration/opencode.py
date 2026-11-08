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
4. Rendering the final preamble with metadata header

OPENCODE INTEGRATION STATUS:
    Automatic injection via MCP tool or subagent hook: UNIMPLEMENTED.
    The injector provides the preamble string; the caller is responsible
    for injecting it into the agent session (e.g., system prompt, context
    window, or AGENTS.md preamble).

CLIENT VERSION REQUIREMENTS:
    opencode >= 0.1.0 (context injection via system prompt)
    Memory MCP >= v0.41 (for project-scoped entity queries)

COUPLING POINT:
    The injector returns a (preamble: str, report: ValidationReport) tuple.
    The caller (OpenCode agent, subagent, or CLI) prepends the preamble to
    the session system prompt.  No bidirectional coupling exists.

TOKEN BUDGET:
    Token counts are estimates (CharProxyEstimator: len(text) // 4).
    The budget check covers the checkpoint context injection ONLY.
    The caller must ensure the full request fits:
        total ≤ context_window
        where total = system_prompt + checkpoint_context + recent_messages
            + mcp_tool_descriptions + reply_reserve

    For hard token budgets, integrate a model-specific tokenizer
    (e.g., tiktoken for OpenAI models, gemini tokenizer for Google).
"""
from __future__ import annotations

import logging
from pathlib import Path

from cognitive_harness.orchestration.checkpoint_manager import (
    CheckpointManager,
    CheckpointError,
    CheckpointBudgetError,
)
from cognitive_harness.model.checkpoint import CheckpointIntegrityError
from cognitive_harness.orchestration.restore_validator import (
    RestoreValidator,
    ValidationReport,
    Severity,
)
from cognitive_harness.model.checkpoint import Checkpoint

log = logging.getLogger(__name__)

# Integration metadata
INTEGRATION_VERSION = "0.1.0"
INTEGRATION_STATUS = "manual"  # auto-injection not yet implemented
MIN_OPENCODE_VERSION = "0.1.0"


class ContextInjectionError(Exception):
    """Raised when context injection fails."""


class OpenCodeContextInjector:
    """Inject checkpoint context into OpenCode agent sessions.

    On injection:
    1. Load checkpoint by ID (integrity verified)
    2. Validate against expected project, budget, and source accessibility
    3. Budget gate: mandatory content must fit
    4. If budget exceeded: apply compaction (strip non-essential fields)
    5. Return (preamble, validation_report)

    The preamble is a Markdown-formatted context block suitable for
    prepending to the agent system prompt.
    """

    def __init__(
        self,
        checkpoint_dir: Path | None = None,
        expected_project_id: str = "",
        budget_tokens: int = 16_000,
        git_repo_path: str = "",
    ):
        self.manager = CheckpointManager(checkpoint_dir=checkpoint_dir)
        self.validator = RestoreValidator(
            expected_project_id=expected_project_id,
            budget_tokens=budget_tokens,
            git_repo_path=git_repo_path,
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

        # Semantic failures block restore
        if report.has_failures:
            failures = [
                r.message
                for r in report.results
                if r.severity == Severity.FAIL
            ]
            raise ContextInjectionError(
                f"Cannot inject checkpoint {checkpoint_id}: {'; '.join(failures)}"
            )

        # Generate context with budget gate
        try:
            context = self.manager.generate_restore_context(
                cp, budget_tokens=self.budget_tokens
            )
        except CheckpointBudgetError as e:
            raise ContextInjectionError(str(e)) from e

        # Check if compaction is needed
        context_tokens = len(context) // 4
        if context_tokens > self.budget_tokens:
            compacted = self._compact_context(cp, self.budget_tokens)
            if compacted:
                preamble = self._build_preamble(compacted, cp)
                log.warning(
                    "Context compacted to fit budget: %d -> %d tokens",
                    context_tokens,
                    len(preamble) // 4,
                )
                return preamble, report
            raise ContextInjectionError(
                f"Checkpoint {checkpoint_id} cannot be compacted to fit "
                f"{self.budget_tokens}-token budget"
            )

        preamble = self._build_preamble(context, cp)
        log.info(
            "Context injected: %s (%d tokens, %d warnings)",
            checkpoint_id,
            len(preamble) // 4,
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
        """Inject the latest matching checkpoint.

        Filters by project_id and/or branch.  Returns the most recent
        checkpoint that matches the criteria.
        """
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
        """Build the final preamble with checkpoint metadata header."""
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

        Strategy (priority order):
        1. Goals (mandatory — always included)
        2. Constraints
        3. Decisions (if budget < 70% used)
        4. Open tasks (if budget < 85% used)
        5. Source references (if budget < 95% used)

        Returns compacted context string, or None if goals alone exceed budget.
        """
        lines = [
            f"# Checkpoint: {cp.checkpoint_id} (COMPACTED)",
            f"# Project: {cp.project_name} ({cp.project_id})",
            f"# Repo: {cp.repo} @ {cp.branch}:{cp.sha[:12]}",
            "",
        ]

        def _token_count() -> int:
            return len("\n".join(lines)) // 4

        # Goals — mandatory
        if cp.goals:
            lines.append("## Goals")
            for i, g in enumerate(cp.goals, 1):
                lines.append(f"{i}. {g}")
            lines.append("")

        if _token_count() > target_tokens:
            log.error(
                "Goals alone exceed budget (%d > %d tokens)",
                _token_count(),
                target_tokens,
            )
            return None

        # Constraints — high priority
        if cp.constraints and _token_count() < target_tokens * 0.6:
            lines.append("## Constraints")
            for c in cp.constraints:
                lines.append(f"- {c}")
            lines.append("")

        # Decisions
        if cp.decisions and _token_count() < target_tokens * 0.7:
            lines.append("## Decisions")
            for did, d in cp.decisions.items():
                outcome = d.get("outcome", "")
                lines.append(f"- **{did}**: {outcome}")
            lines.append("")

        # Open tasks
        if cp.open_tasks and _token_count() < target_tokens * 0.85:
            lines.append("## Open Tasks")
            for t in cp.open_tasks:
                status = t.get("status", "pending")
                desc = t.get("description", "")
                lines.append(f"- [{status}] {desc}")
            lines.append("")

        # Source references
        if cp.source_references and _token_count() < target_tokens * 0.95:
            lines.append("## Source References")
            for sr in cp.source_references:
                sha_tag = f"@{sr.sha[:8]}" if sr.sha else ""
                lines.append(f"- `{sr.path}` {sha_tag}")
            lines.append("")

        return "\n".join(lines)


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
