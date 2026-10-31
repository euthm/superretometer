# FILE: transports/tests/test_persistence_fixes.py
"""Regression tests for MemoryAdapter persistence fixes.

Validates:
  1. Response.__bool__ fix — HTTP 404 with falsey response is handled.
  2. independent=None — missing provenance independence flag stays None.
  3. create_ko persists ch_memory_uuid — POST is followed by PATCH.
  4. _resolve_ch_id fallback — ch_memory_uuid read from properties.

Uses controlled HTTP fixtures — no AI1/Memory server required.
"""
from __future__ import annotations

import uuid as uuidmod
from unittest.mock import MagicMock, patch

import pytest
import requests


class _FakeResponse:
    """Mimics requests.Response.__bool__ — false for >= 400."""

    def __init__(self, status_code: int):
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def __bool__(self) -> bool:
        return 200 <= self.status_code < 400


class TestResponseBoolFix:
    """get_ko must handle falsey Response objects (HTTP 404)."""

    def test_404_with_falsey_response_returns_none(self):
        from transports.memory_adapter import MemoryAdapter

        adapter = MemoryAdapter.__new__(MemoryAdapter)
        adapter._headers = {}
        adapter.server_url = "http://test"
        adapter._ko_id_map = {}
        adapter._memory_id_map = {}

        # Mock _resolve_ch_id to return the input (simulating empty cache)
        fake_id = str(uuidmod.uuid4())
        adapter._resolve_ch_id = lambda x: x

        # Mock _get to raise HTTPError with a falsey 404 response
        fake_resp = _FakeResponse(404)
        http_err = requests.HTTPError(response=fake_resp)
        adapter._get = MagicMock(side_effect=http_err)

        # Verify the response is falsey (the root cause)
        assert not fake_resp, "Test setup: 404 response must be falsey"

        result = adapter.get_ko(fake_id)
        assert result is None, "get_ko must return None for 404, not crash"

    def test_401_with_falsey_response_raises(self):
        from transports.memory_adapter import MemoryAdapter

        adapter = MemoryAdapter.__new__(MemoryAdapter)
        adapter._headers = {}
        adapter.server_url = "http://test"
        adapter._ko_id_map = {}
        adapter._memory_id_map = {}

        fake_id = str(uuidmod.uuid4())
        adapter._resolve_ch_id = lambda x: x

        # 401 is not handled — should propagate
        fake_resp = _FakeResponse(401)
        http_err = requests.HTTPError(response=fake_resp)
        adapter._get = MagicMock(side_effect=http_err)

        with pytest.raises(requests.HTTPError):
            adapter.get_ko(fake_id)


class TestIndependentNone:
    """Missing independent flag must not assert independence."""

    def test_missing_independent_is_none(self):
        from transports.memory_adapter import memory_object_to_ko

        obj = {
            "key": "ch:ko:test",
            "properties": {
                "ch_ko_type": "finding",
                "title": "test",
                "ch_provenance_source": "manual",
                "ch_provenance_author": "test",
                "ch_provenance_timestamp": "2026-01-01T00:00:00+00:00",
                # No ch_provenance_independent
            },
        }
        ko = memory_object_to_ko(obj)
        assert ko.provenance is not None
        assert ko.provenance.independent is None, (
            f"Missing independent flag should be None, got {ko.provenance.independent!r}"
        )

    def test_explicit_independent_true_is_preserved(self):
        from transports.memory_adapter import memory_object_to_ko

        obj = {
            "key": "ch:ko:test",
            "properties": {
                "ch_ko_type": "finding",
                "title": "test",
                "ch_provenance_source": "manual",
                "ch_provenance_author": "test",
                "ch_provenance_timestamp": "2026-01-01T00:00:00+00:00",
                "ch_provenance_independent": True,
            },
        }
        ko = memory_object_to_ko(obj)
        assert ko.provenance.independent is True

    def test_explicit_independent_false_is_preserved(self):
        from transports.memory_adapter import memory_object_to_ko

        obj = {
            "key": "ch:ko:test",
            "properties": {
                "ch_ko_type": "finding",
                "title": "test",
                "ch_provenance_source": "manual",
                "ch_provenance_author": "test",
                "ch_provenance_timestamp": "2026-01-01T00:00:00+00:00",
                "ch_provenance_independent": False,
            },
        }
        ko = memory_object_to_ko(obj)
        assert ko.provenance.independent is False


