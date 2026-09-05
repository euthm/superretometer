# FILE: cognitive-harness/model/tension.py
"""Tension — drives the reasoning loop.

A Tension may have multiple competing Threads attached. It only becomes
RESOLVED when all its Threads agree or when explicitly closed. This
preserves competing reasoning traces and their evidence."""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from enum import Enum


class TensionPriority(str, Enum):
    BLOCKER = "blocker"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TensionStatus(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    CONTESTED = "contested"    # multiple threads, competing conclusions
    RESOLVED = "resolved"


@dataclass
class Tension:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    description: str = ""
    ko_ids: list[str] = field(default_factory=list)
    viewpoint_ids: list[str] = field(default_factory=list)
    priority: TensionPriority = TensionPriority.MEDIUM
    status: TensionStatus = TensionStatus.OPEN
    thread_ids: list[str] = field(default_factory=list)
    resolution_ko_id: str = ""

    def is_contested(self) -> bool:
        return self.status == TensionStatus.CONTESTED
