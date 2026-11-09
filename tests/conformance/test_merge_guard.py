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
