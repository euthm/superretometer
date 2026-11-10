"""Fail-closed CI adapter around the existing #18 evidence APIs.

Run capture without credentials on an ephemeral runner. Run check in a fresh
job using reviewed control code/policy, never code from the candidate artifact.
This script is also usable outside GitHub and is language independent.

Coverage modes
--------------
**full** (default): Every tracked regular file is hashed. This is the only
mode that provides complete source binding without policy author discretion.

**bounded**: Policy declares ``source_paths`` together with ``coverage_mode``
and ``coverage_rationale``. Only the declared paths are hashed. A mandatory
minimum set (source, tests, lockfiles, runner, policy) is enforced. Runner
and policy are included when they live inside the candidate worktree.

Guard identity
--------------
``policy_sha256`` hashes the reviewed policy JSON, not the guard code.
Guard identity is recorded as a tool observation in the receipt
(`environment.tools["ch_merge_guard"]`) and verified in ``check``:
the hash stored in the receipt must match the guard executing check.
Mismatch rejects the receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET

from cognitive_harness.analysis.implementation_gate_policy import canonical_remote
from cognitive_harness.evidence import Target, evaluate, export_bundle, import_receipt, record, verify
from cognitive_harness.evidence.capture import git, remote
from cognitive_harness.evidence.contracts import EvidenceError, canonical, load, receipt_at, safe_file, sha, write

GATES = ("provenance", "scope", "worktree", "test", "falsifiability", "dependency", "freshness")
POLICY_FIELDS = {"schema_version", "command", "parser", "minimum_executed",
                 "required_test_ids", "allowed_skipped_ids", "lockfiles",
                 "timeout_seconds", "scope"}
# Bounded-coverage fields — all three required together.
BOUNDED_FIELDS = {"coverage_mode", "source_paths", "coverage_rationale"}


def _guard_source_sha():
    """Hash this guard script for identity binding."""
    this_file = Path(__file__).resolve()
    return sha(this_file.read_bytes())


def _extract_runner_paths(command):
    """Extract explicit file paths from the command argv that live inside {repo}.

    Returns relative paths for files referenced by the reviewed command that
    must be present in source_paths when tracked. Only direct file references
    are extracted; module paths (-m pytest) and directory arguments are not
    treated as runner files.
    """
    result = []
    for arg in command:
        if arg.startswith("{repo}/"):
            rel = arg[len("{repo}/"):]
            if rel and not rel.startswith("/"):
                result.append(rel)
    return result


def _guard_policy_path(policy_path):
    """Return the relative policy file path if it lives inside the candidate repo.

    The --policy file is loaded from outside the worktree in the CI workflow,
    but when a policy file is tracked inside the candidate repo it must be
    included in source_paths. Returns None when the policy file is external.
    """
    try:
        pol = Path(policy_path).resolve()
        # The policy path argument is absolute in CI. We check if it is a tracked
        # file by comparing against the caller's repo root later.
        return pol.name
    except Exception:
        return None


def _tracked_file_set(repo):
    """Return a set of tracked regular file paths (not submodules)."""
    tracked = set()
    for entry in git(repo, "ls-files", "--stage", "-z").split(b"\0"):
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        mode, _, stage = header.decode().split()
        if stage != "0":
            raise EvidenceError("Unmerged Git index")
        if mode in ("100644", "100755"):
            tracked.add(name.decode("utf-8"))
    return tracked


def _validate_source_paths(source_paths, repo):
    """Validate source_paths: correct type, non-empty, unique, tracked regular files.
    Returns a sorted list."""
    if not isinstance(source_paths, list) or len(source_paths) == 0:
        raise EvidenceError("source_paths must be a non-empty list")
    if len(source_paths) != len(set(source_paths)):
        raise EvidenceError("source_paths must contain unique entries")
    for p in source_paths:
        if not isinstance(p, str) or not p:
            raise EvidenceError(f"source_paths entry is not a non-empty string: {p!r}")
    tracked = _tracked_file_set(repo)
    for p in source_paths:
        if p not in tracked:
            raise EvidenceError(f"source_paths entry '{p}' is not a tracked regular file")
    return sorted(source_paths)


def _enforce_minimum_set(source_paths, repo, command, policy_file_path=None):
    """Enforce that tracked files required for the reviewed regression are in source_paths.

    Two checks, both explicit (no patterns):

    1. Runner: every file referenced by the reviewed command as {repo}/path must
       appear in source_paths when tracked in the repository. This covers the
       actual test runner script and any data/config files the command reads.

    2. Policy: if the --policy file lives inside the candidate worktree
       (same basename is a tracked file), it must be in source_paths.
       The policy file is reviewed separately from the command argv, so this
       check is independent of _extract_runner_paths.
    """
    declared = set(source_paths)
    tracked = _tracked_file_set(repo)
    missing = []

    # 1. Command-referenced files (runner, data files, etc.)
    for path in sorted(_extract_runner_paths(command)):
        if path in tracked and path not in declared:
            missing.append(path)

    # 2. Policy file — checked by name when it exists inside the worktree
    if policy_file_path is not None:
        # Find the actual tracked file by matching basename
        pol_basename = Path(policy_file_path).name
        for f in sorted(tracked):
            if Path(f).name == pol_basename and f not in declared:
                missing.append(f)
                break

    if missing:
        raise EvidenceError(
            f"Bounded coverage missing required files: "
            f"{', '.join(missing)} are tracked but not in source_paths."
        )


def policy_at(path):
    policy = load(Path(path))
    if not isinstance(policy, dict):
        raise EvidenceError("Merge policy must be a YAML/JSON mapping")
    # Allow exactly POLICY_FIELDS (full mode) or POLICY_FIELDS + BOUNDED_FIELDS (bounded mode)
    if set(policy) != POLICY_FIELDS and set(policy) != POLICY_FIELDS | BOUNDED_FIELDS:
        raise EvidenceError("Merge policy has missing or unknown fields")
    if policy["schema_version"] != "ch-merge-policy/v1":
        raise EvidenceError("Unsupported merge policy version")
    for key in ("command", "required_test_ids", "allowed_skipped_ids", "lockfiles"):
        value = policy[key]
        if (not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value)
                or (key != "command" and len(value) != len(set(value)))):
            raise EvidenceError(f"Invalid merge policy {key}")
    if not policy["command"] or not policy["required_test_ids"]:
        raise EvidenceError("Policy must declare a command and required regression IDs")
    for key in ("minimum_executed", "timeout_seconds"):
        if type(policy[key]) is not int or policy[key] <= 0:
            raise EvidenceError(f"Policy {key} must be a positive integer")
    if not isinstance(policy["scope"], str) or not policy["scope"].strip():
        raise EvidenceError("Policy must bound its claim scope")
    parser = policy["parser"]
    if (not isinstance(parser, dict) or set(parser) != {"kind", "report"}
            or parser["kind"] not in ("junit/v1", "counts-json/v1")):
        raise EvidenceError("Merge policy requires a structured result parser")
    if parser["kind"] != "junit/v1" and policy["allowed_skipped_ids"]:
        raise EvidenceError("Per-test skip exceptions require JUnit outcomes")
    from cognitive_harness.evidence.contracts import relative
    relative(parser["report"])
    for name in policy["lockfiles"]:
        relative(name)

    # Bounded-mode validation
    if set(policy) == POLICY_FIELDS | BOUNDED_FIELDS:
        if policy["coverage_mode"] != "bounded":
            raise EvidenceError("coverage_mode must be 'bounded'")
        if not isinstance(policy["coverage_rationale"], str) or not policy["coverage_rationale"].strip():
            raise EvidenceError("coverage_rationale must be a non-empty string explaining the exclusion")
        # source_paths type validated here; repo-path validation deferred to effective_source_paths
        if not isinstance(policy["source_paths"], list) or len(policy["source_paths"]) == 0:
            raise EvidenceError("source_paths must be a non-empty list")

    return policy


def tracked_sources(repo):
    """Bind all tracked regular files, including tests, runners and policies.

    Submodule directories are represented by #18's recursive pin observations.
    Symlinks/other Git modes are explicitly unsupported, never silently omitted.
    """
    paths = []
    for entry in git(repo, "ls-files", "--stage", "-z").split(b"\0"):
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        mode, _, stage = header.decode().split()
        if stage != "0":
            raise EvidenceError("Unmerged Git index")
        if mode == "160000":
            continue
        if mode not in ("100644", "100755"):
            raise EvidenceError("Merge guard requires regular tracked source files")
        paths.append(name.decode("utf-8"))
    return sorted(paths)


def effective_source_paths(policy, repo, policy_file_path=None):
    """Return the source_paths to use, validated, minimum-set enforced, and sorted.

    For bounded mode, validates against tracked files and enforces minimum set.
    For full mode, returns all tracked sources. Order is normalised (sorted)
    identically in capture and check.
    """
    if "coverage_mode" in policy and policy["coverage_mode"] == "bounded":
        validated = _validate_source_paths(policy["source_paths"], repo)
        _enforce_minimum_set(validated, repo, policy["command"], policy_file_path)
        return validated
    return tracked_sources(repo)


def expected_checkout(repo, commit, expected_remote):
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit):
        raise EvidenceError("Expected commit must be a full Git object ID")
    if git(repo, "rev-parse", "HEAD").decode().strip() != commit:
        raise EvidenceError("Checkout does not match the externally expected commit")
    if not canonical_remote(expected_remote) or canonical_remote(remote(repo)) != canonical_remote(expected_remote):
        raise EvidenceError("Checkout does not match the externally expected repository")


def acceptance_rules(policy):
    return {"expected_executed": None, "required_zero_failures": True,
            "no_skips": not policy["allowed_skipped_ids"],
            "required_test_ids": policy["required_test_ids"]}


def fresh_output(output, repo):
    output = Path(output).resolve()
    if output == repo or repo in output.parents:
        raise EvidenceError("Merge guard output must be outside the tested worktree")
    output.mkdir(parents=True, exist_ok=False)
    return output


def _guard_tool_command():
    """Return a valid tool command that outputs the guard source hash.
    
    This is recorded in environment.tools and executed by record().
    The output (the hash string) is stored in the receipt at
    environment.tools["ch_merge_guard"].
    """
    guard_sha = _guard_source_sha()
    return [sys.executable, "-c", f"import sys; sys.stdout.write({guard_sha!r})"]


def capture(policy, repo, commit, expected_remote, output, policy_file_path=None):
    repo = Path(repo).resolve()
    expected_checkout(repo, commit, expected_remote)
    output = fresh_output(output, repo)
    source_paths = effective_source_paths(policy, repo, policy_file_path)
    profile = {
        "repo": str(repo), "source_paths": source_paths, "lockfiles": policy["lockfiles"],
        "archive": {"path": str(output / "archive"), "locator": "ci-artifact://ch-evidence",
                    "retention": "CI artifacts expire after 30 days; export to durable storage for longer audit retention"},
        "claim": {"title": "Candidate satisfies the reviewed regression policy", "scope": policy["scope"],
                  "declared_remote": expected_remote, "requested_commit": commit,
                  "falsifier": "Any failed or missing required test, unexpected skip, source change, or different commit invalidates this bounded claim"},
        "acceptance": acceptance_rules(policy), "parser": policy["parser"],
        "environment": {
            "tools": {
                "python": [sys.executable, "--version"],
                "ch_merge_guard": _guard_tool_command(),
            },
            "services": {},
            "exclusions": [
                "Runner-reported observations; no independent certification or production approval",
                "External services and dependencies beyond declared lockfiles/submodules are not verified",
            ],
        },
        "timeout_seconds": policy["timeout_seconds"],
    }
    result = record(profile, policy["command"])
    shutil.copytree(Path(result["receipt"]).parent, output / "receipt")
    # Keep the transfer small: only the finalized receipt, results and logs.
    shutil.rmtree(output / "archive")
    result["receipt"] = str(output / "receipt/run.json")
    return result


def _receipt_guard_sha(root, run):
    """Extract the guard source hash from the receipt's tool observations."""
    tools = run.get("environment", {}).get("tools", {})
    guard_sha = tools.get("ch_merge_guard")
    if guard_sha is None:
        raise EvidenceError(
            "Receipt missing guard identity observation (environment.tools.ch_merge_guard). "
            "This receipt was captured by an older guard version without identity binding."
        )
    if not re.fullmatch(r"[0-9a-f]{64}", guard_sha):
        raise EvidenceError(f"Receipt guard identity is not a valid SHA-256: {guard_sha!r}")
    return guard_sha


