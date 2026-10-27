"""One bounded public CH/H2/advisory smoke report. No automatic adoption."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE.parent / "harness2_bridge"))
from bridge import ReceiptRejected, digest, evaluate
from advisor import attach_advice, boundary_controls, classify


def save(path, data):
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def verify_h2(source=None):
    if source:
        sys.path.insert(0, str(source.resolve()))
    spec = importlib.util.find_spec("harness2")
    if spec is None or not spec.origin:
        raise RuntimeError("Install examples/toolchain_pilot/requirements.txt or pass --harness2-source <checkout>")
    root = Path(spec.origin).resolve().parent.parent
    lock = json.loads((HERE / "h2-lock.json").read_text())
    inventory = {p.relative_to(root).as_posix() for p in (root / "harness2").rglob("*.py")}
    require(inventory == set(lock["blobs"]), "H2 Python file inventory differs from pinned source")
    for name, expected in lock["blobs"].items():
        path = root / name
        require(path.is_file() and not path.is_symlink(), "Missing/symbolic H2 source: " + name)
        data = path.read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        require(actual == expected, "H2 source mismatch: " + name)
    return root, lock


def verify_answers(actual, expected):
    rows = [{"task": name, "actual": actual.get(name), "expected": wanted,
             "passed": actual.get(name) == wanted} for name, wanted in expected.items()]
    return rows, 0 if rows and set(actual) == set(expected) and all(r["passed"] for r in rows) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("toolchain-report-" + uuid.uuid4().hex[:8]))
    parser.add_argument("--harness2-source", type=Path, default=None)
    parser.add_argument("--julia-url", default=None, help="Optional experimental local /v1/systemone endpoint")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    try:
        h2_root, lock = verify_h2(args.harness2_source)
        from harness2.core import recursion, tree
        from harness2.core.spec import RunView
        from harness2.demo import DemoAdapter, DemoProposer

        class BoundedAdapter(DemoAdapter):
            def validate_tree(self, candidate):
                super().validate_tree(candidate)
                base = tree.read_tree(self.substrate.surface(), self.base_harness())
                require(set(candidate) == set(base), "Candidate changed file inventory")
                require(all(candidate[k] == base[k] for k in base if k != "scripts/summarize.py"),
                        "Only summarize.py may change")

        expected = {"ledger-1": "Total: 85.15\n", "ledger-2": "Total: 20.25\n"}
        save(output / "freeze.json", {"h2": lock, "run_sha256": digest(Path(__file__).read_bytes()),
             "advisor_sha256": digest((HERE / "advisor.py").read_bytes()),
             "bridge_sha256": digest((HERE.parent / "harness2_bridge/bridge.py").read_bytes()),
             "ch_core_sha256": {str(p.relative_to(ROOT)): digest(p.read_bytes())
                                for p in sorted((ROOT / "cognitive_harness").rglob("*.py"))},
             "expected": expected, "mode": "deterministic upstream demo; zero H2 model calls"})
        adapter = BoundedAdapter(output / "h2-demo")
        proposer = DemoProposer(adapter.spec.channels["proposer"])
        base_tree = tree.read_tree(adapter.substrate.surface(), adapter.base_harness())
        base_run = adapter.execute("ledger-1", None, "base1")
        mode = recursion.run_parallel("ledger-1", 1, [RunView("base1", "base1", base_run, True, True)],
            adapter=adapter, prop=proposer, work_dir=output / "method", run_id_of=lambda label: label,
            base_tree=base_tree, propose_workers=1, rollout_workers=1)
        save(output / "h2-mode.json", mode.to_dict())
        require(mode.ok and not mode.fell_back and mode.ledger.R == 4 and mode.ledger.P == 3,
                "H2 workflow incomplete or used fallback")
        final = mode.finals[0]
        final_tree = mode.trees[final]
        adapter.validate_tree(final_tree)
        overfit_tree = dict(base_tree, **{"scripts/summarize.py": "print('Total: 85.15')\n"})
        adapter.validate_tree(overfit_tree)
        overfit_dir = output / "overfit-harness"
        tree.write_tree(adapter.substrate.surface(), overfit_tree, overfit_dir, stubs=False)
        variants = [("baseline", adapter.base_harness(), base_tree),
                    ("overfit", overfit_dir, overfit_tree),
                    ("composed", output / "method/harnesses" / final, final_tree)]
        reports, summary = {}, []
        for name, harness, candidate_tree in variants:
            folder = output / name
            folder.mkdir()
            (folder / "candidate.py").write_text(candidate_tree["scripts/summarize.py"])
            actual = {}
            for task in expected:
                run = adapter.execute(task, harness, "accept-" + name + "-" + task)
                actual[task] = (run / "answer.txt").read_text()
            save(folder / "actual.json", actual)
            save(folder / "oracle.json", expected)
            command = [sys.executable, str(Path(__file__).resolve()), "verify",
                       str(folder / "actual.json"), str(folder / "oracle.json")]
            proc = subprocess.run(command, capture_output=True, text=True, timeout=10)
            require(proc.returncode in (0, 1), "Verifier process failed: " + proc.stderr)
            (folder / "test.log").write_text(proc.stdout + proc.stderr)
            rows = json.loads(proc.stdout)
            entry = lambda p: {"path": p, "sha256": digest((folder / p).read_bytes())}
            run_id = "public-toolchain-" + name
            save(folder / "result.json", {"run_id": run_id,
                "candidate_sha256": entry("candidate.py")["sha256"], "oracle_sha256": entry("oracle.json")["sha256"],
                "tested_commit": lock["commit"], "exit_code": proc.returncode,
                "timestamp": datetime.now(timezone.utc).isoformat(), "command": " ".join(command),
                "actual_sha256": entry("actual.json")["sha256"], "rows": rows,
                "log_sha256": entry("test.log")["sha256"]})
            receipt = {"format": "h2-ch-offline-v1", "run_id": run_id,
                       "workflow": {"repo_remote": "github.com/" + lock["repository"], "commit": lock["commit"]},
                       "candidate": entry("candidate.py"), "oracle": entry("oracle.json"), "result": entry("result.json")}
            save(folder / "receipt.json", receipt)
            report = evaluate(folder / "receipt.json", entry("receipt.json")["sha256"],
                              receipt["workflow"]["repo_remote"], lock["commit"])
            require(report["gates"]["test"]["status"] == ("pass" if name == "composed" else "block"),
                    "Unexpected CH test gate")
            advice = classify("Claim: both ledger tests pass. Recorded evidence: " + json.dumps(rows), args.julia_url)
            combined = attach_advice(report, advice)
            require(combined["gates"] == report["gates"] and not combined["adoption_allowed"],
                    "Advisory changed authority")
            save(folder / "report.json", combined)
            reports[name] = report
            summary.append({"candidate": name, "tests_passed": sum(r["passed"] for r in rows),
                            "tests_total": len(rows), "ch_test_gate": report["gates"]["test"]["status"],
                            "claim_ko_id": report["claim_ko_id"], "julia": advice})
        # Actual integrity failure is rejected, not just described in prose.
        path = output / "composed/result.json"
        clean = path.read_bytes()
        receipt_path = output / "composed/receipt.json"
        pin = digest(receipt_path.read_bytes())
        tamper_rejected = False
        try:
            path.write_bytes(clean + b"\n")
            try:
                evaluate(receipt_path, pin, "github.com/" + lock["repository"], lock["commit"])
            except ReceiptRejected:
                tamper_rejected = True
        finally:
            path.write_bytes(clean)
        require(tamper_rejected, "Corrupt result was accepted")
        controls = boundary_controls(reports["baseline"])
        require(controls["status"] == "PASS", "Advisory boundary control failed")
        verify_h2(args.harness2_source)
        live = "NOT_RUN"
        if args.julia_url:
            if all(r["julia"]["status"] == "OBSERVED" for r in summary):
                live = "PASS" if all(r["julia"]["label"] == ("SUPPORTED" if r["candidate"] == "composed" else "NOT_SUPPORTED") for r in summary) else "FAIL"
            else:
                live = "INCOMPLETE"
        report = {"offline_integration": "PASS", "live_julia": live, "cases": summary,
                  "julia_boundary_controls": controls, "tamper_rejected": tamper_rejected,
                  "h2": {"scripted_proposals": len(proposer._calls), "rollouts": mode.ledger.R,
                         "executor_calls_including_acceptance": adapter.execution_count, "model_calls": 0},
                  "design_bearing": False, "adoption_allowed": False,
                  "limits": "Synthetic public fixtures, scripted H2. Julia controls are stubs; live Julia only when explicitly requested. No code-agent benchmark or production qualification."}
        save(output / "report.json", report)
        print(json.dumps(report, indent=2))
        return 1 if live == "FAIL" else 2 if live == "INCOMPLETE" else 0
    except (RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
        report = {"offline_integration": "INCOMPLETE", "error": str(exc), "adoption_allowed": False}
        save(output / "report.json", report)
        print(json.dumps(report, indent=2))
        return 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "verify":
        rows, code = verify_answers(json.loads(Path(sys.argv[2]).read_text()), json.loads(Path(sys.argv[3]).read_text()))
        print(json.dumps(rows))
        raise SystemExit(code)
    raise SystemExit(main())
