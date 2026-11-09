"""The merge adapter must reject absent/weakened/stale evidence, not just exit 0.

Synthetic runner fixtures exercise orchestration; they are not product test data.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from cognitive_harness.evidence import record
from cognitive_harness.evidence.contracts import EvidenceError

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("ch_merge_guard", ROOT / "scripts/ch_merge_guard.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)
REMOTE = "https://example.invalid/public/merge-fixture.git"

RUNNER = '''import json,sys,time
from pathlib import Path
out=Path(sys.argv[1]); mode=sys.argv[2]
if mode == 'timeout': time.sleep(5)
if mode == 'dirty': Path('input.txt').write_text('changed during run')
if mode != 'absent':
    if mode == 'counts':
        (out/'results.json').write_text(json.dumps({'schema_version':'counts/v1',
          'counts':{'discovered':3,'executed':3,'passed':3,'failed':0,'skipped':0},
          'test_ids':['suite::a','suite::b','suite::c']}))
    else:
        names=['a','b','c'] if mode != 'wrong_ids' else ['x','y','z']
        cases=[]
        for name in names:
            body='<skipped/>' if mode == 'skip' and name == 'a' else ''
            if mode == 'failed' and name == 'a': body='<failure/>'
            cases.append('<testcase classname="suite" name="'+name+'">'+body+'</testcase>')
        if mode == 'optional': cases.append('<testcase classname="suite" name="optional"><skipped/></testcase>')
        (out/'results.xml').write_text('<testsuite>'+''.join(cases)+'</testsuite>')
print('synthetic runner observation, not application evidence')
sys.exit(1 if mode == 'failed' else 0)
'''


@pytest.fixture
def fixture(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args]).decode().strip()
    git("init", "-q")
    git("config", "user.name", "Merge fixture")
    git("config", "user.email", "fixture@example.invalid")
    git("remote", "add", "origin", REMOTE)
    (repo / "runner.py").write_text(RUNNER)
    (repo / "input.txt").write_text("measured input")
    (repo / "fixture.lock").write_text("fixture=1")
    git("add", ".")
    git("commit", "-qm", "Synthetic fixture")
    policy = {"schema_version": "ch-merge-policy/v1",
              "command": [sys.executable, "{repo}/runner.py", "{output}", "pass"],
              "parser": {"kind": "junit/v1", "report": "results.xml"},
              "minimum_executed": 3, "required_test_ids": ["suite::a", "suite::b", "suite::c"],
              "allowed_skipped_ids": [], "lockfiles": ["fixture.lock"],
              "timeout_seconds": 2, "scope": "Synthetic merge-guard orchestration fixture only"}
    return repo, git("rev-parse", "HEAD"), policy, tmp_path


def captured(fixture, mode="pass", policy=None):
    repo, commit, original, root = fixture
    policy = copy.deepcopy(policy or original)
    policy["command"][-1] = mode
    result = guard.capture(policy, repo, commit, REMOTE, root / "capture")
    assert Path(result["receipt"]).is_file()
    assert Path(result["receipt"]) == root / "capture/receipt/run.json"
    return root / "capture/receipt", policy


def test_positive_bundle_and_isolated_negative_controls(fixture):
    repo, commit, _, root = fixture
    receipt, policy = captured(fixture)
    result = guard.check(policy, repo, commit, REMOTE, receipt, root / "verified")
    assert result["approved"] is True
    assert result["commit"] == commit
    assert result["baseline"]["warrant"]["warrant_status"] == "conditionally_warranted"
    assert all(result["baseline"]["gates"][g]["status"] == "pass" for g in guard.GATES)
    mismatch, missing = result["negative_controls"]
    assert mismatch["gates"]["test"]["status"] == "block" and not mismatch["approved"]
    assert missing["gates"]["test"]["status"] == "unknown" and not missing["approved"]
    assert (root / "verified/bundle/SHA256SUMS").is_file()
    assert json.loads((root / "verified/merge-result.json").read_text())["receipt_sha256"] == result["receipt_sha256"]


@pytest.mark.parametrize("mode", ["absent", "failed", "wrong_ids", "dirty", "timeout"])
def test_incomplete_or_failing_run_cannot_become_approval(fixture, mode):
    repo, commit, _, root = fixture
    receipt, policy = captured(fixture, mode)
    with pytest.raises(EvidenceError):
        guard.check(policy, repo, commit, REMOTE, receipt, root / "verified")
    assert not (root / "verified/merge-result.json").exists()


@pytest.mark.parametrize("mutation", ["commit", "remote", "tamper", "floor", "policy", "missing", "stale"])
def test_external_bindings_and_bytes_are_mandatory(fixture, mutation):
    repo, commit, _, root = fixture
    receipt, policy = captured(fixture)
    remote = REMOTE
    if mutation == "commit": commit = "0" * 40
    elif mutation == "remote": remote = "https://example.invalid/other.git"
    elif mutation == "tamper": (receipt / "logs/stdout.log").write_text("changed")
    elif mutation == "floor": policy["minimum_executed"] = 4
    elif mutation == "policy": policy["required_test_ids"] = ["suite::a"]
    elif mutation == "missing": (receipt / "run.json").unlink()
    elif mutation == "stale": (repo / "input.txt").write_text("later change")
    with pytest.raises(EvidenceError):
        guard.check(policy, repo, commit, remote, receipt, root / "verified")


@pytest.mark.parametrize("required", [False, True])
def test_skip_exceptions_cannot_hide_required_regressions(fixture, required):
    repo, commit, policy, root = fixture
    policy["minimum_executed"] = 2
    policy["allowed_skipped_ids"] = ["suite::a" if required else "suite::optional"]
    receipt, policy = captured(fixture, "skip", policy)
    with pytest.raises(EvidenceError, match="skipped"):
        guard.check(policy, repo, commit, REMOTE, receipt, root / "verified")


def test_named_optional_skip_is_explicit_and_retained(fixture):
    repo, commit, policy, root = fixture
    policy["allowed_skipped_ids"] = ["suite::optional"]
    receipt, policy = captured(fixture, "optional", policy)
    result = guard.check(policy, repo, commit, REMOTE, receipt, root / "verified")
    assert result["counts"]["skipped"] == 1
    assert result["counts"]["executed"] == 3


def test_counts_protocol_is_usable_by_non_python_runners(fixture):
    repo, commit, policy, root = fixture
    policy["parser"] = {"kind": "counts-json/v1", "report": "results.json"}
    receipt, policy = captured(fixture, "counts", policy)
    assert guard.check(policy, repo, commit, REMOTE, receipt, root / "verified")["approved"]


def test_underdeclared_source_coverage_is_rejected(fixture):
    repo, commit, policy, root = fixture
    # A valid #18 receipt with insufficient scope must still fail the stricter
    # merge adapter. Do not reinterpret the existing generic receipt contract.
    profile = {"repo": str(repo), "source_paths": ["runner.py"], "lockfiles": ["fixture.lock"],
               "archive": {"path": str(root / "archive"), "locator": "fixture://test", "retention": "fixture only"},
               "claim": {"title": "Fixture", "scope": policy["scope"], "declared_remote": REMOTE,
                         "requested_commit": commit, "falsifier": "Any failed assertion"},
               "acceptance": guard.acceptance_rules(policy), "parser": policy["parser"],
               "environment": {"tools": {}, "services": {}, "exclusions": ["synthetic fixture"]},
               "timeout_seconds": policy["timeout_seconds"]}
    run = record(profile, policy["command"])
    with pytest.raises(EvidenceError, match="omits tracked"):
        guard.check(policy, repo, commit, REMOTE, run["receipt"], root / "verified")


@pytest.mark.parametrize("field,value", [("minimum_executed", 0), ("minimum_executed", True),
                                          ("required_test_ids", []), ("schema_version", "future/v9")])
def test_weakened_or_unknown_policy_is_rejected(fixture, field, value):
    _, _, policy, root = fixture
    policy[field] = value
    path = root / "policy.json"
    path.write_text(json.dumps(policy))
    with pytest.raises(EvidenceError): guard.policy_at(path)


def test_cli_missing_receipt_is_a_nonzero_rejection(fixture, capsys):
    repo, commit, policy, root = fixture
    path = root / "policy.json"
    path.write_text(json.dumps(policy))
    code = guard.main(["check", "--policy", str(path), "--repo", str(repo),
                       "--expected-commit", commit, "--expected-remote", REMOTE,
                       "--output", str(root / "verified")])
    assert code != 0
    assert json.loads(capsys.readouterr().out)["approved"] is False


## ---- Bounded coverage mode tests ----

@pytest.fixture
def bounded_fixture(tmp_path):
    """Fixture with test_runner.py, input.txt, merge_policy.json, and fixture.lock."""
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args]).decode().strip()
    git("init", "-q")
    git("config", "user.name", "Merge fixture")
    git("config", "user.email", "fixture@example.invalid")
    git("remote", "add", "origin", REMOTE)
    (repo / "test_runner.py").write_text(RUNNER)
    (repo / "input.txt").write_text("measured input")
    (repo / "fixture.lock").write_text("fixture=1")
    # Policy file tracked in the worktree
    policy_data = {"schema_version": "ch-merge-policy/v1",
                   "command": [sys.executable, "{repo}/test_runner.py", "{output}", "pass"],
                   "parser": {"kind": "junit/v1", "report": "results.xml"},
                   "minimum_executed": 3, "required_test_ids": ["suite::a", "suite::b", "suite::c"],
                   "allowed_skipped_ids": [], "lockfiles": ["fixture.lock"],
                   "timeout_seconds": 2, "scope": "Synthetic merge-guard orchestration fixture only"}
    (repo / "merge_policy.json").write_text(json.dumps(policy_data))
    git("add", ".")
    git("commit", "-qm", "Synthetic fixture with policy")
    # Bounded policy
    bounded_policy = {**policy_data,
                      "coverage_mode": "bounded",
                      "source_paths": ["test_runner.py", "input.txt", "fixture.lock", "merge_policy.json"],
                      "coverage_rationale": "Test fixture: only these 4 files are relevant to the synthetic runner."}
    return repo, git("rev-parse", "HEAD"), bounded_policy, tmp_path


def test_bounded_coverage_capture_and_check(bounded_fixture):
    """Bounded coverage with all required files passes full capture → check."""
    repo, commit, policy, root = bounded_fixture
    policy["command"][-1] = "pass"
    result = guard.capture(policy, repo, commit, REMOTE, root / "capture")
    assert Path(result["receipt"]).is_file()
    receipt = root / "capture/receipt/run.json"
    check_result = guard.check(policy, repo, commit, REMOTE, receipt, root / "verified")
    assert check_result["approved"] is True
    assert check_result["counts"]["passed"] == 3


def test_bounded_coverage_records_guard_identity(bounded_fixture):
    """Capture stores the guard SHA in environment.tools['ch_merge_guard']."""
    repo, commit, policy, root = bounded_fixture
    policy["command"][-1] = "pass"
    result = guard.capture(policy, repo, commit, REMOTE, root / "capture")
    receipt_path = root / "capture/receipt/run.json"
    receipt_data = json.loads(receipt_path.read_text())
    guard_sha = receipt_data["environment"]["tools"]["ch_merge_guard"]
    assert guard_sha is not None
    assert len(guard_sha) == 64  # SHA-256 hex
    # Verify it matches the current guard
    expected = guard._guard_source_sha()
    assert guard_sha == expected


def test_bounded_missing_runner_is_rejected(bounded_fixture):
    """Bounded source_paths without test_runner.py when runner is tracked must fail."""
    repo, commit, policy, root = bounded_fixture
    # Remove runner from source_paths but leave it tracked
    policy["source_paths"] = ["input.txt", "fixture.lock", "merge_policy.json"]
    with pytest.raises(EvidenceError, match="missing required runner"):
        guard.capture(policy, repo, commit, REMOTE, root / "capture")


def test_bounded_missing_policy_file_is_rejected(bounded_fixture):
    """Bounded source_paths without merge_policy.json when tracked must fail."""
    repo, commit, policy, root = bounded_fixture
    # Remove policy from source_paths but leave it tracked
    policy["source_paths"] = ["test_runner.py", "input.txt", "fixture.lock"]
    with pytest.raises(EvidenceError, match="missing required policy"):
        guard.capture(policy, repo, commit, REMOTE, root / "capture")


def test_bounded_only_input_txt_rejected(bounded_fixture):
    """source_paths with only input.txt must be rejected (runner and policy missing)."""
    repo, commit, policy, root = bounded_fixture
    policy["source_paths"] = ["input.txt"]
    with pytest.raises(EvidenceError, match="missing required"):
        guard.capture(policy, repo, commit, REMOTE, root / "capture")


def test_full_coverage_default(bounded_fixture):
    """Policy without bounded fields uses tracked_sources(repo)."""
    repo, commit, bounded_policy, root = bounded_fixture
    # Remove bounded fields → full mode
    full_policy = {k: v for k, v in bounded_policy.items()
                   if k not in ("coverage_mode", "source_paths", "coverage_rationale")}
    result = guard.capture(full_policy, repo, commit, REMOTE, root / "capture")
    receipt_data = json.loads((root / "capture/receipt/run.json").read_text())
    # Full coverage: all tracked files
    source_paths = receipt_data["code"]["source_paths"]
    assert "test_runner.py" in source_paths
    assert "input.txt" in source_paths
    assert "fixture.lock" in source_paths
    assert "merge_policy.json" in source_paths


def test_invalid_source_paths_empty_list(bounded_fixture):
    """Empty source_paths list is rejected."""
    repo, commit, policy, root = bounded_fixture
    policy["source_paths"] = []
    with pytest.raises(EvidenceError, match="non-empty"):
        guard.capture(policy, repo, commit, REMOTE, root / "capture")


def test_invalid_source_paths_duplicate(bounded_fixture):
    """Duplicate entries in source_paths are rejected."""
    repo, commit, policy, root = bounded_fixture
    policy["source_paths"] = ["input.txt", "input.txt"]
    with pytest.raises(EvidenceError, match="unique"):
        guard.capture(policy, repo, commit, REMOTE, root / "capture")


def test_invalid_source_paths_untracked_file(bounded_fixture):
    """Non-tracked path in source_paths is rejected."""
    repo, commit, policy, root = bounded_fixture
    policy["source_paths"] = ["nonexistent.txt"]
    with pytest.raises(EvidenceError, match="not a tracked regular file"):
        guard.capture(policy, repo, commit, REMOTE, root / "capture")


def test_invalid_source_paths_partial_bounded_fields(bounded_fixture):
    """Only source_paths without coverage_mode is rejected."""
    repo, commit, policy, root = bounded_fixture
    partial = {k: v for k, v in policy.items() if k != "coverage_mode"}
    path = root / "partial.json"
    path.write_text(json.dumps(partial))
    with pytest.raises(EvidenceError, match="missing or unknown fields"):
        guard.policy_at(path)


def test_guard_identity_mismatch_rejected(bounded_fixture):
    """Receipt captured with a different guard hash is rejected by check."""
    repo, commit, policy, root = bounded_fixture
    policy["command"][-1] = "pass"
    # Capture normally
    result = guard.capture(policy, repo, commit, REMOTE, root / "capture")
    receipt_path = root / "capture/receipt/run.json"
    # Tamper with the guard hash in the receipt — must write canonical JSON
    receipt_data = json.loads(receipt_path.read_text())
    receipt_data["environment"]["tools"]["ch_merge_guard"] = "0" * 64
    # Rewrite as canonical JSON (sorted keys, no trailing whitespace)
    from cognitive_harness.evidence.contracts import canonical, write as cw
    receipt_path.write_bytes(canonical(receipt_data))
    # Check must reject the identity mismatch
    with pytest.raises(EvidenceError, match="Guard identity mismatch"):
        guard.check(policy, repo, commit, REMOTE, receipt_path, root / "verified")