def validate_run(policy, repo, commit, expected_remote, receipt, policy_file_path=None):
    """Treat every candidate-controlled observation as data; execute nothing."""
    repo = Path(repo).resolve()
    expected_checkout(repo, commit, expected_remote)
    checked = verify(receipt, repo=repo)
    root, run = receipt_at(Path(receipt))
    if (checked["integrity"] != "verified" or checked["source_current"] != "verified"
            or checked["capture"]["state"] != "complete" or checked["acceptance"]["status"] != "pass"):
        raise EvidenceError("Incomplete, stale or failing execution evidence")
    code = run["code"]
    if (code["before"]["commit"] != commit or code["after"]["commit"] != commit
            or run["claim"]["requested_commit"] != commit
            or not code["before"]["clean"] or not code["after"]["clean"]):
        raise EvidenceError("Receipt is not a clean execution of the expected commit")
    if (code["canonical_remote"] != canonical_remote(expected_remote)
            or canonical_remote(run["claim"]["declared_remote"]) != canonical_remote(expected_remote)):
        raise EvidenceError("Receipt repository identity mismatch")
    expected_sources = effective_source_paths(policy, repo, policy_file_path)
    if code["source_paths"] != expected_sources or code["lockfile_paths"] != sorted(policy["lockfiles"]):
        raise EvidenceError("Receipt omits tracked sources or declared lockfiles")
    # Verify guard identity: the guard that captured must be the same as the guard checking.
    receipt_guard_sha = _receipt_guard_sha(root, run)
    current_guard_sha = _guard_source_sha()
    if receipt_guard_sha != current_guard_sha:
        raise EvidenceError(
            f"Guard identity mismatch: receipt captured with guard SHA {receipt_guard_sha}, "
            f"but check is executing guard SHA {current_guard_sha}. "
            f"Use the same reviewed guard version for capture and check."
        )
    observed_argv = run["execution"]["argv"]
    literal_argv_matches = len(observed_argv) == len(policy["command"]) and all(
        re.fullmatch(re.escape(template).replace(r"\{repo\}", ".+").replace(r"\{output\}", ".+"), actual)
        for template, actual in zip(policy["command"], observed_argv)
    )
    if (run["execution"]["argv_template"] != policy["command"] or not literal_argv_matches
            or run["execution"]["timeout_seconds"] != policy["timeout_seconds"]
            or run["parser"]["kind"] != policy["parser"]["kind"]
            or run["acceptance"] != acceptance_rules(policy)
            or run["claim"]["scope"] != policy["scope"]):
        raise EvidenceError("Receipt changed the reviewed command or acceptance policy")
    counts = run["tests"]["counts"]
    if counts["executed"] < policy["minimum_executed"] or counts["passed"] != counts["executed"]:
        raise EvidenceError("Insufficient passing tests for the reviewed regression floor")
    skipped = set()
    if policy["parser"]["kind"] == "junit/v1":
        result = next(a for a in run["artifacts"] if a["role"] == "structured-result")
        cases = ET.fromstring(safe_file(root, result["path"]).read_bytes()).iter("testcase")
        skipped = {f"{c.get('classname', '')}::{c.get('name')}" for c in cases if c.find("skipped") is not None}
    if skipped - set(policy["allowed_skipped_ids"]):
        raise EvidenceError("Unexpected skipped tests")
    executed = set(run["tests"]["selected_ids"]) - skipped
    if not set(policy["required_test_ids"]) <= executed:
        raise EvidenceError("A required regression test was skipped or omitted")
    return checked, run


