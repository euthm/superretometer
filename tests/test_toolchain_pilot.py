"""Public optional toolchain controls; no model service needed."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/toolchain_pilot"
spec = importlib.util.spec_from_file_location("toolchain_advisor_example", EXAMPLE / "advisor.py")
advisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(advisor)


class AdvisoryControls(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(advisor.parse_reply('{"answers":{"q1":{"noul":0.9}}}')["label"], "SUPPORTED")

    def test_negative(self):
        self.assertEqual(advisor.parse_reply('{"answers":{"q1":{"noul":0.1}}}')["label"], "NOT_SUPPORTED")

    def test_missing_score_does_not_default_to_support(self):
        self.assertEqual(advisor.parse_reply('{"answers":{"q1":{}}}')["status"], "UNKNOWN")

    def test_malformed_json_abstains(self):
        self.assertEqual(advisor.parse_reply('broken')["status"], "UNKNOWN")

    def test_invalid_score_types_and_ranges(self):
        for score in (True, None, "0.9", [], -1, 2, float("nan"), float("inf")):
            with self.subTest(score=score):
                result = advisor.parse_reply(json.dumps({"answers": {"q1": {"noul": score}}}))
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertNotIn("label", result)

    def test_no_endpoint_makes_no_request(self):
        def unexpected(*args):
            self.fail("No endpoint must not call a transport")
        self.assertEqual(advisor.classify("fixture", transport=unexpected)["status"], "NOT_RUN")

    def test_timeout_is_not_run_no_retry(self):
        calls = []
        def timeout(*args):
            calls.append(args)
            raise TimeoutError("controlled")
        result = advisor.classify("fixture", "http://127.0.0.1:8011/v1/systemone", transport=timeout)
        self.assertEqual(result["status"], "NOT_RUN")
        self.assertEqual(len(calls), 1)

    def test_oversized_response_abstains(self):
        result = advisor.classify("fixture", "http://127.0.0.1:8011/v1/systemone", transport=lambda *a: b"x" * 16385)
        self.assertEqual(result["status"], "UNKNOWN")

    def test_external_endpoint_rejected_before_transport(self):
        def unexpected(*args):
            self.fail("External endpoint must not reach transport")
        with self.assertRaises(ValueError):
            advisor.classify("fixture", "https://example.com/julia", transport=unexpected)

    def test_advisory_cannot_override_gate_or_mutate_original(self):
        report = {"gates": {"test": {"status": "block"}}, "adoption_allowed": False}
        advised = advisor.attach_advice(report, {"label": "SUPPORTED"})
        self.assertEqual(advised["gates"], report["gates"])
        self.assertFalse(advised["adoption_allowed"])
        self.assertNotIn("julia_advisory", report)
        advised["gates"]["test"]["status"] = "pass"
        self.assertEqual(report["gates"]["test"]["status"], "block")

    def test_all_embedded_controls(self):
        report = {"gates": {"test": {"status": "block"}}, "adoption_allowed": False}
        result = advisor.boundary_controls(report)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(result["checks"]), 9)
        self.assertFalse(result["model_call"])


@unittest.skipUnless(sys.version_info >= (3, 12) and (os.environ.get("HARNESS2_SOURCE") or importlib.util.find_spec("harness2")),
                     "Optional pinned H2 dependency not installed; use example requirements or HARNESS2_SOURCE")
class FullToolchainControls(unittest.TestCase):
    def test_single_command_real_h2_and_ch_with_advisory_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, str(EXAMPLE / "run.py"), "--output", str(Path(directory) / "report")]
            if os.environ.get("HARNESS2_SOURCE"):
                command += ["--harness2-source", os.environ["HARNESS2_SOURCE"]]
            proc = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = json.loads(proc.stdout)
            self.assertEqual(report["offline_integration"], "PASS")
            self.assertEqual(report["live_julia"], "NOT_RUN")
            self.assertEqual([r["ch_test_gate"] for r in report["cases"]], ["block", "block", "pass"])
            self.assertEqual([r["tests_passed"] for r in report["cases"]], [0, 1, 2])
            self.assertEqual(report["h2"]["scripted_proposals"], 3)
            self.assertEqual(report["h2"]["rollouts"], 4)
            self.assertEqual(report["h2"]["model_calls"], 0)
            self.assertTrue(report["tamper_rejected"])
            self.assertFalse(report["adoption_allowed"])
            self.assertEqual(report["julia_boundary_controls"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
