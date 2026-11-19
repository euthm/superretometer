# FILE: cognitive-harness/analysis/scoped_enumeration.py
"""Scoped enumeration for CH analysis on bounded KO sets.

When enumeration_complete=False (e.g. MemoryAdapter), FULL_REQUIRED analyses
raise IncompleteEnumerationError.  Scoped enumeration provides a workaround:
a manifest explicitly enumerates every KO in scope, enabling analyses that
are provably complete within that scope.

Usage:
    manifest = ScopedManifest(scope="CP-010 to CP-013", kos=[uuid1, uuid2, ...])
    manifest.verify_completeness(adapter)  # raises if any KO missing
    review = manifest.list_review_required(adapter)
    anti = manifest.scan_anti_patterns(adapter)

The manifest is stored as a Conclusion-type KO with content describing the scope.
"""
from __future__ import annotations
from __future__ import annotations
from __future__ import annotations

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cognitive_harness.storage.interface import StorageInterface
    from cognitive_harness.model.ko import KnowledgeObject


class ScopedManifest:
    """An explicitly enumerated set of KOs that forms a provably complete scope."""

    def __init__(self, scope: str, kos: list[str], version: str = "1.0.0"):
        self.scope = scope
        self.ko_ids = list(kos)  # CH IDs or Memory UUIDs
        self.version = version

    @classmethod
    def create(cls, scope: str, kos: list[str], storage: "StorageInterface",
               version: str = "1.0.0") -> "ScopedManifest":
        """Create a scoped manifest and persist it as a KO."""
        manifest = cls(scope, kos, version)
        manifest._persist(storage)
        return manifest

    def _persist(self, storage: "StorageInterface") -> str:
        """Store manifest as a KO. Returns the KO's Memory UUID."""
        from cognitive_harness.model.ko import (
            KnowledgeObject, KOType, EpistemicStatus, ConfidenceLevel,
            TruthCategory, Provenance,
        )
        ko_id = str(uuid.uuid4())
        content = {
            "scope": self.scope,
            "version": self.version,
            "ko_ids": self.ko_ids,
            "type": "scoped_manifest",
        }
        ko = KnowledgeObject(
            id=ko_id,
            type=KOType.CONCLUSION,
            title=f"Scoped Manifest: {self.scope}",
            content=content,
            provenance=Provenance(source="scoped_manifest", author="system"),
            epistemic_status=EpistemicStatus.PROPOSED,
            confidence=ConfidenceLevel.HIGH,
            truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
            scope=self.scope,
        )
        mem_uuid = storage.create_ko(ko)
        self._mem_uuid = mem_uuid
        return mem_uuid

    def verify_completeness(self, storage: "StorageInterface") -> list[str]:
        """Return list of KO IDs that are missing from storage.

        Empty list means all KOs in scope are present and retrievable.
        """
        missing = []
        for ko_id in self.ko_ids:
            ko = storage.get_ko(ko_id)
            if ko is None:
                missing.append(ko_id)
        return missing

    def list_review_required(self, storage: "StorageInterface") -> list["KnowledgeObject"]:
        """List KOs within scope that require review.

        Unlike StorageInterface.list_review_required() (which requires
        enumeration_complete=True), this operates on the explicit set.
        """
        missing = self.verify_completeness(storage)
        if missing:
            raise IncompleteEnumerationError(
                f"Scoped enumeration incomplete: {len(missing)} KOs missing: {missing[:5]}"
            )
        result = []
        for ko_id in self.ko_ids:
            ko = storage.get_ko(ko_id)
            if ko and ko.review_required:
                result.append(ko)
        return result

    def scan_anti_patterns(self, storage: "StorageInterface") -> list[dict]:
        """Scan KOs within scope for anti-patterns.

        Returns list of findings: {ko_id, anti_patterns, details}.
        """
        missing = self.verify_completeness(storage)
        if missing:
            raise IncompleteEnumerationError(
                f"Scoped enumeration incomplete: {len(missing)} KOs missing"
            )
        findings = []
        for ko_id in self.ko_ids:
            ko = storage.get_ko(ko_id)
            if ko is None:
                continue
            if ko.anti_patterns:
                findings.append({
                    "ko_id": ko.id,
                    "title": ko.title,
                    "anti_patterns": ko.anti_patterns,
                    "epistemic_status": ko.epistemic_status.value if hasattr(ko.epistemic_status, 'value') else str(ko.epistemic_status),
                })
            # Check for self-referential support
            if ko.id in (r.to for r in ko.relations if r.type.value == "supports" or str(r.type) == "supports"):
                findings.append({
                    "ko_id": ko.id,
                    "title": ko.title,
                    "anti_patterns": ["self_referential_support"],
                    "details": "KO supports itself without independent evidence",
                })
        return findings

    def to_dict(self) -> dict:
        """Serialize manifest for reporting."""
        return {
            "scope": self.scope,
            "version": self.version,
            "ko_count": len(self.ko_ids),
            "ko_ids": self.ko_ids,
        }


class IncompleteEnumerationError(Exception):
    """Raised when scoped enumeration cannot guarantee completeness."""
    pass
