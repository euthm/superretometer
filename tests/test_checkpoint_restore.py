# FILE: tests/test_checkpoint_restore.py
"""Tests for checkpoint/restore mechanism (unit tests).

Covers:
- Checkpoint creation and serialisation (v2)
- Content hash independence from checkpoint ID
- Integrity verification and tampering detection
- Restore context generation with all v2 fields
- Validation: wrong project, stale SHA, missing sources, budget exceeded
- Roundtrip: create -> save -> load -> restore
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from cognitive_harness.model.checkpoint import (
    Checkpoint,
    SourceReference,
    CheckpointIntegrityError,
    CHECKPOINT_SCHEMA,
    CharProxyEstimator,
)
from cognitive_harness.orchestration.checkpoint_manager import (
    CheckpointManager,
    CheckpointError,
    CheckpointBudgetError,
)
from cognitive_harness.orchestration.restore_validator import (
    RestoreValidator,
    Severity,
    ValidationResult,
    ValidationReport,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_checkpoint_dir(tmp_path: Path) -> Path:
    d = tmp_path / "checkpoints"
    d.mkdir()
    return d


@pytest.fixture
def mgr(tmp_checkpoint_dir: Path) -> CheckpointManager:
    return CheckpointManager(checkpoint_dir=tmp_checkpoint_dir)


@pytest.fixture
def sample_checkpoint() -> Checkpoint:
    return Checkpoint(
        project_id="229d3378-5eda-42ab-9bfa-133f6360cd34",
        project_name="techhappens",
        repo="/home/egiuth/rocom-hrrm",
        branch="baseline/issue10",
        sha="861cb47fbc458a9d5d27ae2b99e0bbe522992138",
        goals=["Verify Issue #10 HTTP parity", "Close PostgreSQL persistence gap"],
        constraints=["Do not merge baseline/issue10 to main", "No production switching"],
        decisions={
            "pos-three-state": {
                "rationale": "Python pydantic model_fields_set distinguishes omit vs null",
                "outcome": "position uses three-state semantics",
            },
            "agent-id-two-state": {
                "rationale": "Python 'is not None' check treats None and omit identically",
                "outcome": "agentIdentity uses two-state semantics",
            },
        },
        last_user_message="Kjør en avgrenset #19-test av kontekstoverlevering.",
        open_tasks=[
            {"task_id": "pg-persist", "description": "Wire handlers to PostgreSQL", "status": "open"},
            {"task_id": "restart-test", "description": "Stop/start/GET survival test", "status": "open"},
        ],
        active_tool_actions=[
            {"tool": "grep", "status": "completed", "artifact": "90 contract matches found"},
        ],
        source_references=[
            SourceReference(
                path="rocom-server/tests/integration/http_parity_test.rs",
                sha="861cb47fbc",
                description="HTTP parity test — 7/7 pass",
            ),
            SourceReference(
                path="tests/evidence/issue10-context.json",
                sha="861cb47fbc",
                description="Handover context file",
            ),
        ],
        context_budget_tokens=16_000,
        session_id="test-session-001",
    )


# ── Creation and Serialisation ────────────────────────────────────────────


class TestCheckpointCreation:
    def test_create_checkpoint_persists(self, mgr: CheckpointManager, sample_checkpoint: Checkpoint):
        cp = mgr.create_checkpoint(
            project_id=sample_checkpoint.project_id,
            project_name=sample_checkpoint.project_name,
            repo=sample_checkpoint.repo,
            branch=sample_checkpoint.branch,
            sha=sample_checkpoint.sha,
            goals=sample_checkpoint.goals,
            constraints=sample_checkpoint.constraints,
            decisions=sample_checkpoint.decisions,
            last_user_message=sample_checkpoint.last_user_message,
            open_tasks=sample_checkpoint.open_tasks,
            active_tool_actions=sample_checkpoint.active_tool_actions,
            source_references=sample_checkpoint.source_references,
            session_id=sample_checkpoint.session_id,
        )
        assert cp.checkpoint_id
        assert cp.content_hash
        assert len(cp.content_hash) == 64
        assert cp.version == 2
        assert len(mgr.list_checkpoints()) == 1

    def test_json_schema_order(self, sample_checkpoint: Checkpoint):
        d = sample_checkpoint._to_ordered_dict()
        keys = list(d.keys())
        assert keys == CHECKPOINT_SCHEMA, f"Schema order mismatch: {keys}"

    def test_roundtrip_serialisation(self, sample_checkpoint: Checkpoint):
        json_str = sample_checkpoint.to_json()
        restored = Checkpoint.from_json(json_str)
        assert restored.project_id == sample_checkpoint.project_id
        assert restored.sha == sample_checkpoint.sha
        assert restored.goals == sample_checkpoint.goals
        assert restored.constraints == sample_checkpoint.constraints
        assert restored.last_user_message == sample_checkpoint.last_user_message
        assert len(restored.source_references) == len(sample_checkpoint.source_references)

    def test_content_hash_deterministic(self, sample_checkpoint: Checkpoint):
        h1 = sample_checkpoint.content_hash
        h2 = sample_checkpoint.content_hash
        assert h1 == h2
        assert len(h1) == 64

    def test_content_hash_independent_of_id(self):
        """Same content, different IDs → same content_hash."""
        cp1 = Checkpoint(
            checkpoint_id="aaaa",
            project_id="proj-1",
            sha="abc",
            repo="/r",
            goals=["g"],
        )
        cp2 = Checkpoint(
            checkpoint_id="bbbb",
            project_id="proj-1",
            sha="abc",
            repo="/r",
            goals=["g"],
        )
        assert cp1.content_hash == cp2.content_hash
        assert cp1.checkpoint_id != cp2.checkpoint_id

    def test_estimated_tokens(self, sample_checkpoint: Checkpoint):
        tokens = sample_checkpoint.estimated_tokens()
        assert 0 < tokens < 10_000

    def test_from_dict_ignores_unknown_keys(self):
        d = {
            "project_id": "test-123",
            "sha": "abc123",
            "repo": "/test",
            "unknown_field": "should be ignored",
        }
        cp = Checkpoint.from_dict(d)
        assert cp.project_id == "test-123"
        assert not hasattr(cp, "unknown_field")


# ── Integrity Verification ───────────────────────────────────────────────


class TestIntegrity:
    def test_valid_checkpoint_passes(self, sample_checkpoint: Checkpoint):
        assert sample_checkpoint.verify_integrity()

    def test_tampered_content_fails(self, sample_checkpoint: Checkpoint):
        sample_checkpoint.goals = ["Tampered"]
        with pytest.raises(CheckpointIntegrityError, match="integrity check failed"):
            sample_checkpoint.verify_integrity()

    def test_tampered_project_id_fails(self, sample_checkpoint: Checkpoint):
        sample_checkpoint.project_id = "tampered-id"
        with pytest.raises(CheckpointIntegrityError):
            sample_checkpoint.verify_integrity()

    def test_load_verifies_integrity(self, mgr: CheckpointManager):
        cp = mgr.create_checkpoint(
            project_id="integrity-test",
            project_name="I",
            repo="/r",
            branch="b",
            sha="abc",
            goals=["g"],
        )
        # Load verifies
        loaded = mgr.load(cp.checkpoint_id)
        assert loaded.checkpoint_id == cp.checkpoint_id

        # Tamper and try to load
        cp_file = mgr.checkpoint_dir / f"{cp.checkpoint_id}.json"
        data = json.loads(cp_file.read_text())
        data["goals"] = ["tampered"]
        cp_file.write_text(json.dumps(data, indent=2))

        with pytest.raises(CheckpointIntegrityError):
            mgr.load(cp.checkpoint_id)


# ── Restore Context Generation ───────────────────────────────────────────


class TestRestoreContext:
    def test_generate_context_includes_goals(self, mgr: CheckpointManager, sample_checkpoint: Checkpoint):
        mgr._save(sample_checkpoint)
        _, context = mgr.restore_checkpoint(sample_checkpoint.checkpoint_id)
        assert "Goals" in context
        assert "HTTP parity" in context

    def test_generate_context_includes_constraints(self, mgr: CheckpointManager, sample_checkpoint: Checkpoint):
        mgr._save(sample_checkpoint)
        _, context = mgr.restore_checkpoint(sample_checkpoint.checkpoint_id)
        assert "Constraints" in context
        assert "Do not merge" in context

    def test_generate_context_includes_last_message(self, mgr: CheckpointManager, sample_checkpoint: Checkpoint):
        mgr._save(sample_checkpoint)
        _, context = mgr.restore_checkpoint(sample_checkpoint.checkpoint_id)
        assert "Last User Message" in context
        assert "#19-test" in context

    def test_generate_context_includes_active_tools(self, mgr: CheckpointManager, sample_checkpoint: Checkpoint):
        mgr._save(sample_checkpoint)
        _, context = mgr.restore_checkpoint(sample_checkpoint.checkpoint_id)
        assert "Active Tool Actions" in context
        assert "grep" in context

    def test_generate_context_includes_decisions(self, mgr: CheckpointManager, sample_checkpoint: Checkpoint):
        mgr._save(sample_checkpoint)
        _, context = mgr.restore_checkpoint(sample_checkpoint.checkpoint_id)
        assert "Decisions" in context
        assert "three-state" in context

    def test_generate_context_includes_sources(self, mgr: CheckpointManager, sample_checkpoint: Checkpoint):
        mgr._save(sample_checkpoint)
        _, context = mgr.restore_checkpoint(sample_checkpoint.checkpoint_id)
        assert "Source References" in context
        assert "http_parity_test.rs" in context

    def test_empty_checkpoint_produces_minimal_context(self, mgr: CheckpointManager):
        cp = mgr.create_checkpoint(
            project_id="empty-test",
            project_name="empty",
            repo="/nonexistent",
            branch="main",
            sha="0000000000000000000000000000000000000000",
        )
        _, context = mgr.restore_checkpoint(cp.checkpoint_id)
        assert "# Checkpoint:" in context
        assert "# Project:" in context


# ── Budget Gate ──────────────────────────────────────────────────────────


class TestBudgetGate:
    def test_mandatory_exceeds_budget_raises(self, mgr: CheckpointManager):
        """When mandatory content alone exceeds budget, CheckpointBudgetError."""
        cp = mgr.create_checkpoint(
            project_id="big-mandatory",
            project_name="B" * 5000,  # project_name is mandatory
            repo="/r",
            branch="b",
            sha="abc",
            goals=["G" * 5000],  # goals are mandatory
        )
        with pytest.raises(CheckpointBudgetError):
            mgr.generate_restore_context(cp, budget_tokens=10)

    def test_budget_gate_passes_when_fits(self, mgr: CheckpointManager):
        cp = mgr.create_checkpoint(
            project_id="small",
            project_name="S",
            repo="/r",
            branch="b",
            sha="abc",
            goals=["small goal"],
        )
        context = mgr.generate_restore_context(cp, budget_tokens=16_000)
        assert context

    def test_mandatory_first_rendering_order(self, mgr: CheckpointManager):
        """Mandatory sections appear before optional sections in rendered context."""
        cp = mgr.create_checkpoint(
            project_id="order-test",
            project_name="ot",
            repo="/r", branch="b", sha="abc",
            goals=["Goal"],
            constraints=["Must do X"],
            last_user_message="Proceed",
            active_tool_actions=[{"tool": "t", "status": "s"}],
            decisions={"d1": {"outcome": "opt"}},
            open_tasks=[{"task_id": "t1", "description": "opt", "status": "pending"}],
        )
        context = mgr.generate_restore_context(cp)
        # Mandatory sections must appear before optional
        goals_pos = context.index("## Goals")
        constraints_pos = context.index("## Constraints")
        msg_pos = context.index("## Last User Message")
        tools_pos = context.index("## Active Tool Actions")
        dec_pos = context.index("## Decisions")
        tasks_pos = context.index("## Open Tasks")
        assert goals_pos < constraints_pos < msg_pos < tools_pos < dec_pos < tasks_pos

    def test_optional_dropped_when_budget_tight(self, mgr: CheckpointManager):
        """When budget is tight, optional sections are dropped but mandatory preserved."""
        cp = mgr.create_checkpoint(
            project_id="drop-test",
            project_name="dt",
            repo="/r", branch="b", sha="abc",
            goals=["Goal"],
            constraints=["Constraint"],
            last_user_message="Message",
            active_tool_actions=[{"tool": "t", "status": "running"}],
            decisions={f"d{i}": {"outcome": f"outcome {i}", "rationale": "x" * 200} for i in range(10)},
            open_tasks=[{"task_id": f"t{i}", "description": "d" * 100, "status": "open"} for i in range(10)],
        )
        context = mgr.generate_restore_context(cp, budget_tokens=80)
        # Mandatory fields present
        assert "Goal" in context
        assert "Constraint" in context
        assert "Message" in context
        assert "Active Tool Actions" in context
        # Optional may be dropped
        est = CharProxyEstimator()
        assert est.estimate(context) <= 80

    def test_same_estimator_across_stages(self, mgr: CheckpointManager, sample_checkpoint: Checkpoint):
        """Validation, rendering, and estimation use the same estimator instance."""
        validator = RestoreValidator(
            expected_project_id=sample_checkpoint.project_id,
            budget_tokens=16_000,
        )
        report = validator.validate(sample_checkpoint)
        est = CharProxyEstimator()
        context = mgr.generate_restore_context(
            sample_checkpoint, estimator=est
        )
        context_tokens = est.estimate(context)
        assert report.context_tokens == context_tokens



# ── Validation ───────────────────────────────────────────────────────────


class TestValidationPass:
    def test_valid_checkpoint_passes(self, sample_checkpoint: Checkpoint, tmp_path: Path):
        for sr in sample_checkpoint.source_references:
            p = tmp_path / sr.path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()
        validator = RestoreValidator(
            expected_project_id=sample_checkpoint.project_id,
            budget_tokens=16_000,
            git_repo_path=str(tmp_path),
        )
        report = validator.validate(sample_checkpoint)
        assert not report.has_failures

    def test_is_safe_to_restore(self, sample_checkpoint: Checkpoint, tmp_path: Path):
        for sr in sample_checkpoint.source_references:
            p = tmp_path / sr.path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()
        validator = RestoreValidator(
            expected_project_id=sample_checkpoint.project_id,
            budget_tokens=16_000,
            git_repo_path=str(tmp_path),
        )
        report = validator.validate(sample_checkpoint)
        assert not report.has_failures
        assert report.is_safe_to_restore


class TestValidationFailures:
    def test_wrong_project_id_fails(self, sample_checkpoint: Checkpoint):
        validator = RestoreValidator(expected_project_id="00000000-0000-0000-0000-000000000000")
        report = validator.validate(sample_checkpoint)
        assert report.has_failures
        proj_results = [r for r in report.results if r.check_name == "project_id"]
        assert proj_results[0].severity == Severity.FAIL

    def test_missing_required_fields_fails(self):
        cp = Checkpoint(project_id="", sha="", repo="")
        validator = RestoreValidator()
        report = validator.validate(cp)
        req_results = [r for r in report.results if r.check_name == "required_fields"]
        assert req_results[0].severity == Severity.FAIL

    def test_budget_exceeded_warns(self):
        """Budget exceeded is a warning (compaction can fix), not a failure."""
        big_goals = ["goal " + "x" * 1000] * 50
        cp = Checkpoint(project_id="budget-test", sha="abc123", repo="/test", goals=big_goals)
        validator = RestoreValidator(budget_tokens=100)
        report = validator.validate(cp)
        budget_results = [r for r in report.results if r.check_name == "context_budget"]
        assert budget_results[0].severity == Severity.WARNING
        assert not report.has_failures

    def test_missing_source_references_fail(self, sample_checkpoint: Checkpoint, tmp_path: Path):
        cp = Checkpoint(
            project_id="src-test",
            sha="abc123",
            repo="",
            source_references=[
                SourceReference(path="definitely/does/not/exist.rs", description="Missing"),
            ],
        )
        validator = RestoreValidator(git_repo_path=str(tmp_path))
        report = validator.validate(cp)
        src_results = [r for r in report.results if r.check_name == "source_references"]
        assert src_results[0].severity == Severity.FAIL

    def test_tampered_checkpoint_fails(self, sample_checkpoint: Checkpoint):
        sample_checkpoint.goals = ["tampered"]
        validator = RestoreValidator()
        report = validator.validate(sample_checkpoint)
        integrity_results = [r for r in report.results if r.check_name == "integrity"]
        assert integrity_results[0].severity == Severity.FAIL
        assert report.has_failures

    def test_stale_sha_warns(self, tmp_path: Path):
        cp = Checkpoint(
            project_id="sha-test",
            sha="0000000000000000000000000000000000000000",
            repo="",
            branch="main",
        )
        validator = RestoreValidator(git_repo_path=str(tmp_path))
        report = validator.validate(cp)
        sha_results = [r for r in report.results if r.check_name == "sha_freshness"]
        assert sha_results[0].severity in (Severity.WARNING, Severity.PASS)

    def test_no_project_id_set_warns(self, sample_checkpoint: Checkpoint):
        validator = RestoreValidator(expected_project_id="")
        report = validator.validate(sample_checkpoint)
        proj_results = [r for r in report.results if r.check_name == "project_id"]
        assert proj_results[0].severity == Severity.WARNING


class TestValidationEdgeCases:
    def test_large_context_warns_near_budget(self):
        medium_goals = ["goal " + "x" * 200] * 10
        cp = Checkpoint(project_id="near-budget", sha="abc123", repo="/test", goals=medium_goals)
        estimated = cp.estimated_tokens()
        validator = RestoreValidator(budget_tokens=int(estimated / 0.85))
        report = validator.validate(cp)
        budget_results = [r for r in report.results if r.check_name == "context_budget"]
        assert budget_results[0].severity == Severity.WARNING

    def test_version_too_new_warns(self):
        cp = Checkpoint(version=99, project_id="ver-test", sha="abc", repo="/test")
        validator = RestoreValidator()
        report = validator.validate(cp)
        ver_results = [r for r in report.results if r.check_name == "version"]
        assert ver_results[0].severity == Severity.WARNING

    def test_version_zero_fails(self):
        cp = Checkpoint(version=0, project_id="ver-test", sha="abc", repo="/test")
        validator = RestoreValidator()
        report = validator.validate(cp)
        ver_results = [r for r in report.results if r.check_name == "version"]
        assert ver_results[0].severity == Severity.FAIL

    def test_report_to_json(self, sample_checkpoint: Checkpoint, tmp_path: Path):
        for sr in sample_checkpoint.source_references:
            p = tmp_path / sr.path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()
        validator = RestoreValidator(
            expected_project_id=sample_checkpoint.project_id,
            git_repo_path=str(tmp_path),
        )
        report = validator.validate(sample_checkpoint)
        json_str = report.to_json()
        d = json.loads(json_str)
        assert "checkpoint_id" in d
        assert "results" in d
        assert len(d["results"]) > 0


# ── Integration: Full Roundtrip ──────────────────────────────────────────


class TestRoundtrip:
    def test_create_save_load_restore(self, mgr: CheckpointManager, tmp_path: Path):
        """Full cycle: create -> save -> load (integrity) -> validate -> restore context."""
        cp = mgr.create_checkpoint(
            project_id="roundtrip-test",
            project_name="test-project",
            repo=str(tmp_path),
            branch="main",
            sha="deadbeef1234567890abcdef1234567890abcdef12",
            goals=["Test roundtrip"],
            constraints=["No merge to main"],
            decisions={"dec1": {"rationale": "test", "outcome": "ok"}},
            last_user_message="Restore this context",
            open_tasks=[{"task_id": "t1", "description": "verify", "status": "pending"}],
            active_tool_actions=[{"tool": "test", "status": "running"}],
            session_id="roundtrip-session",
        )

        # Load — verifies integrity automatically
        loaded = mgr.load(cp.checkpoint_id)
        assert loaded.checkpoint_id == cp.checkpoint_id
        assert loaded.content_hash == cp.content_hash

        # Validate
        validator = RestoreValidator(expected_project_id=cp.project_id)
        report = validator.validate(loaded)
        req_results = [r for r in report.results if r.check_name == "required_fields"]
        assert req_results[0].severity == Severity.PASS

        # Restore context
        _, context = mgr.restore_checkpoint(cp.checkpoint_id)
        assert "Test roundtrip" in context
        assert "No merge to main" in context
        assert "Restore this context" in context

    def test_list_checkpoints(self, mgr: CheckpointManager):
        mgr.create_checkpoint(
            project_id="list-1", project_name="p1", repo="/r", branch="b", sha="s1",
        )
        mgr.create_checkpoint(
            project_id="list-2", project_name="p2", repo="/r", branch="b", sha="s2",
        )
        listed = mgr.list_checkpoints()
        assert len(listed) == 2
        assert all("checkpoint_id" in entry for entry in listed)
        assert all("content_hash" in entry for entry in listed)


# ── SourceReference ──────────────────────────────────────────────────────


class TestSourceReference:
    def test_to_dict_roundtrip(self):
        sr = SourceReference(
            path="src/test.rs",
            sha="abc123",
            line_range=(10, 50),
            description="Test file",
        )
        d = sr.to_dict()
        restored = SourceReference.from_dict(d)
        assert restored.path == sr.path
        assert restored.sha == sr.sha
        assert restored.line_range == sr.line_range
        assert restored.description == sr.description

    def test_from_dict_missing_optional(self):
        d = {"path": "only-path.txt"}
        sr = SourceReference.from_dict(d)
        assert sr.path == "only-path.txt"
        assert sr.sha is None
        assert sr.line_range is None
        assert sr.description == ""


# ── Hash Missing Check ───────────────────────────────────────────────────


class TestHashMissing:
    def test_missing_hash_rejected(self):
        """A checkpoint loaded from JSON without content_hash is rejected."""
        d = {
            "project_id": "test-123",
            "sha": "abc123",
            "repo": "/test",
            "content_hash": "",  # missing
        }
        cp = Checkpoint.from_dict(d)
        validator = RestoreValidator()
        report = validator.validate(cp)
        hash_results = [r for r in report.results if r.check_name == "hash_present"]
        assert hash_results[0].severity == Severity.FAIL
        assert report.has_failures

    def test_missing_hash_key_rejected(self):
        """A checkpoint loaded from JSON without content_hash key is rejected."""
        d = {
            "project_id": "test-123",
            "sha": "abc123",
            "repo": "/test",
            # no content_hash key at all
        }
        cp = Checkpoint.from_dict(d)
        validator = RestoreValidator()
        report = validator.validate(cp)
        hash_results = [r for r in report.results if r.check_name == "hash_present"]
        assert hash_results[0].severity == Severity.FAIL

    def test_present_hash_accepted(self):
        """A checkpoint with a valid content_hash passes the hash_present check."""
        cp = Checkpoint(
            project_id="test-123",
            sha="abc123",
            repo="/test",
            goals=["g"],
        )
        # Save and reload (hash present in source)
        import tempfile
        from cognitive_harness.orchestration.checkpoint_manager import CheckpointManager
        with tempfile.TemporaryDirectory() as tmp:
            mgr = CheckpointManager(checkpoint_dir=Path(tmp))
            mgr._save(cp)
            loaded = mgr.load(cp.checkpoint_id)
            validator = RestoreValidator()
            report = validator.validate(loaded)
            hash_results = [r for r in report.results if r.check_name == "hash_present"]
            assert hash_results[0].severity == Severity.PASS


# ── Custom Estimator ──────────────────────────────────────────────────────


class TestCustomEstimator:
    def test_validator_uses_custom_estimator(self, sample_checkpoint: Checkpoint):
        """A custom estimator is used by the validator for budget checks."""
        class StrictEstimator:
            is_exact = False
            def estimate(self, text: str) -> int:
                # 2 chars per token — much stricter than default
                return max(1, len(text) // 2)

        validator = RestoreValidator(
            budget_tokens=100,
            estimator=StrictEstimator(),
        )
        report = validator.validate(sample_checkpoint)
        budget_results = [r for r in report.results if r.check_name == "context_budget"]
        assert budget_results[0].severity == Severity.WARNING
        assert report.context_tokens > 100

    def test_injector_uses_custom_estimator(self, tmp_checkpoint_dir: Path):
        """The injector propagates a custom estimator through all stages."""
        from cognitive_harness.integration.opencode import OpenCodeContextInjector

        class StrictEstimator:
            is_exact = False
            def estimate(self, text: str) -> int:
                return max(1, len(text) // 2)

        injector = OpenCodeContextInjector(
            checkpoint_dir=tmp_checkpoint_dir,
            expected_project_id="est-test",
            budget_tokens=500,
            estimator=StrictEstimator(),
        )
        cp = injector.manager.create_checkpoint(
            project_id="est-test",
            project_name="test",
            repo="/tmp", branch="main", sha="abc123",
            goals=["Goal"],
        )
        preamble, report = injector.inject(cp.checkpoint_id)
        assert "CONTEXT RESTORED" in preamble

    def test_custom_estimator_affects_compaction(self, tmp_checkpoint_dir: Path):
        """A stricter estimator forces compaction at higher budget."""
        from cognitive_harness.integration.opencode import OpenCodeContextInjector

        class StrictEstimator:
            is_exact = False
            def estimate(self, text: str) -> int:
                return max(1, len(text) // 2)

        injector = OpenCodeContextInjector(
            checkpoint_dir=tmp_checkpoint_dir,
            expected_project_id="compact-est",
            budget_tokens=200,
            estimator=StrictEstimator(),
        )
        cp = injector.manager.create_checkpoint(
            project_id="compact-est",
            project_name="ce",
            repo="/tmp", branch="main", sha="abc",
            goals=["G1"],
            constraints=["C1"],
            last_user_message="Message",
            active_tool_actions=[{"tool": "t", "status": "s"}],
            decisions={f"d{i}": {"outcome": f"x{i}", "rationale": "r" * 30} for i in range(10)},
            open_tasks=[{"task_id": f"t{i}", "description": "d" * 20, "status": "open"} for i in range(10)],
        )
        preamble, _ = injector.inject(cp.checkpoint_id)
        est = StrictEstimator()
        assert est.estimate(preamble) <= 200