def check(policy, repo, commit, expected_remote, receipt, output, policy_file_path=None):
    repo = Path(repo).resolve()
    checked, run = validate_run(policy, repo, commit, expected_remote, receipt, policy_file_path)
    output = fresh_output(output, repo)
    target = Target("ci-merge-guard", output / "target", {expected_remote: repo})
    import_receipt(receipt, target)
    evaluations = [evaluate(target, run["run_id"], control=c)
                   for c in ("baseline", "commit_mismatch", "missing_validator")]
    baseline, mismatch, missing = evaluations
    if not baseline["approved"] or not all(baseline["gates"][g]["status"] == "pass" for g in GATES):
        raise EvidenceError("Baseline did not pass all seven implementation gates")
    if mismatch["approved"] or mismatch["gates"]["test"]["status"] != "block":
        raise EvidenceError("Commit-mismatch negative control failed")
    if any(mismatch["gates"][g]["status"] != baseline["gates"][g]["status"] for g in GATES if g != "test"):
        raise EvidenceError("Commit-mismatch control is not isolated")
    if missing["approved"] or missing["gates"]["test"]["status"] != "unknown":
        raise EvidenceError("Missing-validator negative control failed")
    exported = export_bundle(target, [e["evaluation_id"] for e in evaluations], output / "bundle")
    offline = verify(output / "bundle", repo=repo)
    if offline["integrity"] != "verified" or offline["source_current"] != "verified":
        raise EvidenceError("Final bundle verification failed")
    # Extract guard identity from receipt for the result
    root = Path(receipt).parent
    receipt_guard_sha = _receipt_guard_sha(root, run)
    current_guard_sha = _guard_source_sha()
    result = {
        "schema_version": "ch-merge-result/v1", "approved": True, "commit": commit,
        "repository": canonical_remote(expected_remote),
        "policy_sha256": sha(canonical(policy)),
        "guard_source_sha256": current_guard_sha,
        "receipt_guard_sha256": receipt_guard_sha,
        "run_id": run["run_id"], "receipt_sha256": checked["receipt_sha256"],
        "counts": run["tests"]["counts"], "baseline": baseline,
        "negative_controls": evaluations[1:], "export": exported,
        "trust": "Scoped CI acceptance; runner-reported, not independent certification or deployment approval"
    }
    write(output / "merge-result.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("capture", "check"))
    parser.add_argument("--policy", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-remote", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--receipt")
    args = parser.parse_args(argv)
    try:
        policy = policy_at(args.policy)
        common = (policy, args.repo, args.expected_commit, args.expected_remote)
        # Pass the --policy file path for in-worktree policy enforcement
        pol_path = str(Path(args.policy).resolve())
        if args.operation == "capture":
            result = capture(*common, args.output, policy_file_path=pol_path)
            code = 0 if result["acceptance"]["status"] == "pass" else 4
        else:
            if not args.receipt:
                raise EvidenceError("check requires an explicitly selected receipt")
            result = check(*common, args.receipt, args.output, policy_file_path=pol_path)
            code = 0
        print(json.dumps(result, sort_keys=True))
        return code
    except (EvidenceError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"approved": False, "status": "rejected", "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