class TestCreateKoMemoryUUID:
    """create_ko must persist ch_memory_uuid via PATCH."""

    def test_create_ko_patches_ch_memory_uuid(self):
        from transports.memory_adapter import MemoryAdapter
        from cognitive_harness.model.ko import KnowledgeObject, KOType

        adapter = MemoryAdapter.__new__(MemoryAdapter)
        adapter._headers = {}
        adapter.server_url = "http://test"
        adapter.project_id = "test-project"
        adapter._ko_id_map = {}
        adapter._memory_id_map = {}
        adapter._created_ids = set()

        ko = KnowledgeObject(type=KOType.FINDING, title="test")
        mem_uuid = str(uuidmod.uuid4())

        # Mock _post to return controlled UUID
        adapter._post = MagicMock(return_value={"id": mem_uuid})
        adapter._patch = MagicMock()
        adapter._resolve_ch_id = lambda x: x
        adapter._create_edge = MagicMock()

        result = adapter.create_ko(ko)
        assert result == mem_uuid

        # Verify PATCH was called with ch_memory_uuid
        adapter._patch.assert_called_once()
        call_args = adapter._patch.call_args
        assert "properties" in call_args[0][1]
        props = call_args[0][1]["properties"]
        assert props.get("ch_memory_uuid") == mem_uuid

    def test_create_ko_raises_on_patch_failure(self):
        from transports.memory_adapter import MemoryAdapter
        from cognitive_harness.model.ko import KnowledgeObject, KOType

        adapter = MemoryAdapter.__new__(MemoryAdapter)
        adapter._headers = {}
        adapter.server_url = "http://test"
        adapter.project_id = "test-project"
        adapter._ko_id_map = {}
        adapter._memory_id_map = {}
        adapter._created_ids = set()

        ko = KnowledgeObject(type=KOType.FINDING, title="test")
        mem_uuid = str(uuidmod.uuid4())

        adapter._post = MagicMock(return_value={"id": mem_uuid})

        # PATCH fails with HTTPError
        fake_resp = _FakeResponse(500)
        http_err = requests.HTTPError(response=fake_resp)
        adapter._patch = MagicMock(side_effect=http_err)
        adapter._resolve_ch_id = lambda x: x
        adapter._create_edge = MagicMock()

        with pytest.raises(RuntimeError, match="ch_memory_uuid"):
            adapter.create_ko(ko)


class TestResolveChIdFallback:
    """_resolve_ch_id reads ch_memory_uuid from properties."""

    def test_resolve_reads_ch_memory_uuid_from_direct_fetch(self):
        from transports.memory_adapter import MemoryAdapter

        adapter = MemoryAdapter.__new__(MemoryAdapter)
        adapter._headers = {}
        adapter.server_url = "http://test"
        adapter.project_id = "test-project"
        adapter._ko_id_map = {}
        adapter._memory_id_map = {}
        adapter._lookup_by_key = MagicMock(return_value=None)

        ch_id = str(uuidmod.uuid4())
        mem_uuid = str(uuidmod.uuid4())

        # Direct UUID fetch returns object with ch_memory_uuid
        adapter._get = MagicMock(return_value={
            "id": ch_id,
            "key": f"ch:ko:{ch_id}",
            "properties": {"ch_memory_uuid": mem_uuid},
        })

        result = adapter._resolve_ch_id(ch_id)
        assert result == mem_uuid, (
            f"_resolve_ch_id should return ch_memory_uuid ({mem_uuid}), got {result}"
        )

        # Verify cache was populated
        assert adapter._ko_id_map[ch_id] == mem_uuid
        assert adapter._memory_id_map[mem_uuid] == ch_id
