#!/usr/bin/env python3
"""Replay unchanged Python conformance fixtures against the Go implementation.

The Python implementation is the oracle: wrappers observe inputs and return the
original outputs unchanged while pytest executes the existing contract tests.
Each captured call is replayed immediately, preserving temporary files used by
implementation freshness tests. No expected values are copied from Go.

Usage:
  python3 scripts/check_go_parity.py --go /path/to/go
  python3 scripts/check_go_parity.py --operations check_warrant,impact_set
  python3 scripts/check_go_parity.py --report /tmp/parity.json

Only semantic set ordering and generated report timestamps are normalized.
Diagnosis field names are projected from the Python dataclass to the published
MCP contract; every status, condition, root, and resolution hint is compared.
Incomplete external storage is explicitly excluded: a complete snapshot cannot
faithfully represent a backend which hides objects from enumeration.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
import functools
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def plain(value):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [plain(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def snapshot(storage):
    """Use public enumeration; no dependence on an InMemoryStorage._kos field."""
    objects = list(storage.list_all_kos())
    evidence = {}
    datasets = {}
    dataset_ids = []
    for ko in objects:
        for eid in ko.evidence_ids:
            ev = storage.get_evidence(eid)
            if ev is not None:
                evidence[eid] = plain(ev)
        for ev in storage.list_evidence_for_ko(ko.id):
            evidence[ev["id"]] = plain(ev)
        if ko.derivation:
            dataset_ids.extend([ko.derivation.training_dataset_id,
                                ko.derivation.test_dataset_id])
    while dataset_ids:
        did = dataset_ids.pop()
        if not did or did in datasets:
            continue
        ds = storage.get_dataset(did)
        if ds is not None:
            datasets[did] = plain(ds)
            dataset_ids.extend(ds.derived_from_dataset_ids)
    return {"objects": plain(objects), "datasets": list(datasets.values()),
            "evidence": list(evidence.values())}


def diagnosis(value):
    d = plain(value)
    d["provenance_roots"] = d.pop("shared_roots")
    d["suggested_missing_evidence"] = d.pop("resolution_hint")
    return d


def warrant(value):
    out = plain(value)
    # The public MCP response excludes the analyzer's duplicate traversal and
    # internal evidence IDs; their public equivalents are compared below.
    out.pop("justification_path")
    if value.independence is not None:
        out["independence"] = value.independence.as_response()
    out["anti_pattern_diagnoses"] = [diagnosis(d) for d in value.anti_pattern_diagnoses]
    return out


UNORDERED = {
    "supporting_kos", "independent_kos", "dependent_kos",
    "conditional_assumptions", "contradicting_kos", "offending_ko_ids",
    "provenance_roots", "anti_pattern_diagnoses", "cycles",
}


def normalize(value, key="", operation=""):
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            if k == "timestamp" and operation in ("simulation_gates", "orientation"):
                continue
            if k in ("root_sets", "shared_ancestors"):
                result[k] = {name: sorted(ids) for name, ids in v.items()}
            else:
                result[k] = normalize(v, k, operation)
        return result
    if isinstance(value, list):
        result = [normalize(v, "", operation) for v in value]
        if key in UNORDERED or (not key and operation in ("scan_anti_patterns", "impact_set")):
            result.sort(key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False))
        return result
    if isinstance(value, str):
        # Python's diagnostic strings may embed unordered set reprs. Retain all
        # members and text, canonicalizing only the ordering of an actual set.
        def order_set(match):
            try:
                item = ast.literal_eval(match.group())
            except (ValueError, SyntaxError):
                return match.group()
            if isinstance(item, set) and all(isinstance(v, str) for v in item):
                return "{" + ", ".join(repr(v) for v in sorted(item)) + "}"
            return match.group()
        return re.sub(r"\{[^{}]*\}", order_set, value)
    return value


def first_difference(expected, actual, path="$"):
    if type(expected) is not type(actual):
        return {"path": path, "expected": expected, "actual": actual}
    if isinstance(expected, dict):
        if expected.keys() != actual.keys():
            return {"path": path, "expected_keys": sorted(expected), "actual_keys": sorted(actual)}
        for k in expected:
            result = first_difference(expected[k], actual[k], f"{path}.{k}")
            if result:
                return result
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            return {"path": path, "expected": expected, "actual": actual}
        for i, (e, a) in enumerate(zip(expected, actual)):
            result = first_difference(e, a, f"{path}[{i}]")
            if result:
                return result
    elif expected != actual:
        return {"path": path, "expected": expected, "actual": actual}
    return None


class Collector:
    def __init__(self, runner, operations):
        self.runner = runner
        self.operations = operations
        self.nodeid = "outside_test"
        self.counts = Counter()
        self.excluded = Counter()
        self.failures = []
        self.restores = []

    def pytest_runtest_setup(self, item):
        self.nodeid = item.nodeid

    def wrap(self, owner, method, operation, project=plain, storage_method=False):
        if operation not in self.operations:
            return
        original = getattr(owner, method)

        @functools.wraps(original)
        def observe(instance, *args, **kwargs):
            storage = instance if storage_method else instance.storage
            if not storage.enumeration_complete:
                self.excluded[f"{operation}: incomplete external storage"] += 1
                return original(instance, *args, **kwargs)
            before = snapshot(storage)
            result = original(instance, *args, **kwargs)
            expected = project(result)
            if storage_method:
                expected = [{"id": kid, "title": storage.get_ko(kid).title
                             if storage.get_ko(kid) else ""} for kid in result]
            argument = str(args[0]) if args else str(next(iter(kwargs.values()), ""))
            request = {"operation": operation, "snapshot": before, "argument": argument}
            # Trusted local conformance fixtures may name temporary repositories.
            # Only fixture paths that already exist are granted to the Go gate.
            roots = set()
            for ko in before["objects"]:
                content = ko.get("content")
                if isinstance(content, dict):
                    prov = content.get("implementation_provenance", {})
                    if isinstance(prov, dict):
                        for name in ("repo_path", "repo_root"):
                            path = prov.get(name)
                            if isinstance(path, str) and os.path.isdir(path):
                                roots.add(path)
            if roots and operation == "implementation_gates":
                request["freshness_roots"] = sorted(roots)
            self.runner.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            self.runner.stdin.flush()
            line = self.runner.stdout.readline()
            if not line:
                raise RuntimeError("Go parity runner exited before producing a result")
            response = json.loads(line)
            self.counts[operation] += 1
            actual = response.get("result")
            diff = ({"error": response["error"]} if "error" in response else
                    first_difference(normalize(expected, operation=operation),
                                     normalize(actual, operation=operation)))
            if diff:
                self.failures.append({"test": self.nodeid, "operation": operation,
                                      "argument": argument, "difference": diff,
                                      "expected": expected, "actual": actual,
                                      "request": request})
            if operation == "check_warrant" and "justification_path" in self.operations:
                from cognitive_harness.storage.inmemory import InMemoryStorage
                if isinstance(storage, InMemoryStorage):
                    # Exercise the public traversal against the same unchanged
                    # adversarial graph, even when the test only asks warrant.
                    storage.get_justification_path(argument)
            return result

        setattr(owner, method, observe)
        self.restores.append((owner, method, original))

    def install(self):
        from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer
        from cognitive_harness.analysis.simulation_gate_policy import SimulationGatePolicy
        from cognitive_harness.analysis.implementation_gate_policy import ImplementationGatePolicy
        from cognitive_harness.storage.inmemory import InMemoryStorage
        self.wrap(WarrantAnalyzer, "compute_warrant", "check_warrant", warrant)
        self.wrap(WarrantAnalyzer, "detect_all_anti_patterns", "scan_anti_patterns",
                  lambda xs: [diagnosis(x) for x in xs])
        self.wrap(SimulationGatePolicy, "evaluate_gates", "simulation_gates", lambda x: x.to_dict())
        self.wrap(ImplementationGatePolicy, "evaluate_gates", "implementation_gates")
        self.wrap(InMemoryStorage, "get_justification_path", "justification_path", storage_method=True)
        self.wrap(InMemoryStorage, "compute_impact_set", "impact_set", storage_method=True)

    def restore(self):
        for owner, name, original in reversed(self.restores):
            setattr(owner, name, original)

    def rpc(self, request):
        self.runner.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        self.runner.stdin.flush()
        line = self.runner.stdout.readline()
        if not line:
            raise RuntimeError("Go parity runner exited before producing a result")
        return json.loads(line)

    def service_case(self, tool, args, expected, before, category, project=None):
        request = {"operation": "service_call", "tool": tool,
                   "arguments": args, "snapshot": before}
        response = self.rpc(request)
        self.counts[category] += 1
        if "error" in response:
            actual, diff = None, {"error": response["error"]}
        else:
            returned = response["result"]
            actual = project(returned) if project else returned["result"]
            diff = first_difference(normalize(expected, operation=tool),
                                    normalize(actual, operation=tool))
            # Submission and every public read must preserve the complete input
            # graph, including content, booleans, evidence and provenance.
            graph_after = {key: returned["state"][key] for key in before}
            graph_diff = first_difference(before, graph_after)
            if graph_diff:
                diff = {"graph_mutated": graph_diff, "result_difference": diff}
        if diff:
            self.failures.append({"test": f"reference_service::{tool}",
                                  "operation": category, "argument": args,
                                  "difference": diff, "expected": expected,
                                  "actual": actual, "request": request})

    def service_fixtures(self):
        """Compare public reference reads and proposal submission semantics.

        Execution corrections (numeric confidence, verified-evidence promotion,
        idempotency and real tensions) deliberately use normative Go tests, not
        the known-broken Python execution paths as an oracle.
        """
        from cognitive_harness.mcp.server import MCPServer
        from cognitive_harness.model.ko import (
            KnowledgeObject, KOType, EpistemicStatus, ConfidenceLevel,
            Provenance, Relation, RelationType, FalsifiableValidator,
        )

        def seeded():
            server = MCPServer()
            old = KnowledgeObject(id="old", type=KOType.SPECIFICATION, title="Earlier claim",
                                  epistemic_status=EpistemicStatus.SUPERSEDED,
                                  superseded_by_id="current", scope="test/hospital")
            current = KnowledgeObject(
                id="current", type=KOType.CONCLUSION, title="Current measurable claim",
                content={"verified_flag": False, "quantity": 7},
                epistemic_status=EpistemicStatus.CANONICAL, confidence=ConfidenceLevel.HIGH,
                supersedes_id="old", scope="test/hospital", viewpoint_ids=["realization"],
                provenance=Provenance(source="fixture", author="parity", independent=True),
                review_required=True, review_reason="Upstream source changed",
                assumptions=["controlled environment"],
                validators=[FalsifiableValidator(id="validator", description="Bounded error",
                            what_would_falsify="Error exceeds tolerance", passes=False)],
            )
            related = KnowledgeObject(id="related", type=KOType.OBSERVATION,
                                      title="Measurable support", content="Needle in evidence",
                                      scope="test/lab", viewpoint_ids=["application"],
                                      relations=[Relation(to="current", type=RelationType.SUPPORTS)])
            for ko in (old, current, related):
                server.storage.create_ko(ko)
            server.storage.add_evidence("record", "current", "verified", "Controlled measurement",
                                        [{"source": "measurement.csv", "accepted": False}])
            return server

        if "service_reads" in self.operations:
            server = seeded()
            cases = [
                ("orientation", {"scope": "test/hospital"}, lambda a: server._handle_orientation(a)),
                ("review_required", {}, lambda a: server.api.list_review_required()),
                ("list_canonical", {"scope": "test/hospital"}, lambda a: server.api.list_canonical(**a)),
                ("list_canonical", {"scope": "missing"}, lambda a: server.api.list_canonical(**a)),
                ("list_active_by_scope", {"scope": "test"}, lambda a: server.api.list_active_by_scope(**a)),
                ("query", {"topic": "measurable", "limit": 1}, lambda a: server.api.query(**a)),
                ("query", {"topic": "needle", "viewpoint": "application"}, lambda a: server.api.query(**a)),
                ("query", {"topic": "needle", "viewpoint": "realization"}, lambda a: server.api.query(**a)),
                ("query", {"topic": "measurable", "limit": 0}, lambda a: server.api.query(**a)),
                ("explain", {"ko_id": "current"}, lambda a: server.api.explain(**a)),
                ("explain", {"ko_id": "missing"}, lambda a: server.api.explain(**a)),
                ("succession_chain", {"ko_id": "current"}, lambda a: server.api.succession_chain(**a)),
                ("list_evidence_for_ko", {"ko_id": "current"}, lambda a: server.storage.list_evidence_for_ko(**a)),
                ("get_evidence", {"evidence_id": "record"}, lambda a: server.storage.get_evidence(**a)),
            ]
            for tool, args, reference in cases:
                before = snapshot(server.storage)
                self.service_case(tool, args, plain(reference(args)), before, "service_reads")

        if "proposal_submissions" in self.operations:
            common = {"proposer": "reference-parity", "rationale": "Check submission boundary"}
            cases = [
                ("propose_ko", {**common, "ko_type": "hypothesis", "title": "A staged hypothesis",
                  "content": {"accepted": False, "threshold": 0}, "scope": "test/lab", "viewpoints": ["conceptual"]},
                 ["ko_type", "ko_title", "ko_content", "ko_scope", "ko_viewpoints"]),
                ("propose_relation", {**common, "from_ko_id": "related", "to_ko_id": "current", "relation_type": "contradicts"},
                 ["from_ko_id", "to_ko_id", "relation_type"]),
                ("propose_evidence", {**common, "claim_ko_id": "current", "observation": "A new observation",
                  "records": [{"source": "candidate.csv", "accepted": False}]},
                 ["evidence_claim_id", "evidence_observation", "evidence_records", "evidence_relation_type"]),
                ("propose_tension", {**common, "title": "A staged conflict", "description": "Needs review",
                  "ko_ids": ["current", "related"], "viewpoints": ["conceptual"]},
                 ["tension_title", "tension_description", "tension_ko_ids", "tension_viewpoints"]),
            ]
            for tool, args, payload_keys in cases:
                server = seeded()
                before = snapshot(server.storage)
                result = getattr(server, "_handle_" + tool)(args)
                pid = result["proposal_id"]
                keys = ["type", "state", "proposer", "rationale", *payload_keys]
                py_proposal = plain(server.storage._proposals[pid])
                expected = {"pending_count": 1, "proposal": {k: py_proposal[k] for k in keys}}

                def project(returned, keys=keys):
                    result = returned["result"]
                    proposals = returned["state"]["proposals"]
                    proposal = next((p for p in proposals if p["id"] == result.get("proposal_id")), {})
                    return {"pending_count": len(proposals),
                            "proposal": {k: proposal.get(k) for k in keys}}

                self.service_case(tool, args, expected, before, "proposal_submissions", project)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--go", default=os.environ.get("GO", "go"))
    parser.add_argument("--operations", default="check_warrant,scan_anti_patterns,simulation_gates,implementation_gates,justification_path,impact_set,service_reads,proposal_submissions")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--max-failures", type=int, default=20)
    parser.add_argument("tests", nargs="*", default=["tests/conformance", "tests/adversarial", "tests/test_direction_semantics.py"])
    args = parser.parse_args()
    operations = set(args.operations.split(","))
    import pytest
    with tempfile.TemporaryDirectory(prefix="superretometer-parity-") as temp:
        binary = Path(temp) / "parity"
        subprocess.run([args.go, "build", "-buildvcs=false", "-o", str(binary), "./internal/parity"],
                       cwd=ROOT / "go", check=True)
        with subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              text=True, encoding="utf-8", bufsize=1) as runner:
            collector = Collector(runner, operations)
            collector.install()
            try:
                status = pytest.main([*args.tests, "-q", "--disable-warnings"], plugins=[collector])
                collector.service_fixtures()
            finally:
                collector.restore()
                runner.stdin.close()
                runner.wait(timeout=10)
        missing = sorted(operations - collector.counts.keys())
        report = {"python_test_exit_code": int(status), "calls_compared": dict(collector.counts),
                  "excluded": dict(collector.excluded), "unexercised_operations": missing,
                  "failure_count": len(collector.failures), "failures": collector.failures}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print("\nGo/Python parity:", json.dumps({k: v for k, v in report.items() if k != "failures"}, sort_keys=True))
        for failure in collector.failures[:args.max_failures]:
            print(json.dumps({k: failure[k] for k in ("test", "operation", "argument", "difference")}, ensure_ascii=False))
        return 1 if status != 0 or collector.failures or missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
