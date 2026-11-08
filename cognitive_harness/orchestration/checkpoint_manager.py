# FILE: cognitive-harness/orchestration/checkpoint_manager.py
"""CheckpointManager — create, persist, and restore session checkpoints.

Operates on Checkpoint objects from cognitive_harness.model.checkpoint.
Provides file-based persistence and restore context generation.

Budget gate: before rendering context, checks that mandatory fields fit
within budget.  If not, raises CheckpointBudgetError — no compaction
fallback can help when mandatory content alone exceeds the budget.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from cognitive_harness.model.checkpoint import (
    Checkpoint,
    SourceReference,
    CheckpointIntegrityError,
)

log = logging.getLogger(__name__)


DEFAULT_CHECKPOINT_DIR = Path(
    os.environ.get("CH_CHECKPOINT_DIR", "~/.superretometer/checkpoints")
).expanduser()


class CheckpointError(Exception):
    """Raised when checkpoint creation or restoration fails."""


class CheckpointBudgetError(CheckpointError):
    """Raised when mandatory content exceeds budget — compaction cannot rescue."""


class CheckpointManager:
    """Create, list, load, and save Checkpoint instances.

    Checkpoints are stored as JSON files in a configurable directory.
    Filenames follow the pattern: {checkpoint_id}.json

    On load, integrity is verified automatically (content_hash check).
    """

    def __init__(self, checkpoint_dir: Path | None = None):
        self.checkpoint_dir = checkpoint_dir or DEFAULT_CHECKPOINT_DIR
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # ── Creation ───────────────────────────────────────────────────────

    def create_checkpoint(
        self,
        *,
        project_id: str,
        project_name: str,
        repo: str,
        branch: str,
        sha: str,
        goals: list[str] | None = None,
        constraints: list[str] | None = None,
        decisions: dict[str, dict[str, Any]] | None = None,
        last_user_message: str = "",
        open_tasks: list[dict[str, Any]] | None = None,
        active_tool_actions: list[dict[str, Any]] | None = None,
        source_references: list[SourceReference] | None = None,
        context_budget_tokens: int = 16_000,
        session_id: str = "",
    ) -> Checkpoint:
        """Create a new checkpoint and persist it to disk.

        Returns the Checkpoint instance.  Raises CheckpointError on I/O failure.
        """
        cp = Checkpoint(
            project_id=project_id,
            project_name=project_name,
            repo=repo,
            branch=branch,
            sha=sha,
            goals=goals or [],
            constraints=constraints or [],
            decisions=decisions or {},
            last_user_message=last_user_message,
            open_tasks=open_tasks or [],
            active_tool_actions=active_tool_actions or [],
            source_references=source_references or [],
            context_budget_tokens=context_budget_tokens,
            session_id=session_id,
        )
        self._save(cp)
        log.info(
            "Checkpoint created: %s (project=%s, sha=%s, hash=%s)",
            cp.checkpoint_id,
            project_id[:8],
            sha[:8] if sha else "",
            cp.content_hash[:8],
        )
        return cp

    # ── Persistence ────────────────────────────────────────────────────

    def _save(self, cp: Checkpoint) -> Path:
        """Persist checkpoint to disk.  Returns the file path."""
        path = self.checkpoint_dir / f"{cp.checkpoint_id}.json"
        try:
            path.write_text(cp.to_json(), encoding="utf-8")
        except OSError as e:
            raise CheckpointError(
                f"Failed to write checkpoint {cp.checkpoint_id}: {e}"
            ) from e
        return path

    def load(self, checkpoint_id: str) -> Checkpoint:
        """Load a checkpoint by ID and verify integrity.

        Raises CheckpointError if not found or corrupt.
        Raises CheckpointIntegrityError if content hash doesn't match.
        """
        path = self.checkpoint_dir / f"{checkpoint_id}.json"
        if not path.exists():
            raise CheckpointError(
                f"Checkpoint {checkpoint_id} not found at {path}"
            )
        try:
            data = path.read_text(encoding="utf-8")
            cp = Checkpoint.from_json(data)
        except (json.JSONDecodeError, KeyError) as e:
            raise CheckpointError(
                f"Corrupt checkpoint {checkpoint_id}: {e}"
            ) from e
        # Verify integrity on load
        cp.verify_integrity()
        return cp

    def list_checkpoints(self) -> list[dict[str, str]]:
        """List all checkpoint files with metadata."""
        result = []
        for p in sorted(self.checkpoint_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                result.append({
                    "checkpoint_id": data.get("checkpoint_id", p.stem),
                    "content_hash": data.get("content_hash", ""),
                    "timestamp": data.get("timestamp", ""),
                    "project_id": data.get("project_id", ""),
                    "sha": data.get("sha", ""),
                    "project_name": data.get("project_name", ""),
                })
            except (json.JSONDecodeError, OSError):
                continue
        return result

    # ── Restore context generation (standalone, no OpenCode coupling) ──

    def generate_restore_context(
        self,
        cp: Checkpoint,
        budget_tokens: int | None = None,
    ) -> str:
        """Generate a compact text context from a checkpoint for injection.

        The output is designed for LLM context windows: factual,
        token-efficient, no narrative filler.

        Budget gate: if budget_tokens is set, mandatory fields are checked
        first.  If they exceed the budget, CheckpointBudgetError is raised
        (no compaction fallback can help).

        Args:
            cp: The checkpoint to render.
            budget_tokens: Optional token budget.  If None, no gate check.

        Returns:
            Markdown-formatted context string ready for preamble injection.

        Raises:
            CheckpointBudgetError: mandatory content exceeds budget.
        """
        if budget_tokens is not None:
            mandatory_tokens = cp.mandatory_token_estimate()
            if mandatory_tokens > budget_tokens:
                raise CheckpointBudgetError(
                    f"Mandatory content ({mandatory_tokens} tokens) exceeds "
                    f"budget ({budget_tokens} tokens).  Restore blocked."
                )

        lines = [
            f"# Checkpoint: {cp.checkpoint_id}",
            f"# Content Hash: {cp.content_hash[:16]}",
            f"# Project: {cp.project_name} ({cp.project_id})",
            f"# Repo: {cp.repo} @ {cp.branch}:{cp.sha[:12]}",
            f"# Time: {cp.timestamp}",
            "",
        ]

        # Goals — mandatory, always included
        if cp.goals:
            lines.append("## Goals")
            for i, g in enumerate(cp.goals, 1):
                lines.append(f"{i}. {g}")
            lines.append("")

        # Constraints — high priority for context preservation
        if cp.constraints:
            lines.append("## Constraints")
            for c in cp.constraints:
                lines.append(f"- {c}")
            lines.append("")

        # Last user message — preserves conversational continuity
        if cp.last_user_message:
            lines.append("## Last User Message")
            lines.append(f"> {cp.last_user_message}")
            lines.append("")

        # Decisions
        if cp.decisions:
            lines.append("## Decisions")
            for did, d in cp.decisions.items():
                outcome = d.get("outcome", "")
                rationale = d.get("rationale", "")
                lines.append(f"- **{did}**: {outcome}")
                if rationale:
                    lines.append(f"  Rationale: {rationale}")
            lines.append("")

        # Active tool actions — preserves in-flight work state
        if cp.active_tool_actions:
            lines.append("## Active Tool Actions")
            for a in cp.active_tool_actions:
                tool = a.get("tool", "unknown")
                status = a.get("status", "unknown")
                artifact = a.get("artifact", "")
                lines.append(f"- [{status}] {tool}" + (f" → {artifact}" if artifact else ""))
            lines.append("")

        # Open tasks
        if cp.open_tasks:
            lines.append("## Open Tasks")
            for t in cp.open_tasks:
                status = t.get("status", "pending")
                desc = t.get("description", "")
                lines.append(f"- [{status}] {desc}")
            lines.append("")

        # Source references
        if cp.source_references:
            lines.append("## Source References")
            for sr in cp.source_references:
                sha_tag = f" @ {sr.sha[:8]}" if sr.sha else ""
                desc = f" — {sr.description}" if sr.description else ""
                lines.append(f"- `{sr.path}`{sha_tag}{desc}")
            lines.append("")

        return "\n".join(lines)

    def restore_checkpoint(
        self,
        checkpoint_id: str,
        budget_tokens: int | None = None,
    ) -> tuple[Checkpoint, str]:
        """Load checkpoint, verify integrity, generate restore context.

        Returns (Checkpoint, context_string).  Context is ready for injection.

        Args:
            checkpoint_id: UUID of the checkpoint to restore.
            budget_tokens: Optional token budget for budget gate.
        """
        cp = self.load(checkpoint_id)
        context = self.generate_restore_context(cp, budget_tokens=budget_tokens)
        return cp, context
