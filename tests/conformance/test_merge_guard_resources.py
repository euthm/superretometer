"""HA regressions: expensive or interrupted evidence can never become approval."""
from __future__ import annotations

import importlib.util
import io
import itertools
import json
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from cognitive_harness.evidence.contracts import EvidenceError
from cognitive_harness.evidence import guard_runtime
from cognitive_harness.evidence.guard_runtime import (
    DEFAULT_LIMITS, Progress, enforce_receipt, enforce_sources, limits_for, supervise,
)

spec = importlib.util.spec_from_file_location(
    "resource_fixtures", Path(__file__).with_name("test_merge_guard.py"))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
fixture = fixtures.fixture
bounded_fixture = fixtures.bounded_fixture
guard = fixtures.guard
REMOTE = fixtures.REMOTE


def test_hrrm_scale_full_capture_rejects_before_record(fixture, monkeypatch):
    repo, commit, policy, root = fixture
    # Simulate the observed 570,510-file selection without constructing a real
    # enormous repository or hashing files. The full mode must stay full.
    monkeypatch.setattr(guard, "tracked_sources", lambda repo: ["input.txt"] * 570_510)
    monkeypatch.setattr(guard, "record", lambda *a: pytest.fail("Runner must not start"))
    with pytest.raises(EvidenceError, match="Source budget exceeded: 570510"):
        guard.capture(policy, repo, commit, REMOTE, root / "capture")
    assert "coverage_mode" not in policy
    assert not (root / "capture").exists()


def test_large_receipt_rejected_before_json_read_or_verification(fixture, monkeypatch):
    repo, commit, policy, root = fixture
    incoming = root / "incoming"
    incoming.mkdir()
    receipt = incoming / "run.json"
    # A sparse file models the reported 243.06 MB receipt; invalid bytes must
    # never be parsed, not merely fail JSON validation after an expensive read.
    with receipt.open("wb") as stream:
        stream.truncate(243_060_000)
    monkeypatch.setattr(guard, "load", lambda *a: pytest.fail("Must not read receipt"))
    monkeypatch.setattr(guard, "validate_run", lambda *a: pytest.fail("Must not verify"))
    with pytest.raises(EvidenceError, match="Receipt budget exceeded"):
        guard.check(policy, repo, commit, REMOTE, receipt, root / "check")
    assert receipt.stat().st_size == 243_060_000
    assert not (root / "check").exists()


def test_reviewed_bounded_set_fits_budget_and_keeps_controls(bounded_fixture):
    repo, commit, policy, root = bounded_fixture
    policy["resource_limits"] = {"max_source_files": 4}
    result = guard.capture(policy, repo, commit, REMOTE, root / "capture",
                           policy_file_path=repo / "merge_policy.json")
    checked = guard.check(policy, repo, commit, REMOTE, result["receipt"], root / "check",
                          policy_file_path=repo / "merge_policy.json")
    assert checked["approved"]
    assert all(checked["baseline"]["gates"][g]["status"] == "pass" for g in guard.GATES)
    mismatch, missing = checked["negative_controls"]
    assert mismatch["gates"]["test"]["status"] == "block" and not mismatch["approved"]
    assert missing["gates"]["test"]["status"] == "unknown" and not missing["approved"]


def test_changing_resource_budget_invalidates_policy_identity(fixture):
    repo, commit, policy, root = fixture
    result = guard.capture(policy, repo, commit, REMOTE, root / "capture")
    policy["resource_limits"] = {"max_source_files": 100}
    with pytest.raises(EvidenceError, match="Policy identity mismatch"):
        guard.check(policy, repo, commit, REMOTE, result["receipt"], root / "check")


def test_changing_operational_runtime_is_not_hidden_by_same_guard_script(fixture, monkeypatch):
    repo, commit, policy, root = fixture
    result = guard.capture(policy, repo, commit, REMOTE, root / "capture")
    monkeypatch.setattr(guard, "_runtime_source_sha", lambda: "0" * 64)
    with pytest.raises(EvidenceError, match="runtime identity mismatch"):
        guard.check(policy, repo, commit, REMOTE, result["receipt"], root / "check")


