# FILE: cognitive-harness/model/checkpoint.py
"""Checkpoint — versioned context snapshot for session handover.

A checkpoint captures the minimal state needed to restore a reasoning
session: goals, constraints, decisions, open tasks, project identity,
code provenance, active tool state, last user message, and source
references.  It is serialised to JSON and can be written to disk or
embedded in a handover file.

Identity model:
    checkpoint_id — random UUID, stable across serialisation.
    content_hash  — SHA-256 over canonical JSON (excludes checkpoint_id).
    These are independent: the ID locates the file, the hash verifies integrity.

Token estimation:
    CharProxyEstimator is the sole estimator (len(text) // 4).
    The same instance is used by validation, compaction, and final
    budget check — no divergence between stages.

    This is NOT a model tokenizer.  Production deployments should pass
    a model-specific estimator (e.g., tiktoken) via the TokenEstimator
    protocol to get hard token counts.

Format is stabilised at version 2.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


CHECKPOINT_SCHEMA: list[str] = [
    "version",
    "checkpoint_id",
    "content_hash",
    "timestamp",
    "project_id",
    "project_name",
    "repo",
    "branch",
    "sha",
    "goals",
    "constraints",
    "decisions",
    "last_user_message",
    "open_tasks",
    "active_tool_actions",
    "source_references",
    "context_budget_tokens",
    "session_id",
]


class TokenEstimator(Protocol):
    """Estimate token count for a text string."""

    def estimate(self, text: str) -> int: ...

    @property
    def is_exact(self) -> bool: ...


class CharProxyEstimator:
    """len(text) // 4 token estimate.

    Applied identically in validation, compaction, and final budget gate.
    Not a model tokenizer — production should substitute a real one.
    """

    is_exact = False

    def estimate(self, text: str) -> int:
        return max(1, len(text) // 4)


class CheckpointIntegrityError(Exception):
    """Raised when content_hash verification fails on load."""


@dataclass
class SourceReference:
    """A provenance anchor: path, SHA, and optional line range."""

    path: str
    sha: str | None = None
    line_range: tuple[int, int] | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"path": self.path}
        if self.sha:
            d["sha"] = self.sha
        if self.line_range:
            d["line_range"] = list(self.line_range)
        if self.description:
            d["description"] = self.description
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SourceReference:
        lr = d.get("line_range")
        if isinstance(lr, list):
            lr = tuple(lr)
        return cls(
            path=d["path"],
            sha=d.get("sha"),
            line_range=lr,
            description=d.get("description", ""),
        )


@dataclass
class Checkpoint:
    """Versioned snapshot of session state for handover and restore."""

    version: int = 2
    checkpoint_id: str = ""
    content_hash: str = ""
    timestamp: str = ""
    project_id: str = ""
    project_name: str = ""
    repo: str = ""
    branch: str = ""
    sha: str = ""
    goals: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_user_message: str = ""
    open_tasks: list[dict[str, Any]] = field(default_factory=list)
    active_tool_actions: list[dict[str, Any]] = field(default_factory=list)
    source_references: list[SourceReference] = field(default_factory=list)
    context_budget_tokens: int = 16_000
    session_id: str = ""

    def __post_init__(self):
        if not self.checkpoint_id:
            self.checkpoint_id = secrets.token_hex(8)
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self.content_hash:
            self.content_hash = self._compute_content_hash()

    def to_json(self, indent: int = 2) -> str:
        d = self._to_ordered_dict()
        return json.dumps(d, indent=indent, ensure_ascii=False)

    def _to_ordered_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        for key in CHECKPOINT_SCHEMA:
            val = getattr(self, key, None)
            if key == "source_references" and val:
                d[key] = [sr.to_dict() for sr in val]
            else:
                d[key] = val
        return d

    @classmethod
    def from_json(cls, data: str) -> Checkpoint:
        d = json.loads(data)
        return cls.from_dict(d)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Checkpoint:
        raw_refs = d.get("source_references", [])
        refs = [SourceReference.from_dict(r) for r in raw_refs if isinstance(r, dict)]
        cp = cls(**{k: v for k, v in d.items() if k in CHECKPOINT_SCHEMA})
        cp.source_references = refs
        # Track whether the source had a content_hash
        if not d.get("content_hash"):
            cp._hash_missing_in_source = True
        else:
            cp._hash_missing_in_source = False
        return cp

    def _compute_content_hash(self) -> str:
        d = self._to_ordered_dict()
        d.pop("checkpoint_id", None)
        d.pop("content_hash", None)
        canonical = json.dumps(d, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def get_content_hash(self) -> str:
        return self.content_hash

    def verify_integrity(self) -> bool:
        computed = self._compute_content_hash()
        if computed != self.content_hash:
            raise CheckpointIntegrityError(
                f"Checkpoint {self.checkpoint_id} integrity check failed: "
                f"stored={self.content_hash[:16]}, computed={computed[:16]}"
            )
        return True

    def estimated_tokens(
        self,
        estimator: TokenEstimator | None = None,
    ) -> int:
        """Estimate tokens of the full rendered context.

        Delegates to CheckpointManager.generate_restore_context(), then
        applies the estimator.  Default: CharProxyEstimator.
        """
        if estimator is None:
            estimator = CharProxyEstimator()
        from cognitive_harness.orchestration.checkpoint_manager import CheckpointManager
        mgr = CheckpointManager()
        context = mgr.generate_restore_context(self)
        return estimator.estimate(context)
