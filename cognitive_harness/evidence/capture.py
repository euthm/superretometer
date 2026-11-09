"""Explicit local runner. This module is never called by import or evaluation."""
from __future__ import annotations

import os
import platform
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from cognitive_harness import __version__
from cognitive_harness.analysis.implementation_gate_policy import canonical_remote, _compute_blob_digest
from .contracts import (EvidenceError, canonical, file_entry, load, manifest, now,
                        relative, safe_file, sha, validate, verify, write, package_source_sha256)


def git(repo: Path, *args, check=True) -> bytes:
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvidenceError("Git observation unavailable") from exc
    if check and p.returncode:
        raise EvidenceError(f"Git observation failed: {args[0]}")
    return p.stdout if p.returncode == 0 else b""


def remote(repo: Path) -> str:
    raw = git(repo, "remote", "get-url", "origin", check=False).decode().strip()
    # The legacy helper preserves SSH users and URL queries; receipts do not.
    if "://" in raw:
        url = urlsplit(raw)
        host = url.hostname or ""
        if url.port:
            host += f":{url.port}"
        return urlunsplit((url.scheme.lower(), host, url.path, "", ""))
    return re.sub(r"^[^@/]+@", "git@", raw).split("?", 1)[0].split("#", 1)[0]


def observe(repo: Path, sources: list[str], locks: list[str]) -> dict:
    root = Path(git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if root != repo.resolve():
        raise EvidenceError("Repository mapping must name the Git worktree root")
    status = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    staged = git(repo, "diff", "--no-ext-diff", "--no-textconv", "--binary", "--cached", "HEAD", "--")
    unstaged = git(repo, "diff", "--no-ext-diff", "--no-textconv", "--binary", "--")
    index = git(repo, "ls-files", "--stage", "-z")
    # Reuse the exact index snapshot already included in diff_sha256. Starting
    # a new Git process for every source/lockfile made large captures impractical.
    # Keep paths as bytes: unrelated non-UTF-8 names need not be decoded, and
    # glob/pathspec characters in a declared name must be matched literally.
    tracked_paths = {entry.split(b"\t", 1)[1] for entry in index.split(b"\0") if entry}
    untracked = []
    for raw in git(repo, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
        if not raw:
            continue
        name = raw.decode("utf-8")
        path = repo / name
        data = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
        untracked.append({"path": name, "sha256": sha(data), "size": len(data)})
    errors, files, lockfiles = [], [], []
    for paths, entries in ((sources, files), (locks, lockfiles)):
        if len(set(paths)) != len(paths):
            raise EvidenceError("Duplicate declared input paths")
        for name in sorted(paths):
            try:
                entries.append(file_entry(repo, name))
            except EvidenceError as exc:
                errors.append(str(exc))
    pins = {}
    for line in git(repo, "submodule", "status", "--recursive").decode().splitlines():
        marker, rest = line[:1], line[1:].split()
        if len(rest) < 2 or len(rest) > 3 or (len(rest) == 3 and not (rest[2].startswith("(") and rest[2].endswith(")"))):
            errors.append("Unparseable submodule state")
            continue
        commit, path = rest[:2]
        relative(path)
        initialized = marker != "-"
        rem = remote(repo / path) if initialized else ""
        clean = marker == " " and initialized and not git(repo / path, "status", "--porcelain=v1", "--untracked-files=all")
        pins[path] = {"path": path, "commit": commit, "repo_remote_canonical": canonical_remote(rem),
                      "repo_remote_sanitized": rem, "initialized": initialized, "clean": bool(clean)}
        if not initialized or not rem or not clean:
            errors.append(f"Submodule unavailable, dirty, or missing remote: {path}")
    for entry in files + lockfiles:
        if entry["path"].encode("utf-8") not in tracked_paths:
            errors.append(f"Declared input is not tracked by Git: {entry['path']}")
    complete = len(files) == len(sources) and bool(sources)
    return {"commit": git(repo, "rev-parse", "HEAD").decode().strip(),
            "branch": git(repo, "symbolic-ref", "--short", "HEAD", check=False).decode().strip(),
            "clean": not status, "status_sha256": sha(status),
            "diff_sha256": sha(canonical({"staged_diff_sha256": sha(staged), "unstaged_diff_sha256": sha(unstaged), "index_sha256": sha(index), "untracked": untracked})),
            "source_manifest": files, "source_manifest_sha256": sha(canonical(files)),
            "legacy_blob_digest": _compute_blob_digest(str(repo), sources) if complete else None,
            "lockfiles": lockfiles, "submodules": pins, "errors": errors}


def parse_results(kind: str, data: bytes | None) -> dict:
    """Two explicit adapters. Never infer counts from a successful process exit."""
    unknown = {"counts": {k: None for k in ("discovered", "executed", "passed", "failed", "skipped")}, "selected_ids": []}
    if kind == "unknown/v1":
        return unknown
    if data is None:
        raise EvidenceError("Structured result is absent")
    if kind == "counts-json/v1":
        import json
        from .contracts import _pairs
        try:
            value = json.loads(data, object_pairs_hook=_pairs)
            if set(value) != {"schema_version", "counts", "test_ids"} or value["schema_version"] != "counts/v1":
                raise ValueError("Expected counts/v1 document")
            counts, ids = value["counts"], value["test_ids"]
            if set(counts) != set(unknown["counts"]) or any(type(v) is not int or v < 0 for v in counts.values()):
                raise ValueError("Counts must be nonnegative integers")
            if not isinstance(ids, list) or any(not isinstance(v, str) or not v for v in ids) or len(ids) != len(set(ids)):
                raise ValueError("Test IDs must be unique nonempty strings")
            if counts["executed"] != counts["passed"] + counts["failed"] or counts["discovered"] != counts["executed"] + counts["skipped"]:
                raise ValueError("Inconsistent test totals")
            if len(ids) != counts["discovered"]:
                raise ValueError("Test identities do not cover discovered cases")
            return {"counts": counts, "selected_ids": ids}
        except (ValueError, KeyError, TypeError) as exc:
            raise EvidenceError(f"Invalid counts/v1 report: {exc}") from exc
    if kind != "junit/v1":
        raise EvidenceError(f"Unsupported parser: {kind}")
    try:
        xml_text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvidenceError("JUnit adapter accepts UTF-8 only") from exc
    if "\0" in xml_text or "<!DOCTYPE" in xml_text.upper() or "<!ENTITY" in xml_text.upper():
        raise EvidenceError("JUnit document types/entities are not permitted")
    try:
        root = ET.fromstring(xml_text)
        cases = list(root.iter("testcase"))
        if root.tag not in ("testsuites", "testsuite") or not cases:
            raise ValueError("Expected JUnit testcase elements")
        ids, passed, failed, skipped = [], 0, 0, 0
        for case in cases:
            if sum(case.find(tag) is not None for tag in ("skipped", "failure", "error")) > 1:
                raise ValueError("Ambiguous testcase outcome")
            if not case.get("name"):
                raise ValueError("Unnamed testcase")
            ids.append(f"{case.get('classname', '')}::{case.get('name')}")
            if case.find("skipped") is not None:
                skipped += 1
            elif case.find("failure") is not None or case.find("error") is not None:
                failed += 1
            else:
                passed += 1
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate testcase identities")
        if root.get("tests") is not None and int(root.get("tests")) != len(cases):
            raise ValueError("JUnit tests count differs from testcase coverage")
        return {"counts": {"discovered": len(cases), "executed": passed + failed,
                           "passed": passed, "failed": failed, "skipped": skipped}, "selected_ids": ids}
    except (ET.ParseError, ValueError) as exc:
        raise EvidenceError(f"Invalid JUnit report: {exc}") from exc


def _profile(profile) -> tuple[dict, Path]:
    if isinstance(profile, (str, Path)):
        path = Path(profile).resolve()
        p, base = load(path), path.parent
    else:
        p, base = dict(profile), Path.cwd()
    validate(p, "test-capture-profile-v1")
    required = {"repo", "source_paths", "lockfiles", "archive", "claim", "acceptance", "parser", "environment"}
    if not required <= p.keys() or p.keys() - required - {"timeout_seconds", "redact_env"}:
        raise EvidenceError("Profile has missing or unknown keys")
    for key in ("source_paths", "lockfiles", "redact_env"):
        value = p.get(key, [])
        if not isinstance(value, list) or any(not isinstance(s, str) for s in value):
            raise EvidenceError(f"{key} must be a list of strings")
    if not p["source_paths"]:
        raise EvidenceError("Declare at least one source file")
    for name in p["source_paths"] + p["lockfiles"]:
        relative(name)
    if set(p["archive"]) != {"path", "locator", "retention"} or not p["archive"]["locator"] or not p["archive"]["retention"]:
        raise EvidenceError("Archive requires path, locator and explicit retention policy")
    if set(p["parser"]) != {"kind", "report"} or p["parser"]["kind"] not in ("counts-json/v1", "junit/v1", "unknown/v1"):
        raise EvidenceError("Explicit supported parser kind/report required")
    if p["parser"]["report"] is not None:
        relative(p["parser"]["report"])
    if p["parser"]["kind"] != "unknown/v1" and p["parser"]["report"] is None:
        raise EvidenceError("A structured parser requires a report path")
    env = p["environment"]
    if set(env) != {"tools", "services", "exclusions"} or not isinstance(env["tools"], dict):
        raise EvidenceError("Environment requires explicit tools, services and exclusions")
    for argv in env["tools"].values():
        if not isinstance(argv, list) or not argv or any(not isinstance(a, str) for a in argv):
            raise EvidenceError("Tool observations require explicit argument vectors")
    timeout = p.get("timeout_seconds")
    if timeout is not None and (type(timeout) not in (float, int) or timeout <= 0):
        raise EvidenceError("Timeout must be positive")
    return p, base


def record(profile, argv: list[str]) -> dict:
    """Execute exactly the operator-supplied argv; publish a new immutable run.

    {repo} and {output} are substituted only here. No shell is introduced.
    Services and falsifiers are declarations; tool versions are observations.
    """
    from .contracts import acceptance
    p, base = _profile(profile)
    if not isinstance(argv, list) or not argv or any(not isinstance(a, str) for a in argv):
        raise EvidenceError("A nonempty command argument vector is required")
    secrets = [os.environ[n].encode() for n in p.get("redact_env", []) if os.environ.get(n)]
    # Secrets in metadata/commands are rejected rather than published verbatim.
    metadata = canonical({"profile": {k: v for k, v in p.items() if k != "redact_env"}, "argv": argv})
    if any(s in metadata for s in secrets):
        raise EvidenceError("Configured secret found in profile or command metadata")
    repo = (base / p["repo"]).resolve()
    archive = (base / p["archive"]["path"]).resolve()
    if archive == repo or repo in archive.parents:
        raise EvidenceError("Capture outputs must live outside the tested worktree")
    archive.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    destination = archive / "runs" / run_id
    started = now()
    before = observe(repo, p["source_paths"], p["lockfiles"])
    object_format = git(repo, "rev-parse", "--show-object-format").decode().strip()
    observed_remote = remote(repo)
    if not observed_remote or not canonical_remote(observed_remote):
        raise EvidenceError("A repository origin remote is required")
    reasons = list(before["errors"])
    tools = {}
    for name, command in p["environment"]["tools"].items():
        try:
            tool = subprocess.run(command, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
            tools[name] = tool.stdout[:8192].decode("utf-8", errors="replace").strip() if tool.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            tools[name] = None
        if tools[name] is None:
            reasons.append(f"Tool version unavailable: {name}")
        elif any(s in tools[name].encode() for s in secrets):
            tools[name] = None
            reasons.append(f"Tool version redacted/unavailable: {name}")
    with tempfile.TemporaryDirectory(prefix="ch-evidence-") as stage_name:
        stage = Path(stage_name)
        command = [a.replace("{repo}", str(repo)).replace("{output}", str(stage)) for a in argv]
        outcome, exit_code, sig, stdout, stderr = "not_run", None, None, b"", b""
        proc = None
        try:
            proc = subprocess.Popen(command, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    start_new_session=(os.name == "posix"))
            try:
                stdout, stderr = proc.communicate(timeout=p.get("timeout_seconds"))
                outcome = "signaled" if proc.returncode < 0 else "exited"
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                outcome = "timed_out" if isinstance(exc, subprocess.TimeoutExpired) else "signaled"
                sig = signal.SIGKILL if outcome == "timed_out" else signal.SIGINT
                if os.name == "posix":
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    proc.kill()
                stdout, stderr = proc.communicate()
            exit_code = proc.returncode
            sig = -exit_code if exit_code < 0 else None
        except OSError as exc:
            # Avoid exception text containing unredacted arguments/credentials.
            reasons.append(f"Command could not start ({type(exc).__name__})")
        try:
            after = observe(repo, p["source_paths"], p["lockfiles"])
            reasons.extend(after["errors"])
        except (EvidenceError, OSError) as exc:
            after = None
            reasons.append(f"Post-execution observation unavailable ({type(exc).__name__})")
        if before != after or remote(repo) != observed_remote:
            reasons.append("Code/dependency/worktree state changed during execution")
        artifacts = []
        destination.mkdir(parents=True, exist_ok=False)
        def persist(name, data, role, derivation):
            transformed = data
            for secret in secrets:
                transformed = transformed.replace(secret, b"[REDACTED]")
            path = safe_file(destination, name, must_exist=False)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(transformed)
            artifacts.append({**file_entry(destination, name), "role": role,
                              "transformation": "unmodified" if data == transformed else "redacted",
                              "derivation": derivation, "locator": "bundle-relative"})
            return transformed
        persist("logs/stdout.log", stdout, "stdout", "child stdout stream")
        persist("logs/stderr.log", stderr, "stderr", "child stderr stream")
        result, parser_error = None, None
        report = p["parser"]["report"]
        if report is not None:
            try:
                raw = safe_file(stage, report).read_bytes()
                extension = "xml" if p["parser"]["kind"] == "junit/v1" else "json"
                result = persist(f"test-results.{extension}", raw, "structured-result", "child result file")
            except EvidenceError as exc:
                parser_error = str(exc)
        try:
            if parser_error:
                raise EvidenceError(parser_error)
            tests = parse_results(p["parser"]["kind"], result)
        except EvidenceError as exc:
            parser_error = str(exc)
            tests = parse_results("unknown/v1", None)
        if parser_error or p["parser"]["kind"] == "unknown/v1":
            reasons.append(parser_error or "Test counts are not observed by this parser")
        if outcome != "exited":
            reasons.append(f"Execution outcome: {outcome}")
        run = {"schema_version": "test-run/v1", "run_id": run_id,
               "producer": {"name": "superretometer", "version": __version__, "origin": "local-runner-reported", "source_sha256": package_source_sha256()},
               "started_at": started, "ended_at": now(),
               "code": {"remote": observed_remote, "canonical_remote": canonical_remote(observed_remote),
                        "object_format": object_format,
                        "digest_algorithm": "path-size-sha256-json/v1",
                        "worktree_digest_algorithm": "staged-unstaged-untracked-sha256-json/v1",
                        "legacy_digest_algorithm": "sorted-concatenated-content-sha256/v0",
                        "source_paths": sorted(p["source_paths"]), "lockfile_paths": sorted(p["lockfiles"]),
                        "before": before, "after": after},
               "execution": {"argv": command, "argv_template": argv, "cwd": ".", "cwd_binding": "configured-repository-root", "outcome": outcome, "exit_code": exit_code,
                             "signal": sig, "timeout_seconds": p.get("timeout_seconds")},
               "parser": {"kind": p["parser"]["kind"], "version": 1, "error": parser_error},
               "tests": tests, "claim": p["claim"], "acceptance": p["acceptance"],
               "environment": {"os": platform.platform(), "architecture": platform.machine(),
                               "python": sys.version.split()[0], "tools": tools,
                               "services": p["environment"]["services"], "exclusions": p["environment"]["exclusions"]},
               "artifacts": artifacts, "archive": {"locator": p["archive"]["locator"].rstrip("/") + "/runs/" + run_id,
                                                    "retention": p["archive"]["retention"]},
               "capture": {"state": "not_run" if outcome == "not_run" else "incomplete" if reasons else "complete",
                           "reasons": list(dict.fromkeys(reasons))}}
        validate(run, "test-run-receipt-v1")
        if any(secret in canonical(run) for secret in secrets):
            raise EvidenceError("Configured secret found in captured metadata; receipt not published")
        write(destination / "run.json", run)
    return {"receipt": str(destination / "run.json"), "receipt_sha256": sha(canonical(run)),
            "run_id": run_id, "child_exit_code": exit_code, "capture": run["capture"],
            "acceptance": acceptance(run)}
