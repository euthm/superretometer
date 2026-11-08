"""Versioned byte contracts; verification never executes receipt commands."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath


class EvidenceError(ValueError):
    """Rejected, incomplete, unsupported, or conflicting evidence operation."""


def plain(value):
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(plain(v) for v in value)
    return value


def canonical(value) -> bytes:
    return json.dumps(plain(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def package_source_sha256() -> str:
    root = Path(__file__).parents[1]
    return sha(canonical({p.relative_to(root).as_posix(): sha(p.read_bytes())
                          for p in sorted(root.rglob("*.py"))}))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load(path: Path):
    try:
        return json.loads(path.read_bytes(), object_pairs_hook=_pairs,
                          parse_constant=lambda x: (_ for _ in ()).throw(
                              EvidenceError(f"Non-finite JSON number: {x}")))
    except (OSError, ValueError) as exc:
        raise EvidenceError(f"Cannot read JSON {path.name}: {exc}") from exc


def write(path: Path, value, *, replace=False):
    """Atomic publication. New records may never overwrite a finalized identity."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical(value)
    fd, temp = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temp, path)
        else:
            # link is atomic and fails if a finalized file already exists.
            os.link(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def validate(value, name: str):
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:
        raise EvidenceError("Install cognitive-harness[evidence] for receipt validation") from exc
    schema = load(Path(__file__).parent / "schemas" / f"{name}.schema.json")
    error = next(iter(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value)), None)
    if error:
        location = ".".join(map(str, error.absolute_path)) or "root"
        raise EvidenceError(f"Invalid {name} at {location}: {error.message}")


def relative(name: str) -> str:
    """One portable spelling, no escapes, controls, Windows paths or dot segments."""
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name
            or any(ord(c) < 32 for c in name) or name.startswith("/")):
        raise EvidenceError(f"Unsafe relative path: {name!r}")
    p = PurePosixPath(name)
    if any(part in ("", ".", "..", ".git") for part in name.split("/")) or str(p) != name:
        raise EvidenceError(f"Ambiguous relative path: {name!r}")
    return name


def safe_file(root: Path, name: str, *, must_exist=True) -> Path:
    relative(name)
    root = root.resolve()
    path = root
    for part in PurePosixPath(name).parts:
        path = path / part
        if path.is_symlink():
            raise EvidenceError(f"Symlink is not permitted: {name}")
    if must_exist and not path.is_file():
        raise EvidenceError(f"Missing regular file: {name}")
    if path.exists() and not path.is_file():
        raise EvidenceError(f"Not a regular file: {name}")
    return path


def file_entry(root: Path, name: str) -> dict:
    data = safe_file(root, name).read_bytes()
    return {"path": name, "size": len(data), "sha256": sha(data)}


def manifest(root: Path, paths: list[str]) -> list[dict]:
    if len(set(paths)) != len(paths):
        raise EvidenceError("Duplicate declared source paths")
    return [file_entry(root, name) for name in sorted(paths)]


def listed_files(root: Path) -> list[str]:
    if root.is_symlink() or not root.is_dir():
        raise EvidenceError("A regular evidence directory is required (archives are not extracted)")
    result = []
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(base) / name
            if path.is_symlink():
                raise EvidenceError("Evidence directories cannot contain symlinks")
        for name in files:
            rel = (Path(base) / name).relative_to(root).as_posix()
            relative(rel)
            result.append(rel)
    return sorted(result)


