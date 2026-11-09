# FILE: tests/test_checkpoint_subprocess.py
"""Subprocess tests for checkpoint/restore full chain.

Tests the CLI end-to-end: create → exit → load → validate → render.
Each test runs the CLI as a separate process to simulate real session
handover (process restart, no shared state).

Covers:
- Happy path: create → list → restore → inject
- Wrong project ID
- Manipulated checkpoint (tampered content)
- Budget exceeded (mandatory content too large)
- Missing checkpoint
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


CLI = [sys.executable, "-m", "cognitive_harness.cli"]


def test_timestamp_is_integrity_protected_without_a_wall_clock_race():
    from cognitive_harness.model.checkpoint import Checkpoint, CheckpointIntegrityError
    first = Checkpoint(project_id="hash-fixture", timestamp="2026-11-09T00:00:00Z")
    second = Checkpoint(project_id="hash-fixture", timestamp="2026-11-09T00:00:01Z")
    assert first.content_hash != second.content_hash
    first.timestamp = second.timestamp
    with pytest.raises(CheckpointIntegrityError):
        first.verify_integrity()


def run_checkpoint(*args, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    """Run the checkpoint CLI subcommand."""
    cmd = [*CLI, "checkpoint", *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        check=check,
    )


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """Isolated working directory with checkpoint storage."""
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir()
    return tmp_path


# ── Happy Path ───────────────────────────────────────────────────────────


class TestHappyPath:
    def test_create_list_restore_inject(self, workdir: Path):
        """Full chain: create → list → restore → inject, all in separate processes."""
        cp_dir = workdir / "checkpoints"

        # 1. Create checkpoint
        create = run_checkpoint(
            "create",
            "--project-id", "test-123",
            "--project-name", "TestProject",
            "--repo", str(workdir),
            "--branch", "main",
            "--sha", "deadbeef1234567890abcdef1234567890abcdef12",
            "--goal", "Verify checkpoint handover",
            "--constraint", "Do not merge to main",
            "--last-message", "Kjør en avgrenset #19-test",
            "--task", json.dumps({"task_id": "t1", "description": "Verify restore", "status": "open"}),
            "--output-dir", str(cp_dir),
            cwd=workdir,
        )
        assert create.returncode == 0
        create_data = json.loads(create.stdout)
        cp_id = create_data["checkpoint_id"]
        content_hash = create_data["content_hash"]
        assert cp_id
        assert len(content_hash) == 64

        # 2. List checkpoints
        listing = run_checkpoint("list", "--output-dir", str(cp_dir), cwd=workdir)
        assert listing.returncode == 0
        cp_list = json.loads(listing.stdout)
        assert len(cp_list) >= 1
        assert any(c["checkpoint_id"] == cp_id for c in cp_list)

        # 3. Restore (validate + render)
        restore = run_checkpoint(
            "restore", cp_id,
            "--project-id", "test-123",
            "--budget", "16000",
            "--output-dir", str(cp_dir),
            cwd=workdir,
        )
        assert restore.returncode == 0
        restore_data = json.loads(restore.stdout.split("\n--- RENDERED CONTEXT ---\n")[0].strip())
        assert restore_data["safe_to_restore"]
        assert not restore_data["has_failures"]
        # Context should include our fields
        assert "Verify checkpoint handover" in restore.stdout
        assert "Do not merge to main" in restore.stdout

        # 4. Inject (preamble output)
        inject = run_checkpoint(
            "inject", cp_id,
            "--project-id", "test-123",
            "--budget", "16000",
            "--output-dir", str(cp_dir),
            cwd=workdir,
        )
        assert inject.returncode == 0
        assert "CONTEXT RESTORED" in inject.stdout
        assert cp_id in inject.stdout
        assert content_hash[:16] in inject.stdout

    def test_content_hash_stable(self, workdir: Path):
        """Reload the SAME persisted checkpoint in a fresh process.

        Creating another checkpoint also creates another timestamp; comparing
        those hashes made this test depend on crossing a wall-clock second.
        """
        cp_dir = workdir / "checkpoints"

        r1 = run_checkpoint(
            "create",
            "--project-id", "stable-hash",
            "--project-name", "HashTest",
            "--repo", str(workdir),
            "--branch", "main",
            "--sha", "aaa123",
            "--goal", "Stable goal",
            "--output-dir", str(cp_dir),
            cwd=workdir,
        )
        created = json.loads(r1.stdout)
        stored = cp_dir / f"{created['checkpoint_id']}.json"
        before = stored.read_bytes()
        r2 = subprocess.run(
            [sys.executable, "-c",
             "import json,sys; from pathlib import Path; "
             "from cognitive_harness.orchestration.checkpoint_manager import CheckpointManager; "
             "cp=CheckpointManager(checkpoint_dir=Path(sys.argv[1])).load(sys.argv[2]); "
             "print(json.dumps({'checkpoint_id':cp.checkpoint_id,'content_hash':cp.content_hash}))",
             str(cp_dir), created["checkpoint_id"]],
            cwd=workdir, capture_output=True, text=True, check=True,
        )
        loaded = json.loads(r2.stdout)
        assert loaded == {k: created[k] for k in ("checkpoint_id", "content_hash")}
        assert stored.read_bytes() == before


# ── Negative Cases ──────────────────────────────────────────────────────


class TestNegativeCases:
    def test_wrong_project_id_blocks_restore(self, workdir: Path):
        """Wrong project ID → validation failure → restore blocked."""
        cp_dir = workdir / "checkpoints"

        run_checkpoint(
            "create",
            "--project-id", "real-project",
            "--project-name", "P",
            "--repo", str(workdir),
            "--branch", "b",
            "--sha", "abc",
            "--output-dir", str(cp_dir),
            cwd=workdir,
        )
        listing = run_checkpoint(
            "list", "--output-dir", str(cp_dir), cwd=workdir
        )
        cp_id = json.loads(listing.stdout)[0]["checkpoint_id"]

        restore = run_checkpoint(
            "restore", cp_id,
            "--project-id", "wrong-project",
            "--output-dir", str(cp_dir),
            cwd=workdir,
            check=False,
        )
        assert restore.returncode == 2  # validation failure exit code
        data = json.loads(restore.stdout)
        assert data["has_failures"]

    def test_tampered_checkpoint_fails_integrity(self, workdir: Path):
        """Manipulated checkpoint file → integrity check fails."""
        cp_dir = workdir / "checkpoints"

        # Create a valid checkpoint
        r = run_checkpoint(
            "create",
            "--project-id", "tamper-test",
            "--project-name", "T",
            "--repo", str(workdir),
            "--branch", "b",
            "--sha", "abc",
            "--goal", "Original goal",
            "--output-dir", str(cp_dir),
            cwd=workdir,
        )
        cp_id = json.loads(r.stdout)["checkpoint_id"]

        # Tamper with the file
        cp_file = cp_dir / f"{cp_id}.json"
        data = json.loads(cp_file.read_text())
        data["goals"] = ["Tampered goal"]
        cp_file.write_text(json.dumps(data, indent=2))  # hash is stale

        # Restore should fail integrity check — load fails before validation
        restore = run_checkpoint(
            "restore", cp_id,
            "--output-dir", str(cp_dir),
            cwd=workdir,
            check=False,
        )
        assert restore.returncode != 0
        assert "integrity" in restore.stderr

    def test_missing_checkpoint_fails(self, workdir: Path):
        """Non-existent checkpoint ID → error."""
        cp_dir = workdir / "checkpoints"
        cp_dir.mkdir(exist_ok=True)

        restore = run_checkpoint(
            "restore", "nonexistent-id",
            "--output-dir", str(cp_dir),
            cwd=workdir,
            check=False,
        )
        assert restore.returncode != 0

    def test_budget_exceeded_mandatory_blocks(self, workdir: Path):
        """When mandatory content exceeds budget, restore is blocked."""
        cp_dir = workdir / "checkpoints"

        # Create a checkpoint with very long goals (mandatory content)
        long_goal = "G" * 10000  # ~2500 tokens just for goals
        r = run_checkpoint(
            "create",
            "--project-id", "budget-test",
            "--project-name", "BudgetTest",
            "--repo", str(workdir),
            "--branch", "b",
            "--sha", "abc",
            "--goal", long_goal,
            "--budget", "16000",
            "--output-dir", str(cp_dir),
            cwd=workdir,
        )
        cp_id = json.loads(r.stdout)["checkpoint_id"]

        # Try to restore with a budget too small for mandatory content
        restore = run_checkpoint(
            "restore", cp_id,
            "--budget", "10",  # tiny budget
            "--output-dir", str(cp_dir),
            cwd=workdir,
            check=False,
        )
        assert restore.returncode == 3  # budget blocked
        assert "BUDGET BLOCKED" in restore.stderr


# ── CLI Help and Version ─────────────────────────────────────────────────


class TestCLI:
    def test_checkpoint_help(self, workdir: Path):
        r = subprocess.run(
            [*CLI, "checkpoint", "--help"],
            capture_output=True, text=True, cwd=str(workdir),
        )
        assert r.returncode == 0
        assert "create" in r.stdout
        assert "list" in r.stdout
        assert "restore" in r.stdout
        assert "inject" in r.stdout

    def test_version(self, workdir: Path):
        r = subprocess.run(
            [*CLI, "--version"],
            capture_output=True, text=True, cwd=str(workdir),
        )
        assert r.returncode == 0

    def test_evidence_routing(self, workdir: Path):
        """CLI evidence subcommand is routed — delegates to evidence CLI."""
        r = subprocess.run(
            [*CLI, "evidence", "verify", "--help"],
            capture_output=True, text=True, cwd=str(workdir),
        )
        assert r.returncode == 0
        assert "verify" in r.stdout or "Check receipt" in r.stdout

    def test_main_commands_present(self, workdir: Path):
        """Main CLI help lists evidence, checkpoint, and mcp."""
        r = subprocess.run(
            [*CLI, "--help"],
            capture_output=True, text=True, cwd=str(workdir),
        )
        assert r.returncode == 0
        assert "evidence" in r.stdout
        assert "checkpoint" in r.stdout
        assert "mcp" in r.stdout

    def test_restore_cli_rejects_missing_hash(self, workdir: Path):
        """superretometer checkpoint restore rejects a file with missing content_hash."""
        cp_dir = workdir / "checkpoints"

        r = subprocess.run(
            [*CLI, "checkpoint", "create",
             "--project-id", "hash-test", "--project-name", "H",
             "--repo", "/r", "--branch", "b", "--sha", "abc",
             "--goal", "G", "--output-dir", str(cp_dir)],
            capture_output=True, text=True, cwd=str(workdir),
        )
        assert r.returncode == 0
        cp_id = json.loads(r.stdout)["checkpoint_id"]

        cp_file = cp_dir / f"{cp_id}.json"
        data = json.loads(cp_file.read_text())
        data["content_hash"] = ""
        cp_file.write_text(json.dumps(data))

        r = subprocess.run(
            [*CLI, "checkpoint", "restore", cp_id,
             "--output-dir", str(cp_dir)],
            capture_output=True, text=True, cwd=str(workdir),
        )
        assert r.returncode != 0
        assert "missing content_hash" in r.stderr
