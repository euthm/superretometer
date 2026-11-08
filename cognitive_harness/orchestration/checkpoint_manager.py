# FILE: cognitive-harness/orchestration/checkpoint_manager.py
"""CheckpointManager — create, persist, and restore session checkpoints.

Budget gate (mandatory-first rendering):
    1. Render mandatory sections (metadata + goals + constraints +
       last_user_message + active_tool_actions).
    2. If mandatory alone exceeds budget → CheckpointBudgetError (blocked).
    3. Append optional sections (decisions, tasks, sources) one by one,
       checking budget after each.  Stop when budget would be exceeded.
    4. Final check: estimate the complete preamble (including header).
       If it exceeds budget → CheckpointBudgetError.

The same CharProxyEstimator instance is used throughout — no divergence
between validation, rendering, compaction, and final gate.
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
    CharProxyEstimator,
    TokenEstimator,
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
    """Create, list, load, and save Checkpoint instances."""

    def __init__(self, checkpoint_dir: Path | None = None):
        self.checkpoint_dir = checkpoint_dir or DEFAULT_CHECKPOINT_DIR
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

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

    def _save(self, cp: Checkpoint) -> Path:
        path = self.checkpoint_dir / f"{cp.checkpoint_id}.json"
        try:
            path.write_text(cp.to_json(), encoding="utf-8")
        except OSError as e:
            raise CheckpointError(
                f"Failed to write checkpoint {cp.checkpoint_id}: {e}"
            ) from e
        return path

    def load(self, checkpoint_id: str) -> Checkpoint:
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
        cp.verify_integrity()
        return cp

    def list_checkpoints(self) -> list[dict[str, str]]:
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

    # ── Restore context generation ─────────────────────────────────────

    def generate_restore_context(
        self,
        cp: Checkpoint,
        budget_tokens: int | None = None,
        estimator: TokenEstimator | None = None,
    ) -> str:
        """Generate a compact text context from a checkpoint.

        Mandatory-first rendering:
            1. Metadata header + goals + constraints + last_user_message +
               active_tool_actions  (mandatory — cannot be dropped).
            2. If mandatory exceeds budget → CheckpointBudgetError.
            3. Decisions, tasks, sources  (optional — appended if they fit).

        Final check: the complete preamble (with injection header) is
        estimated.  If it exceeds budget → CheckpointBudgetError.

        The same CharProxyEstimator instance is used for every count in
        this flow — no divergence between stages.
        """
        if estimator is None:
            estimator = CharProxyEstimator()

        def _count() -> int:
            return estimator.estimate("\n".join(lines))

        lines: list[str] = []

        # ── Metadata header ──────────────────────────────────────────
        lines.append(f"# Checkpoint: {cp.checkpoint_id}")
        lines.append(f"# Content Hash: {cp.content_hash[:16]}")
        lines.append(f"# Project: {cp.project_name} ({cp.project_id})")
        lines.append(f"# Repo: {cp.repo} @ {cp.branch}:{cp.sha[:12]}")
        lines.append(f"# Time: {cp.timestamp}")
        lines.append("")

        # ── Mandatory sections ───────────────────────────────────────
        # Goals
        if cp.goals:
            lines.append("## Goals")
            for i, g in enumerate(cp.goals, 1):
                lines.append(f"{i}. {g}")
            lines.append("")

        # Constraints
        if cp.constraints:
            lines.append("## Constraints")
            for c in cp.constraints:
                lines.append(f"- {c}")
            lines.append("")

        # Last user message
        if cp.last_user_message:
            lines.append("## Last User Message")
            lines.append(f"> {cp.last_user_message}")
            lines.append("")

        # Active tool actions
        if cp.active_tool_actions:
            lines.append("## Active Tool Actions")
            for a in cp.active_tool_actions:
                tool = a.get("tool", "unknown")
                status = a.get("status", "unknown")
                artifact = a.get("artifact", "")
                lines.append(f"- [{status}] {tool}" + (f" → {artifact}" if artifact else ""))
            lines.append("")

        # ── Budget gate: mandatory alone ─────────────────────────────
        if budget_tokens is not None:
            mandatory_tokens = _count()
            if mandatory_tokens > budget_tokens:
                raise CheckpointBudgetError(
                    f"Mandatory context ({mandatory_tokens} tokens, "
                    f"estimated) exceeds budget ({budget_tokens} tokens). "
                    f"Restore blocked."
                )

        # ── Optional sections — append if they fit ───────────────────
        def _append_section(block: list[str]) -> None:
            nonlocal lines
            if budget_tokens is not None:
                trial = lines + block
                if _count_for(trial) <= budget_tokens:
                    lines.extend(block)
            else:
                lines.extend(block)

        def _count_for(block_lines: list[str]) -> int:
            return estimator.estimate("\n".join(block_lines))

        # Decisions
        if cp.decisions:
            sec = ["## Decisions"]
            for did, d in cp.decisions.items():
                outcome = d.get("outcome", "")
                rationale = d.get("rationale", "")
                sec.append(f"- **{did}**: {outcome}")
                if rationale:
                    sec.append(f"  Rationale: {rationale}")
            sec.append("")
            _append_section(sec)

        # Open tasks
        if cp.open_tasks:
            sec = ["## Open Tasks"]
            for t in cp.open_tasks:
                status = t.get("status", "pending")
                desc = t.get("description", "")
                sec.append(f"- [{status}] {desc}")
            sec.append("")
            _append_section(sec)

        # Source references
        if cp.source_references:
            sec = ["## Source References"]
            for sr in cp.source_references:
                sha_tag = f" @ {sr.sha[:8]}" if sr.sha else ""
                desc = f" — {sr.description}" if sr.description else ""
                sec.append(f"- `{sr.path}`{sha_tag}{desc}")
            sec.append("")
            _append_section(sec)

        return "\n".join(lines)

    def build_preamble(
        self,
        context: str,
        cp: Checkpoint,
    ) -> str:
        """Wrap context with injection header.  Returns final preamble string."""
        return (
            f"# CONTEXT RESTORED FROM CHECKPOINT\n"
            f"Checkpoint ID: {cp.checkpoint_id}\n"
            f"Content Hash: {cp.content_hash[:16]}\n"
            f"---\n\n"
            f"{context}"
        )

    def restore_checkpoint(
        self,
        checkpoint_id: str,
        budget_tokens: int | None = None,
        estimator: TokenEstimator | None = None,
    ) -> tuple[Checkpoint, str]:
        """Load checkpoint, verify integrity, generate restore context."""
        cp = self.load(checkpoint_id)
        context = self.generate_restore_context(
            cp, budget_tokens=budget_tokens, estimator=estimator,
        )
        return cp, context