@pytest.mark.parametrize("field,value", [
    ("max_source_files", 0), ("max_source_files", True),
    ("max_source_files", 1.5), ("max_receipt_bytes", -1),
    ("operation_timeout_seconds", 0), ("operation_timeout_seconds", True),
    ("operation_timeout_seconds", float("nan")),
    ("operation_timeout_seconds", float("inf")),
])
def test_invalid_resource_limits_reject(field, value):
    with pytest.raises(EvidenceError, match="positive finite"):
        limits_for({"resource_limits": {field: value}})


@pytest.mark.parametrize("value", [None, [], {"typo": 10}])
def test_unknown_or_invalid_limit_block_rejects(value):
    with pytest.raises(EvidenceError, match="resource_limits"):
        limits_for({"resource_limits": value})


def test_limit_boundary_is_inclusive_and_explicit_increase_is_possible():
    limits = limits_for({})
    enforce_sources(limits["max_source_files"], limits)
    enforce_receipt(limits["max_receipt_bytes"], limits)
    with pytest.raises(EvidenceError):
        enforce_sources(limits["max_source_files"] + 1, limits)
    increased = limits_for({"resource_limits": {"max_source_files": 600_000}})
    enforce_sources(570_510, increased)
    assert DEFAULT_LIMITS["max_source_files"] == 10_000


def test_existing_output_rejects_before_verification_and_is_preserved(fixture, monkeypatch):
    repo, commit, policy, root = fixture
    output = root / "check"
    output.mkdir()
    sentinel = output / "existing.txt"
    sentinel.write_text("historical evidence")
    monkeypatch.setattr(guard, "validate_run", lambda *a: pytest.fail("Must reject early"))
    with pytest.raises(EvidenceError, match="already exists"):
        guard.check(policy, repo, commit, REMOTE, root / "missing/run.json", output)
    assert sentinel.read_text() == "historical evidence"


def cli(fixture, operation, *extra):
    repo, commit, policy, root = fixture
    policy_path = root / "policy.json"
    policy_path.write_text(json.dumps(policy))
    return [str(Path(guard.__file__)), operation, "--policy", str(policy_path),
            "--repo", str(repo), "--expected-commit", commit,
            "--expected-remote", REMOTE, "--output", str(root / operation), *extra]


