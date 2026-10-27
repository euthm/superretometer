"""Synthetic receipt controls; no model, H2 runtime or test execution required."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import importlib.util
EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "harness2_bridge" / "bridge.py"
_spec = importlib.util.spec_from_file_location("harness2_bridge_example", EXAMPLE)
_bridge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bridge)
ReceiptRejected, digest, evaluate = _bridge.ReceiptRejected, _bridge.digest, _bridge.evaluate

COMMIT = "a" * 40  # synthetic metadata, not an observed Git checkout
REPO = "github.com/example/public-demo"


class TestOfflineBridge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.candidate = b"print('synthetic candidate; never executed by importer')\n"
        self.oracle = b'{"synthetic_fixture": true}\n'
        self.result = {"run_id": "synthetic-unit", "candidate_sha256": digest(self.candidate),
                       "oracle_sha256": digest(self.oracle), "tested_commit": COMMIT,
                       "exit_code": 0, "command": "synthetic recorded test; not executed",
                       "timestamp": "2026-10-27T08:00:00+00:00"}
        self.receipt = {"format": "h2-ch-offline-v1", "run_id": "synthetic-unit",
                        "workflow": {"repo_remote": REPO, "commit": COMMIT},
                        "candidate": {"path": "candidate.py", "sha256": digest(self.candidate)},
                        "oracle": {"path": "oracle.json", "sha256": digest(self.oracle)}}
        (self.root / "candidate.py").write_bytes(self.candidate)
        (self.root / "oracle.json").write_bytes(self.oracle)
        self.write_receipt()

    def write_receipt(self):
        data = (json.dumps(self.result, sort_keys=True) + "\n").encode()
        (self.root / "result.json").write_bytes(data)
        self.receipt["result"] = {"path": "result.json", "sha256": digest(data)}
        self.path = self.root / "receipt.json"
        self.path.write_text(json.dumps(self.receipt, sort_keys=True) + "\n")
        self.pin = digest(self.path.read_bytes())

    def evaluate(self, repo=REPO, commit=COMMIT):
        return evaluate(self.path, self.pin, repo, commit)

    def test_valid_receipt_uses_real_ch_without_claiming_adoption(self):
        report = self.evaluate()
        self.assertEqual(report["gates"]["test"]["status"], "pass")
        self.assertEqual(report["gates"]["worktree"]["status"], "unknown")
        self.assertEqual(report["gates"]["freshness"]["status"], "unknown")
        self.assertFalse(report["gates"]["design_bearing"])
        self.assertFalse(report["adoption_allowed"])
        self.assertNotEqual(report["warrant"]["warrant_status"], "warranted")
        self.assertEqual(len(report["graph"]["kos"]), 2)
        self.assertTrue(all(p["state"] == "accepted" for p in report["graph"]["proposals"]))

    def test_failed_test_is_blocked(self):
        self.result["exit_code"] = 1
        self.write_receipt()
        self.assertEqual(self.evaluate()["gates"]["test"]["status"], "block")

    def test_tested_commit_mismatch_is_blocked(self):
        self.result["tested_commit"] = "b" * 40
        self.write_receipt()
        self.assertEqual(self.evaluate()["gates"]["test"]["status"], "block")

    def test_missing_exit_code_remains_unknown(self):
        del self.result["exit_code"]
        self.write_receipt()
        self.assertEqual(self.evaluate()["gates"]["test"]["status"], "unknown")

    def test_boolean_exit_code_is_rejected(self):
        self.result["exit_code"] = True
        self.write_receipt()
        with self.assertRaisesRegex(ReceiptRejected, "integer"):
            self.evaluate()

    def test_symbolic_artifact_is_rejected(self):
        path = self.root / "candidate.py"
        path.rename(self.root / "real-candidate.py")
        path.symlink_to("real-candidate.py")
        with self.assertRaisesRegex(ReceiptRejected, "Symbolic"):
            self.evaluate()

    def test_demo_executes_candidates_and_preserves_failed_result(self):
        output = self.root / "demo-output"
        proc = subprocess.run([sys.executable, str(EXAMPLE.with_name("demo.py")),
                               "--output", str(output)], capture_output=True,
                              text=True, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = json.loads(proc.stdout)
        self.assertEqual([(r["cases_passed"], r["ch_test_gate"]) for r in rows],
                         [(1, "block"), (3, "pass")])
        self.assertTrue(all(not r["adoption_allowed"] and not r["design_bearing"] for r in rows))

    def test_tampered_result_is_rejected_before_ch(self):
        (self.root / "result.json").write_text('{"exit_code": 0}')
        with self.assertRaisesRegex(ReceiptRejected, "digest mismatch"):
            self.evaluate()

    def test_changed_candidate_is_rejected(self):
        (self.root / "candidate.py").write_text("print('different')")
        with self.assertRaisesRegex(ReceiptRejected, "digest mismatch"):
            self.evaluate()

    def test_missing_artifact_is_rejected(self):
        (self.root / "oracle.json").unlink()
        with self.assertRaisesRegex(ReceiptRejected, "missing"):
            self.evaluate()

    def test_changed_manifest_cannot_repin_itself(self):
        self.path.write_text(self.path.read_text() + "\n")
        with self.assertRaisesRegex(ReceiptRejected, "caller's pin"):
            self.evaluate()

    def test_wrong_repository_is_rejected(self):
        with self.assertRaisesRegex(ReceiptRejected, "scope"):
            self.evaluate(repo="github.com/example/another-project")

    def test_wrong_commit_is_rejected(self):
        with self.assertRaisesRegex(ReceiptRejected, "caller's pin"):
            self.evaluate(commit="c" * 40)

    def test_result_candidate_binding_is_checked(self):
        self.result["candidate_sha256"] = "0" * 64
        self.write_receipt()
        with self.assertRaisesRegex(ReceiptRejected, "binding mismatch"):
            self.evaluate()

    def test_parent_traversal_is_rejected(self):
        self.receipt["candidate"]["path"] = "../candidate.py"
        self.write_receipt()
        with self.assertRaisesRegex(ReceiptRejected, "relative path"):
            self.evaluate()

    def test_fresh_process_reconstructs_same_gate_statuses(self):
        original = self.evaluate()
        cmd = [sys.executable, str(EXAMPLE), str(self.path),
               "--receipt-sha256", self.pin, "--repo", REPO, "--commit", COMMIT]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        replay = json.loads(result.stdout)
        statuses = lambda r: {k: v["status"] for k, v in r["gates"].items() if isinstance(v, dict) and "status" in v}
        self.assertEqual(statuses(original), statuses(replay))
        self.assertNotEqual(original["claim_ko_id"], replay["claim_ko_id"])
        self.assertFalse(replay["adoption_allowed"])


if __name__ == "__main__":
    unittest.main()