def receipt_at(path: Path) -> tuple[Path, dict]:
    if path.is_symlink():
        raise EvidenceError("Receipt path cannot be a symlink")
    root = path if path.is_dir() else path.parent
    receipt_path = safe_file(root, "run.json")
    if path.is_file() and path.name != "run.json":
        raise EvidenceError("Expected a receipt directory or run.json")
    run = load(receipt_path)
    validate(run, "test-run-receipt-v1")
    if receipt_path.read_bytes() != canonical(run):
        raise EvidenceError("run.json must use canonical JSON bytes")
    if datetime.fromisoformat(run["ended_at"].replace("Z", "+00:00")) < datetime.fromisoformat(run["started_at"].replace("Z", "+00:00")):
        raise EvidenceError("Run ends before it starts")
    code = run["code"]
    from .capture import canonical_remote, parse_results
    if canonical_remote(code["remote"]) != code["canonical_remote"]:
        raise EvidenceError("Observed and canonical repository identities disagree")
    for names in (code["source_paths"], code["lockfile_paths"]):
        if len(set(names)) != len(names) or names != sorted(names):
            raise EvidenceError("Declared input paths must be unique and sorted")
        for name in names:
            relative(name)
    execution = run["execution"]
    if (execution["outcome"] == "not_run") != (execution["exit_code"] is None):
        raise EvidenceError("Execution outcome and exit code disagree")
    if execution["outcome"] == "exited" and (execution["exit_code"] < 0 or execution["signal"] is not None):
        raise EvidenceError("Exited outcome cannot carry a signal")
    if execution["exit_code"] is not None and execution["exit_code"] < 0 and execution["signal"] != -execution["exit_code"]:
        raise EvidenceError("Child signal and exit code disagree")
    if run["capture"]["state"] == "complete":
        before, after = code["before"], code["after"]
        if (run["capture"]["reasons"] or execution["outcome"] != "exited" or before != after
                or before["errors"] or after["errors"] or run["parser"]["error"]
                or run["parser"]["kind"] == "unknown/v1"
                or any(v is None for v in run["environment"]["tools"].values())
                or [e["path"] for e in before["source_manifest"]] != code["source_paths"]
                or [e["path"] for e in before["lockfiles"]] != code["lockfile_paths"]):
            raise EvidenceError("Complete capture conflicts with its observations")
    length = 40 if code["object_format"] == "sha1" else 64
    for state in (code["before"], code["after"]):
        if state is None:
            continue
        if len(state["commit"]) != length:
            raise EvidenceError("Git object format and commit length disagree")
        paths = [e["path"] for e in state["source_manifest"]]
        if len(set(paths)) != len(paths) or paths != sorted(paths):
            raise EvidenceError("Source manifest paths must be unique and sorted")
        for e in state["source_manifest"] + state["lockfiles"]:
            relative(e["path"])
        if sha(canonical(state["source_manifest"])) != state["source_manifest_sha256"]:
            raise EvidenceError("Source manifest hash mismatch")
    return root, run


def acceptance(run: dict) -> dict:
    """Domain acceptance, independent of gate and warrant semantics."""
    reasons, unknown = [], []
    ex = run["execution"]
    counts = run["tests"]["counts"]
    rules = run["acceptance"]
    if ex["outcome"] != "exited":
        reasons.append(f"Execution outcome: {ex['outcome']}")
    elif ex["exit_code"] is None:
        unknown.append("Child exit code is unknown")
    elif ex["exit_code"] != 0:
        reasons.append(f"Child exit code: {ex['exit_code']}")
    if run["capture"]["state"] != "complete":
        unknown.extend(run["capture"]["reasons"] or ["Capture incomplete"])
    required = {"executed": rules["expected_executed"],
                "failed": 0 if rules["required_zero_failures"] else None,
                "skipped": 0 if rules["no_skips"] else None}
    for name, expected in required.items():
        if expected is None:
            continue
        if counts[name] is None:
            unknown.append(f"{name} count is unknown")
        elif counts[name] != expected:
            reasons.append(f"{name}: expected {expected}, observed {counts[name]}")
    missing = set(rules["required_test_ids"]) - set(run["tests"]["selected_ids"])
    if missing:
        reasons.append(f"Required test IDs absent: {sorted(missing)}")
    return {"status": "fail" if reasons else "unknown" if unknown else "pass",
            "reasons": reasons + unknown}


