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

Format is stabilised at version 2.  Backward compatible with v1 for
the fields listed in CHECKPOINT_SCHEMA_V1.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any


# Canonical field list — validators and serializers depend on this order.
# V2 adds: constraints, last_user_message, active_tool_actions, content_hash.
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

# Fields considered mandatory for restore — must fit within budget.
MANDATORY_FIELDS: frozenset[str] = frozenset({
    "project_id", "project_name", "repo", "sha", "goals",
})


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
    """Versioned snapshot of session state for handover and restore.

    Fields:
        version: Format version (int). Currently 2.
        checkpoint_id: Random UUID — locator, not derived from content.
        content_hash: SHA-256 of canonical JSON (integrity proof).
        timestamp: ISO-8601 UTC timestamp.
        project_id: Memory project UUID (e.g. d5ae0938-...).
        project_name: Human-readable project name.
        repo: Repository path or URL.
        branch: Git branch name.
        sha: Git commit SHA (full 40-char hex).
        goals: Ordered list of goal strings.
        constraints: Ordered list of constraint/mandate strings.
        decisions: Dict of decision_id -> {rationale, outcome}.
        last_user_message: Verbatim last user message before checkpoint.
        open_tasks: List of {task_id, description, status}.
        active_tool_actions: List of {tool, status, artifact} for in-flight work.
        source_references: List of SourceReference anchors.
        context_budget_tokens: Maximum token budget for restore context.
        session_id: Origin session identifier.
    """

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
        # Compute content_hash if not set
        if not self.content_hash:
            self.content_hash = self._compute_content_hash()

    # ── Serialisation ──────────────────────────────────────────────────

    def to_json(self, indent: int = 2) -> str:
        """Serialise to JSON string.  Deterministic key order per schema."""
        d = self._to_ordered_dict()
        return json.dumps(d, indent=indent, ensure_ascii=False)

    def _to_ordered_dict(self) -> dict[str, Any]:
        """Build dict with keys in CHECKPOINT_SCHEMA order."""
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
        """Deserialise from JSON string.  Unknown keys are ignored."""
        d = json.loads(data)
        return cls.from_dict(d)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Checkpoint:
        """Deserialise from dict.  Unknown keys are ignored."""
        raw_refs = d.get("source_references", [])
        refs = [SourceReference.from_dict(r) for r in raw_refs if isinstance(r, dict)]
        cp = cls(**{k: v for k, v in d.items() if k in CHECKPOINT_SCHEMA})
        cp.source_references = refs
        return cp

    # ── Integrity ──────────────────────────────────────────────────────

    def _compute_content_hash(self) -> str:
        """SHA-256 of canonical JSON excluding checkpoint_id and content_hash.

        This ensures the hash is content-derived, not identity-derived.
        Two checkpoints with identical content but different IDs get the same hash.
        """
        d = self._to_ordered_dict()
        d.pop("checkpoint_id", None)
        d.pop("content_hash", None)
        canonical = json.dumps(d, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def get_content_hash(self) -> str:
        """Return stored content hash (SHA-256 of canonical JSON)."""
        return self.content_hash

    def verify_integrity(self) -> bool:
        """Verify stored content_hash matches computed hash.

        Raises CheckpointIntegrityError if mismatch (tampering detection).
        """
        computed = self._compute_content_hash()
        if computed != self.content_hash:
            raise CheckpointIntegrityError(
                f"Checkpoint {self.checkpoint_id} integrity check failed: "
                f"stored={self.content_hash[:16]}, computed={computed[:16]}"
            )
        return True

    def estimated_tokens(self) -> int:
        """Rough token estimate of the rendered restore context (4 chars ≈ 1 token).

        Uses the serialised checkpoint JSON as proxy for context size.
        """
        return len(self.to_json()) // 4

    def mandatory_token_estimate(self) -> int:
        """Token estimate of mandatory fields only.

        Used by the budget gate: if even mandatory content exceeds budget,
        restore is blocked (no compaction fallback can help).
        """
        mandatory = {k: getattr(self, k, None) for k in MANDATORY_FIELDS}
        return len(json.dumps(mandatory, sort_keys=True)) // 4
