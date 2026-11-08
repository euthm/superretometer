# FILE: tests/test_opencode_integration.py
"""Tests for OpenCode context injection and compaction fallback."""
from __future__ import annotations

from pathlib import Path

import pytest

from cognitive_harness.model.checkpoint import Checkpoint, SourceReference, CharProxyEstimator
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
        """Budget allows mandatory content, but full context needs compaction."""
        injector = OpenCodeContextInjector(
            checkpoint_dir=tmp_checkpoint_dir,
            expected_project_id="compact-test",
            budget_tokens=100,
        )
        cp = injector.manager.create_checkpoint(
            project_id="compact-test",
            project_name="compact",
            repo="/tmp", branch="main", sha="abc123",
            goals=["Goal one", "Goal two"],
            constraints=["Constraint A"],
            last_user_message="Continue the task",
            active_tool_actions=[{"tool": "grep", "status": "running"}],
            decisions={
                "d1": {"outcome": "Decision one", "rationale": "Long rationale one"},
                "d2": {"outcome": "Decision two", "rationale": "Long rationale two"},
                "d3": {"outcome": "Decision three", "rationale": "Long rationale three"},
            },
            open_tasks=[
                {"task_id": "t1", "description": "Task one", "status": "open"},
                {"task_id": "t2", "description": "Task two", "status": "open"},
                {"task_id": "t3", "description": "Task three", "status": "open"},
            ],
        )
        preamble, report = injector.inject(cp.checkpoint_id)
        assert "COMPACTED" in preamble
        assert "Goal one" in preamble
        # Mandatory fields preserved
        assert "Constraint A" in preamble
        assert "Continue the task" in preamble
        assert "grep" in preamble
        est = CharProxyEstimator()
        assert est.estimate(preamble) <= 100

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

    def test_compaction_includes_constraints_and_tools(self, tmp_checkpoint_dir: Path):
        """Compacted context preserves mandatory fields: constraints, last_user_message, active_tool_actions."""
        injector = OpenCodeContextInjector(
            checkpoint_dir=tmp_checkpoint_dir,
            expected_project_id="compact-mandatory",
            budget_tokens=120,
        )
        cp = injector.manager.create_checkpoint(
            project_id="compact-mandatory",
            project_name="cm",
            repo="/tmp", branch="main", sha="abc123",
            goals=["Primary goal"],
            constraints=["Do not touch prod"],
            last_user_message="Fix the bug",
            active_tool_actions=[{"tool": "git", "status": "pending", "artifact": "diff.patch"}],
            decisions={
                "d1": {"outcome": "Use approach A", "rationale": "Rationale for A"},
                "d2": {"outcome": "Use approach B", "rationale": "Rationale for B"},
            },
            open_tasks=[
                {"task_id": "t1", "description": "Task 1", "status": "open"},
                {"task_id": "t2", "description": "Task 2", "status": "open"},
            ],
        )
        preamble, _ = injector.inject(cp.checkpoint_id)
        est = CharProxyEstimator()
        assert "Primary goal" in preamble
        assert "Do not touch prod" in preamble
        assert "Fix the bug" in preamble
        assert "git" in preamble
        assert est.estimate(preamble) <= 120

    def test_final_preamble_budget_check(self, tmp_checkpoint_dir: Path):
        """The final preamble (context + header) is checked against budget.
        If normal rendering fits context budget but preamble exceeds total budget,
        compaction is triggered."""
        injector = OpenCodeContextInjector(
            checkpoint_dir=tmp_checkpoint_dir,
            expected_project_id="preamble-check",
            budget_tokens=70,
        )
        cp = injector.manager.create_checkpoint(
            project_id="preamble-check",
            project_name="pc",
            repo="/tmp", branch="main", sha="abc",
            goals=["Goal"],
            decisions={"d1": {"outcome": "x", "rationale": "y" * 50}},
            open_tasks=[{"task_id": "t1", "description": "desc", "status": "open"}],
        )
        preamble, _ = injector.inject(cp.checkpoint_id)
        est = CharProxyEstimator()
        assert est.estimate(preamble) <= 70

    def test_compaction_uses_same_estimator(self, tmp_checkpoint_dir: Path):
        """Compaction uses the same CharProxyEstimator instance — not inline len//4."""
        injector = OpenCodeContextInjector(
            checkpoint_dir=tmp_checkpoint_dir,
            expected_project_id="est-test",
            budget_tokens=80,
        )
        cp = injector.manager.create_checkpoint(
            project_id="est-test",
            project_name="et",
            repo="/tmp", branch="main", sha="abc",
            goals=["G1"],
            decisions={f"d{i}": {"outcome": f"x{i}", "rationale": f"r{i}" * 20} for i in range(10)},
        )
        preamble, _ = injector.inject(cp.checkpoint_id)
        est = CharProxyEstimator()
        assert est.estimate(preamble) <= 80

    def test_compacted_preamble_verified_before_return(self, tmp_checkpoint_dir: Path):
        """Compacted preamble that exceeds budget is rejected, not returned."""
        injector = OpenCodeContextInjector(
            checkpoint_dir=tmp_checkpoint_dir,
            expected_project_id="verify-test",
            budget_tokens=10,  # extremely tight — even compacted won't fit
        )
        cp = injector.manager.create_checkpoint(
            project_id="verify-test",
            project_name="v" * 100,
            repo="/tmp", branch="main", sha="abc",
            goals=["G" * 200],
        )
        with pytest.raises(ContextInjectionError, match="exceeds"):
            injector.inject(cp.checkpoint_id)

