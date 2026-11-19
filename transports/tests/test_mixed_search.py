# FILE: transports/tests/test_mixed_search.py
"""Regression tests for mixed CH/non-CH search results.

Covers:
  1. memory_object_to_ko with no CH provenance fields -> synthetic provenance
  2. _present_ko with None provenance -> graceful fallback
  3. query_semantic returning mixed results -> no crash
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


class TestNonCHProvenanceFallback:
    """memory_object_to_ko must not produce prov=None for non-CH objects."""

    def test_plain_memory_object_gets_synthetic_provenance(self):
        from transports.memory_adapter import memory_object_to_ko

        # Plain Memory object — no ch_ prefix, no provenance dict
        obj = {
            "id": str(uuid.uuid4()),
            "key": "cp-010-connector-liveness",
            "type": "Standard",
            "properties": {
                "cp_id": "CP-010",
                "status": "MERGED",
                "description": "BMS Connector Liveness",
            },
        }

        ko = memory_object_to_ko(obj)
        assert ko.provenance is not None
        assert ko.provenance.source == "memory_unadapted"
        assert ko.provenance.author == "system"
        assert ko.provenance.revision == 1
        assert ko.provenance.independent is False

    def test_ch_prefixed_object_preserves_original_provenance(self):
        from transports.memory_adapter import memory_object_to_ko

        now = datetime.now(timezone.utc)
        obj = {
            "id": str(uuid.uuid4()),
            "key": "ch:ko:test-cp-010",
            "type": "Concept",
            "properties": {
                "ch_ko_type": "finding",
                "ch_provenance_source": "spec_and_code",
                "ch_provenance_author": "kvasir",
                "ch_provenance_timestamp": now.isoformat(),
                "ch_provenance_revision": 2,
                "title": "CP-010 Liveness",
            },
        }

        ko = memory_object_to_ko(obj)
        assert ko.provenance.source == "spec_and_code"
        assert ko.provenance.author == "kvasir"
        assert ko.provenance.revision == 2

    def test_nested_provenance_dict_preserved(self):
        from transports.memory_adapter import memory_object_to_ko

        obj = {
            "id": str(uuid.uuid4()),
            "key": "legacy-ko",
            "type": "Concept",
            "properties": {
                "provenance": {
                    "source": "adopted",
                    "author": "system",
                    "timestamp": "2026-10-25T08:06:13.185490+00:00",
                    "revision": 1,
                },
                "ch_ko_type": "finding",
            },
        }

        ko = memory_object_to_ko(obj)
        assert ko.provenance.source == "adopted"
        assert ko.provenance.author == "system"


class TestPresentKoNoneProvenance:
    """_present_ko must handle None provenance gracefully."""

    def test_present_ko_with_none_provenance(self):
        from cognitive_harness.consumer.api import ConsumerAPI
        from cognitive_harness.model.ko import (
            KnowledgeObject,
            KOType,
            EpistemicStatus,
            ConfidenceLevel,
            TruthCategory,
        )

        ko = KnowledgeObject(
            id="test-123",
            type=KOType.REQUIREMENT,
            title="Test",
            provenance=None,  # Simulates a KO from a non-Memory adapter
        )

        api = ConsumerAPI.__new__(ConsumerAPI)
        result = api._present_ko(ko, summary=True)
        assert result["provenance"]["source"] == "unknown"
        assert result["provenance"]["author"] == "unknown"
        assert result["provenance"]["timestamp"] is None
        assert result["provenance"]["revision"] == 0


class TestMixedSearchResults:
    """query_semantic returning mixed CH and non-CH objects must not crash."""

    def test_query_with_mixed_results(self):
        from cognitive_harness.consumer.api import ConsumerAPI
        from cognitive_harness.orchestration.engine import OrchestrationEngine
        from transports.memory_adapter import MemoryAdapter, memory_object_to_ko

        # Simulate search returning both CH and non-CH objects
        mixed_objs = [
            {
                "id": str(uuid.uuid4()),
                "key": "cp-010-connector-liveness",
                "type": "Standard",
                "properties": {
                    "cp_id": "CP-010",
                    "status": "MERGED",
                },
            },
            {
                "id": str(uuid.uuid4()),
                "key": "ch:ko:validated-ko",
                "type": "Concept",
                "properties": {
                    "ch_ko_type": "conclusion",
                    "ch_provenance_source": "simulation",
                    "ch_provenance_author": "system",
                    "ch_provenance_timestamp": datetime.now(timezone.utc).isoformat(),
                    "title": "Validated finding",
                },
            },
        ]

        mock_storage = MagicMock(spec=MemoryAdapter)
        mock_storage.query_semantic = lambda q, v, l: [
            memory_object_to_ko(obj) for obj in mixed_objs
        ]

        mock_orchestrator = MagicMock(spec=OrchestrationEngine)
        api = ConsumerAPI(storage=mock_storage, orchestrator=mock_orchestrator)

        # Should not raise AttributeError on ko.provenance.source
        results = api.query("CP-010", limit=10)
        assert len(results) == 2
        assert results[0]["provenance"]["source"] == "memory_unadapted"
        assert results[1]["provenance"]["source"] == "simulation"
