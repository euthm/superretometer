"""Create and import synthetic external-run receipts; no Harness2 or model needed."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from bridge import digest, evaluate

WORKFLOW_REPO = "github.com/example/h2-receipt-demo"
WORKFLOW_SHA = "a" * 40  # Synthetic fixture, not an observed checkout.
CASES = {"original": ["100.25", "-20.10", "5.00"], "empty": [],
         "negative": ["-10.25", "-5.00"]}
EXPECTED = {"original": "85.15\n", "empty": "0.00\n", "negative": "-15.25\n"}
PROGRAM = """import json, sys
from decimal import Decimal
values = [Decimal(v) for v in json.loads(sys.argv[1])]
total = sum(values, Decimal(0))
print(f'{total:.2f}')
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    summary = []
    for name, program in (("hardcoded", "print('85.15')\n"), ("signed-sum", PROGRAM)):
        folder = root / name
        folder.mkdir()
        candidate = folder / "candidate.py"
        candidate.write_text(program)
        outcomes = []
        for case, values in CASES.items():
            cmd = [sys.executable, str(candidate), json.dumps(values)]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            outcomes.append({"case": case, "returncode": proc.returncode,
                             "stdout": proc.stdout, "stderr": proc.stderr,
                             "passed": proc.returncode == 0 and proc.stdout == EXPECTED[case]})
        # This trusted demo runner compares actual subprocess results. The
        # offline importer merely verifies and records the supplied receipt.
        exit_code = 0 if outcomes and all(x["passed"] for x in outcomes) else 1
        (folder / "oracle.json").write_text(json.dumps(EXPECTED) + "\n")
        entry = lambda p: {"path": p, "sha256": digest((folder / p).read_bytes())}
        run_id = "synthetic-demo-" + name
        result = {"run_id": run_id, "candidate_sha256": entry("candidate.py")["sha256"],
                  "oracle_sha256": entry("oracle.json")["sha256"], "exit_code": exit_code,
                  "tested_commit": WORKFLOW_SHA, "command": "synthetic demo subprocess checks",
                  "timestamp": datetime.now(timezone.utc).isoformat(), "outcomes": outcomes}
        (folder / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        receipt = {"format": "h2-ch-offline-v1", "run_id": run_id,
                   "workflow": {"repo_remote": WORKFLOW_REPO, "commit": WORKFLOW_SHA},
                   "candidate": entry("candidate.py"), "oracle": entry("oracle.json"),
                   "result": entry("result.json")}
        path = folder / "receipt.json"
        path.write_text(json.dumps(receipt, indent=2) + "\n")
        pin = digest(path.read_bytes())
        report = evaluate(path, pin, WORKFLOW_REPO, WORKFLOW_SHA)
        (folder / "ch-report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
        (folder / "trust-inputs.json").write_text(json.dumps({"receipt_sha256": pin,
            "repo": WORKFLOW_REPO, "commit": WORKFLOW_SHA}, indent=2) + "\n")
        summary.append({"candidate": name, "cases_passed": sum(x["passed"] for x in outcomes),
                        "cases_total": len(CASES), "runner_exit_code": exit_code,
                        "ch_test_gate": report["gates"]["test"]["status"],
                        "design_bearing": report["gates"]["design_bearing"],
                        "adoption_allowed": report["adoption_allowed"]})
    (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
