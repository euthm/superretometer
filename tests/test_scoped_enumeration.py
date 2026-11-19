# FILE: tests/test_scoped_enumeration.py
"""Tests for scoped enumeration on bounded KO sets."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from cognitive_harness.analysis.scoped_enumeration import ScopedManifest, IncompleteEnumerationError
from cognitive_harness.model.ko import KnowledgeObject, KOType, EpistemicStatus, ConfidenceLevel, TruthCategory, Provenance


class TestScopedManifest:
    """ScopedManifest provides enumeration_complete semantics for bounded sets."""

    def _make_ko(self, ko_id: str, review_required: bool = False, anti_patterns: list | None = None) -> KnowledgeObject:
        return KnowledgeObject(
            id=ko_id,
            type=KOType.REQUIREMENT,
            title=f"KO {ko_id}",
            provenance=Provenance(source="test", author="test"),
            epistemic_status=EpistemicStatus.PROPOSED,
            confidence=ConfidenceLevel.SPECULATIVE,
            truth_category=TruthCategory.ASSUMPTION,
            review_required=review_required,
            review_reason="test reason" if review_required else "",
            anti_patterns=anti_patterns or [],
            relations=[],
        )

    def test_verify_completeness_all_present(self):
        kos = [self._make_ko("a"), self._make_ko("b")]
        storage = MagicMock()
        storage.get_ko = lambda x: {"a": kos[0], "b": kos[1]}.get(x)

        manifest = ScopedManifest(scope="test", kos=["a", "b"])
        missing = manifest.verify_completeness(storage)
        assert missing == []

    def test_verify_completeness_missing(self):
        kos = [self._make_ko("a")]
        storage = MagicMock()
        storage.get_ko = lambda x: kos[0] if x == "a" else None

        manifest = ScopedManifest(scope="test", kos=["a", "b"])
        missing = manifest.verify_completeness(storage)
        assert missing == ["b"]

    def test_list_review_required(self):
        kos = [
            self._make_ko("a", review_required=True),
            self._make_ko("b", review_required=False),
            self._make_ko("c", review_required=True),
        ]
        storage = MagicMock()
        storage.get_ko = lambda x: {"a": kos[0], "b": kos[1], "c": kos[2]}.get(x)

        manifest = ScopedManifest(scope="test", kos=["a", "b", "c"])
        result = manifest.list_review_required(storage)
        assert len(result) == 2
        ids = [r.id for r in result]
        assert "a" in ids
        assert "c" in ids
        assert "b" not in ids

    def test_list_review_required_incomplete_raises(self):
        storage = MagicMock()
        storage.get_ko = lambda x: None

        manifest = ScopedManifest(scope="test", kos=["a", "b"])
        with pytest.raises(IncompleteEnumerationError, match="2 KOs missing"):
            manifest.list_review_required(storage)

    def test_scan_anti_patterns(self):
        kos = [
            self._make_ko("a", anti_patterns=["circular_derivation"]),
            self._make_ko("b", anti_patterns=[]),
        ]
        storage = MagicMock()
        storage.get_ko = lambda x: {"a": kos[0], "b": kos[1]}.get(x)

        manifest = ScopedManifest(scope="test", kos=["a", "b"])
        findings = manifest.scan_anti_patterns(storage)
        assert len(findings) == 1
        assert findings[0]["ko_id"] == "a"
        assert "circular_derivation" in findings[0]["anti_patterns"]

    def test_scan_anti_patterns_incomplete_raises(self):
        storage = MagicMock()
        storage.get_ko = lambda x: None

        manifest = ScopedManifest(scope="test", kos=["a"])
        with pytest.raises(IncompleteEnumerationError):
            manifest.scan_anti_patterns(storage)

    def test_to_dict(self):
        manifest = ScopedManifest(scope="CP-010 to CP-013", kos=["a", "b", "c"], version="2.0.0")
        d = manifest.to_dict()
        assert d["scope"] == "CP-010 to CP-013"
        assert d["ko_count"] == 3
        assert d["version"] == "2.0.0"
        assert d["ko_ids"] == ["a", "b", "c"]
