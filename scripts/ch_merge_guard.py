"""Fail-closed CI adapter around the existing #18 evidence APIs.

Run capture without credentials on an ephemeral runner. Run check in a fresh
job using reviewed control code/policy, never code from the candidate artifact.
This script is also usable outside GitHub and is language independent.
"""
from __future__ import annotations

import argparse
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


def _extract_runner_paths(command):
    """Extract explicit file paths from the command argv that live inside {repo}.

    Returns relative paths (without {repo} prefix) for files referenced by
    the command that must be present in source_paths when tracked.
    Only direct file references are extracted; module paths (-m pytest) and
    directory arguments are not treated as runner files.
    """
    result = []
    for arg in command:
        # {repo}/path → relative path
        if arg.startswith("{repo}/"):
            rel = arg[len("{repo}/"):]
            if rel and not rel.startswith("/"):
                result.append(rel)
    return result


def _enforce_minimum_set(source_paths, tracked_paths, command):
    """Reject if tracked files referenced by the command are missing from source_paths.

    The reviewed command names specific files (runner script, etc.). If those
    files are tracked by Git, they must appear in the declared source_paths.
    A capture that omits the actual runner code cannot represent the reviewed
    regression. Pattern-based source discovery is insufficient for enforcement.
    """
    declared = set(source_paths)
    required = set(_extract_runner_paths(command))
    tracked_set = set(tracked_paths)
    missing = []
    for path in sorted(required):
        if path in tracked_set and path not in declared:
            missing.append(path)
    if missing:
        raise EvidenceError(
            f"Declared source set omits tracked required files referenced by command: {', '.join(missing)}"
        )


def policy_at(path):
    policy = load(Path(path))
    if not isinstance(policy, dict) or set(policy) != POLICY_FIELDS:
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


def capture(policy, repo, commit, expected_remote, output):
    repo = Path(repo).resolve()
    expected_checkout(repo, commit, expected_remote)
    output = fresh_output(output, repo)
    tracked = tracked_sources(repo)
    profile = {
        "repo": str(repo), "source_paths": tracked, "lockfiles": policy["lockfiles"],
        "archive": {"path": str(output / "archive"), "locator": "ci-artifact://ch-evidence",
                    "retention": "CI artifacts expire after 30 days; export to durable storage for longer audit retention"},
        "claim": {"title": "Candidate satisfies the reviewed regression policy", "scope": policy["scope"],
                  "declared_remote": expected_remote, "requested_commit": commit,
                  "falsifier": "Any failed or missing required test, unexpected skip, source change, or different commit invalidates this bounded claim"},
        "acceptance": acceptance_rules(policy), "parser": policy["parser"],
        "environment": {"tools": {"python": [sys.executable, "--version"]}, "services": {},
                        "exclusions": ["Runner-reported observations; no independent certification or production approval",
                                       "External services and dependencies beyond declared lockfiles/submodules are not verified"]},
        "timeout_seconds": policy["timeout_seconds"],
    }
    result = record(profile, policy["command"])
    shutil.copytree(Path(result["receipt"]).parent, output / "receipt")
    # Keep the transfer small: only the finalized receipt, results and logs.
    shutil.rmtree(output / "archive")
    result["receipt"] = str(output / "receipt/run.json")
    return result


def validate_run(policy, repo, commit, expected_remote, receipt):
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
    tracked = tracked_sources(repo)
    _enforce_minimum_set(code["source_paths"], tracked, policy["command"])
    if code["source_paths"] != tracked or code["lockfile_paths"] != sorted(policy["lockfiles"]):
        raise EvidenceError("Receipt omits tracked sources or declared lockfiles")
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


def check(policy, repo, commit, expected_remote, receipt, output):
    repo = Path(repo).resolve()
    checked, run = validate_run(policy, repo, commit, expected_remote, receipt)
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
    result = {"schema_version": "ch-merge-result/v1", "approved": True, "commit": commit,
              "repository": canonical_remote(expected_remote), "policy_sha256": sha(canonical(policy)),
              "run_id": run["run_id"], "receipt_sha256": checked["receipt_sha256"],
              "counts": run["tests"]["counts"], "baseline": baseline,
              "negative_controls": evaluations[1:], "export": exported,
              "trust": "Scoped CI acceptance; runner-reported, not independent certification or deployment approval"}
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
        if args.operation == "capture":
            result = capture(*common, args.output)
            code = 0 if result["acceptance"]["status"] == "pass" else 4
        else:
            if not args.receipt:
                raise EvidenceError("check requires an explicitly selected receipt")
            result = check(*common, args.receipt, args.output)
            code = 0
        print(json.dumps(result, sort_keys=True))
        return code
    except (EvidenceError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"approved": False, "status": "rejected", "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
