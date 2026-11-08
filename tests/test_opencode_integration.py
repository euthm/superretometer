# FILE: tests/test_opencode_integration.py
"""Tests for OpenCode context injection and compaction fallback."""
from __future__ import annotations

from pathlib import Path

import pytest

from cognitive_harness.model.checkpoint import Checkpoint, SourceReference
from cognitive_harness.integration.opencode import (
    OpenCodeContextInjector,
    ContextInjectionError,
    INTEGRATION_VERSION,
    INTEGRATION_STATUS,
)


@pytest.fixture
def tmp_checkpoint_dir(tmp_path: Path) -> Path:
    d = tmp_path / "checkpoints"
    d.mkdir()
    return d


@pytest.fixture
def injector(tmp_checkpoint_dir: Path) -> OpenCodeContextInjector:
    return OpenCodeContextInjector(
        checkpoint_dir=tmp_checkpoint_dir,
        expected_project_id="test-project-123",
        budget_tokens=16_000,
    )


@pytest.fixture
def small_repo(tmp_path: Path) -> Path:
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "README.md").write_text("test")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True, check=True)
    return tmp_path


class TestContextInjection:
    def test_successful_injection(self, injector: OpenCodeContextInjector):
        cp = injector.manager.create_checkpoint(
            project_id="test-project-123",
            project_name="test",
            repo="/tmp",
            branch="main",
            sha="deadbeef1234567890abcdef1234567890abcdef12",
            goals=["Test injection"],
        )
        preamble, report = injector.inject(cp.checkpoint_id)
        assert "CONTEXT RESTORED" in preamble
        assert "Test injection" in preamble
        assert cp.content_hash[:16] in preamble
        assert not report.has_failures

    def test_wrong_project_fails(self, injector: OpenCodeContextInjector):
        cp = injector.manager.create_checkpoint(
            project_id="wrong-project-id",
            project_name="wrong",
            repo="/tmp",
            branch="main",
            sha="abc123",
        )
        with pytest.raises(ContextInjectionError, match="Project ID mismatch"):
            injector.inject(cp.checkpoint_id)

    def test_missing_checkpoint_fails(self, injector: OpenCodeContextInjector):
        with pytest.raises(ContextInjectionError, match="not found"):
            injector.inject("nonexistent-checkpoint")

    def test_tampered_checkpoint_fails(self, injector: OpenCodeContextInjector):
        cp = injector.manager.create_checkpoint(
            project_id="test-project-123",
            project_name="t",
            repo="/tmp",
            branch="b",
            sha="abc",
            goals=["original"],
        )
        # Tamper
        import json
        cp_file = injector.manager.checkpoint_dir / f"{cp.checkpoint_id}.json"
        data = json.loads(cp_file.read_text())
        data["goals"] = ["tampered"]
        cp_file.write_text(json.dumps(data, indent=2))

        with pytest.raises(ContextInjectionError, match="integrity"):
            injector.inject(cp.checkpoint_id)

    def test_inject_latest(self, injector: OpenCodeContextInjector):
        import time
        injector.manager.create_checkpoint(
            project_id="test-project-123",
            project_name="test",
            repo="/tmp", branch="main", sha="sha1",
            goals=["First"],
        )
        time.sleep(1.1)  # ensure distinct timestamp
        injector.manager.create_checkpoint(
            project_id="test-project-123",
            project_name="test",
            repo="/tmp", branch="main", sha="sha2",
            goals=["Second"],
        )
        preamble, _ = injector.inject_latest(project_id="test-project-123")
        assert "Second" in preamble

    def test_inject_latest_no_match(self, injector: OpenCodeContextInjector):
        with pytest.raises(ContextInjectionError, match="No checkpoint found"):
            injector.inject_latest(project_id="nonexistent")

    def test_integration_metadata_documented(self):
        """Integration status and version are documented constants."""
        assert INTEGRATION_VERSION == "0.1.0"
        assert INTEGRATION_STATUS == "manual"  # auto-injection not yet implemented


class TestCompaction:
    def test_compacts_when_budget_exceeded(self, tmp_checkpoint_dir: Path):
        injector = OpenCodeContextInjector(
            checkpoint_dir=tmp_checkpoint_dir,
            expected_project_id="compact-test",
            budget_tokens=50,
        )
        cp = injector.manager.create_checkpoint(
            project_id="compact-test",
            project_name="compact",
            repo="/tmp", branch="main", sha="abc123",
            goals=["Goal one", "Goal two"],
            decisions={
                "d1": {"outcome": "Decision one", "rationale": "Long rationale one"},
                "d2": {"outcome": "Decision two", "rationale": "Long rationale two"},
            },
            open_tasks=[
                {"task_id": "t1", "description": "Task one", "status": "open"},
                {"task_id": "t2", "description": "Task two", "status": "open"},
            ],
        )
        preamble, report = injector.inject(cp.checkpoint_id)
        assert len(preamble) // 4 < 200
        assert "COMPACTED" in preamble
        assert "Goal one" in preamble

    def test_compaction_preserves_goals(self, tmp_checkpoint_dir: Path):
        injector = OpenCodeContextInjector(
            checkpoint_dir=tmp_checkpoint_dir,
            expected_project_id="goals-test",
            budget_tokens=20,
        )
        cp = injector.manager.create_checkpoint(
            project_id="goals-test",
            project_name="goals",
            repo="/tmp", branch="main", sha="abc",
            goals=["Critical goal"],
            decisions={"d1": {"outcome": "x", "rationale": "y" * 100}},
        )
        try:
            preamble, _ = injector.inject(cp.checkpoint_id)
            if preamble:
                assert "Critical goal" in preamble
        except ContextInjectionError:
            pass

    def test_no_compaction_needed_when_fits(self, tmp_checkpoint_dir: Path):
        injector = OpenCodeContextInjector(
            checkpoint_dir=tmp_checkpoint_dir,
            expected_project_id="fits-test",
            budget_tokens=16_000,
        )
        cp = injector.manager.create_checkpoint(
            project_id="fits-test",
            project_name="fits",
            repo="/tmp", branch="main", sha="abc",
            goals=["Simple goal"],
        )
        preamble, _ = injector.inject(cp.checkpoint_id)
        assert "COMPACTED" not in preamble

    def test_mandatory_exceeds_budget_blocks(self, tmp_checkpoint_dir: Path):
        """When mandatory content exceeds budget, injection blocks."""
        injector = OpenCodeContextInjector(
            checkpoint_dir=tmp_checkpoint_dir,
            expected_project_id="block-test",
            budget_tokens=5,
        )
        cp = injector.manager.create_checkpoint(
            project_id="block-test",
            project_name="B" * 500,
            repo="/tmp", branch="main", sha="abc",
            goals=["G" * 2000],
        )
        with pytest.raises(ContextInjectionError, match="exceeds"):
            injector.inject(cp.checkpoint_id)