def test_cli_preflight_is_read_only_and_stdout_is_one_json(fixture):
    proc = subprocess.run([sys.executable, *cli(fixture, "capture", "--preflight")],
                          capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    plan = json.loads(proc.stdout)
    assert plan["status"] == "preflight" and plan["approved"] is False
    assert plan["source_files"] == 3 and plan["coverage_mode"] == "full"
    assert not (fixture[3] / "capture").exists()
    assert '"phase": "preflight"' in proc.stderr


def test_cli_capture_reports_phases_without_changing_result(fixture):
    proc = subprocess.run([sys.executable, *cli(fixture, "capture")],
                          capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    result = json.loads(proc.stdout)
    assert result["capture"]["state"] == "complete"
    assert '"phase": "record"' in proc.stderr
    assert '"phase": "preflight"' in proc.stderr
    assert "ch-progress" not in proc.stdout


def test_cli_check_reports_each_control_and_final_json(fixture):
    repo, commit, policy, root = fixture
    result = guard.capture(policy, repo, commit, REMOTE, root / "captured")
    proc = subprocess.run([sys.executable, *cli(fixture, "check", "--receipt", result["receipt"])],
                          capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert json.loads(proc.stdout)["approved"] is True
    for control in ("baseline", "commit_mismatch", "missing_validator"):
        assert f'"control": "{control}"' in proc.stderr
    for phase in ("verify_receipt", "import", "export", "verify_bundle", "complete"):
        assert f'"phase": "{phase}"' in proc.stderr


def test_cli_deadline_rejects_instead_of_waiting_for_test_timeout(fixture):
    fixture[2]["command"][-1] = "timeout"
    fixture[2]["resource_limits"] = {"operation_timeout_seconds": 0.25}
    proc = subprocess.run([sys.executable, *cli(fixture, "capture")],
                          capture_output=True, text=True, timeout=10)
    assert proc.returncode != 0
    result = json.loads(proc.stdout)
    assert result["approved"] is False and "deadline exceeded" in result["reason"]


def test_cli_sigterm_returns_rejection_and_preserves_partial_output(fixture):
    fixture[2]["command"][-1] = "timeout"
    log_path = fixture[3] / "progress.log"
    with log_path.open("w") as log:
        proc = subprocess.Popen([sys.executable, *cli(fixture, "capture")],
                                stdout=subprocess.PIPE, stderr=log, text=True)
        try:
            until = time.monotonic() + 10
            while '"phase": "record"' not in log_path.read_text():
                assert proc.poll() is None, proc.communicate()[0]
                assert time.monotonic() < until, "Worker did not reach record"
                time.sleep(0.02)
            proc.send_signal(signal.SIGTERM)
            stdout, _ = proc.communicate(timeout=5)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
    result = json.loads(stdout)
    assert proc.returncode != 0 and result["approved"] is False
    assert "interrupted" in result["reason"]
    assert (fixture[3] / "capture").is_dir()


def test_timeout_discards_worker_approval_and_keeps_artifacts(tmp_path, capsys):
    artifact = tmp_path / "partial.txt"
    code = ("import time; from pathlib import Path; "
            f"Path({str(artifact)!r}).write_text('partial evidence'); "
            "print('{\"approved\":true}', flush=True); time.sleep(10)")
    with pytest.raises(EvidenceError, match="deadline exceeded"):
        supervise([sys.executable, "-c", code], 0.5,
                  progress=Progress(io.StringIO()), heartbeat_seconds=0.1)
    assert artifact.read_text() == "partial evidence"
    assert "approved" not in capsys.readouterr().out


def test_supervision_reports_heartbeat_and_retains_final_result():
    diagnostics = io.StringIO()
    code = "import time; time.sleep(0.25); print('{\"approved\":true}')"
    output, status = supervise([sys.executable, "-c", code], 5,
                              progress=Progress(diagnostics), heartbeat_seconds=0.05)
    assert status == 0 and json.loads(output)["approved"] is True
    assert '"phase": "waiting"' in diagnostics.getvalue()


def test_completion_observed_after_deadline_cannot_approve(monkeypatch):
    # A successful communicate() can return after the deadline due to OS
    # scheduling; success must still be checked against the monotonic deadline.
    clock = itertools.chain([0, 0], itertools.repeat(2))
    monkeypatch.setattr(guard_runtime, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    reporter = SimpleNamespace(emit=lambda *args, **kwargs: None)
    with pytest.raises(EvidenceError, match="deadline exceeded"):
        supervise([sys.executable, "-c", "print('{\"approved\":true}')"], 1,
                  progress=reporter)


def test_timeout_kills_descendant_process(tmp_path):
    pidfile = tmp_path / "child.pid"
    child = "import time; time.sleep(30)"
    code = ("import subprocess,sys,time; from pathlib import Path; "
            f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
            f"Path({str(pidfile)!r}).write_text(str(p.pid)); time.sleep(30)")
    with pytest.raises(EvidenceError, match="deadline exceeded"):
        supervise([sys.executable, "-c", code], 1, progress=Progress(io.StringIO()))
    pid = int(pidfile.read_text())
    state = Path(f"/proc/{pid}/stat")
    # An orphan awaiting PID 1's reap is no longer running either.
    def running():
        try:
            return not state.read_text().split(") ", 1)[1].startswith("Z")
        except FileNotFoundError:
            return False
    until = time.monotonic() + 1
    while running():
        assert time.monotonic() < until, "Descendant survived process-group termination"
        time.sleep(0.01)
    assert not running()