def verify(path, *, repo=None) -> dict:
    """Verify bytes offline; optionally measure source freshness in a mapped checkout.

    Historical evaluations are checked for byte integrity, never presented as new
    evaluations. Neither receipt argv nor producer paths are executed or trusted.
    """
    root, run = receipt_at(Path(path))
    seen = {"run.json"}
    for item in run["artifacts"]:
        if item["path"] in seen:
            raise EvidenceError("Duplicate or reserved artifact path")
        seen.add(item["path"])
        if file_entry(root, item["path"]) != {k: item[k] for k in ("path", "size", "sha256")}:
            raise EvidenceError(f"Artifact digest mismatch: {item['path']}")
    roles = [a["role"] for a in run["artifacts"]]
    if roles.count("stdout") != 1 or roles.count("stderr") != 1 or roles.count("structured-result") > 1:
        raise EvidenceError("Artifact roles are missing or ambiguous")
    from .capture import parse_results
    result = next((a for a in run["artifacts"] if a["role"] == "structured-result"), None)
    try:
        parsed = parse_results(run["parser"]["kind"], safe_file(root, result["path"]).read_bytes() if result else None)
    except EvidenceError:
        if run["parser"]["error"] is None:
            raise EvidenceError("Unreported structured parser failure")
        parsed = parse_results("unknown/v1", None)
    if parsed != run["tests"]:
        raise EvidenceError("Receipt counts/test IDs disagree with the structured result")
    evaluations = []
    if (root / "SHA256SUMS").exists():
        index = load(safe_file(root, "SHA256SUMS"))
        validate(index, "test-evidence-bundle-v1")
        if index["receipt_sha256"] != sha(canonical(run)):
            raise EvidenceError("Bundle receipt identity mismatch")
        actual = set(listed_files(root)) - {"SHA256SUMS"}
        if set(index["files"]) != actual:
            raise EvidenceError("Bundle coverage mismatch (extra or missing files)")
        for name, entry in index["files"].items():
            if file_entry(root, name) != {"path": name, **entry}:
                raise EvidenceError(f"Bundle digest mismatch: {name}")
        for eid in index["evaluation_ids"]:
            value = load(safe_file(root, f"evaluations/{eid}/evaluation.json"))
            validate(value, "test-evaluation-v1")
            if value["receipt_sha256"] != index["receipt_sha256"] or value["run_id"] != run["run_id"] or value["evaluation_id"] != eid:
                raise EvidenceError("Evaluation binding mismatch")
            prefix = f"evaluations/{eid}/"
            for name in ("gates", "warrant"):
                if load(safe_file(root, prefix + name + ".json")) != value[name]:
                    raise EvidenceError(f"Evaluation {name} response mismatch")
            if sha(safe_file(root, prefix + "graph.json").read_bytes()) != value["graph_sha256"]:
                raise EvidenceError("Evaluation graph identity mismatch")
            graph = load(safe_file(root, prefix + "graph.json"))
            from .workflow import _restore
            _restore(graph)
            claim_id = graph["mapping"]["claim"]["ch_id"]
            if (any(n["content"].get("receipt_sha256") != value["receipt_sha256"] for n in graph["nodes"])
                    or value["gates"].get("claim_ko_id") != claim_id
                    or value["warrant"].get("conclusion_ko_id") != claim_id):
                raise EvidenceError("Graph/evaluation/receipt binding mismatch")
            evaluations.append(eid)
    else:
        if set(listed_files(root)) != seen:
            raise EvidenceError("Receipt directory contains unbound files")
    source, reasons = "unavailable", ["No operator-mapped checkout; historical verification only"]
    if repo is not None:
        from .capture import observe
        try:
            state = observe(Path(repo), run["code"]["source_paths"], run["code"]["lockfile_paths"])
            expected = run["code"]["before"]
            fields = ("commit", "status_sha256", "diff_sha256", "source_manifest", "lockfiles", "submodules")
            reasons = [f"Current {key} differs from captured pre-state" for key in fields if state[key] != expected[key]] + state["errors"]
            source = "mismatch" if reasons else "verified"
        except (EvidenceError, OSError) as exc:
            source, reasons = "unavailable", [str(exc)]
    return {"integrity": "verified", "receipt_sha256": sha(canonical(run)),
            "run_id": run["run_id"], "source_current": source, "reasons": reasons,
            "capture": run["capture"], "acceptance": acceptance(run),
            "historical_evaluations": evaluations,
            "trust": "runner-reported; checksums are not authenticity or independent certification"}
