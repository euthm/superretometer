"""Optional offline H2-result -> CH example. No H2 import or execution.

Verifies bytes against a caller-pinned receipt, not the truth/authorship of a
producer's report. CH gates retain their existing semantics. Nothing is adopted.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re


class ReceiptRejected(ValueError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_artifact(root, entry):
    name = entry.get("path", "")
    relative = Path(name)
    if not name or relative.is_absolute() or ".." in relative.parts:
        raise ReceiptRejected("Artifact must have a bounded relative path")
    path = root / relative
    if any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
        raise ReceiptRejected("Symbolic artifact paths are not accepted")
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ReceiptRejected("Artifact missing or outside receipt directory")
    data = path.read_bytes()
    if digest(data) != entry.get("sha256"):
        raise ReceiptRejected("Artifact digest mismatch: " + name)
    return data


def evaluate(receipt_path, expected_receipt_sha256, expected_repo, expected_commit):
    # Trusted expectations must come from the caller, not from the imported file.
    receipt_path = Path(receipt_path)
    if receipt_path.is_symlink():
        raise ReceiptRejected("Symbolic receipt is not accepted")
    raw = receipt_path.read_bytes()
    if digest(raw) != expected_receipt_sha256:
        raise ReceiptRejected("Receipt digest differs from caller's pin")
    receipt = json.loads(raw)
    if receipt.get("format") != "h2-ch-offline-v1":
        raise ReceiptRejected("Unsupported receipt format")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise ReceiptRejected("Expected commit must be a full Git SHA")

    from cognitive_harness.analysis.implementation_gate_policy import (
        ImplementationGatePolicy, canonical_remote, sanitize_remote,
    )
    workflow = receipt["workflow"]
    if canonical_remote(workflow["repo_remote"]) != canonical_remote(expected_repo):
        raise ReceiptRejected("Workflow repository outside caller's scope")
    if workflow["commit"] != expected_commit:
        raise ReceiptRejected("Workflow commit differs from caller's pin")
    root = receipt_path.resolve().parent
    candidate = read_artifact(root, receipt["candidate"])
    oracle = read_artifact(root, receipt["oracle"])
    result_bytes = read_artifact(root, receipt["result"])
    result = json.loads(result_bytes)
    for field in ("run_id", "candidate_sha256", "oracle_sha256"):
        expected = {"run_id": receipt["run_id"], "candidate_sha256": digest(candidate),
                    "oracle_sha256": digest(oracle)}[field]
        if result.get(field) != expected:
            raise ReceiptRejected("Result binding mismatch: " + field)
    exit_code = result.get("exit_code")
    if exit_code is not None and (type(exit_code) is not int):
        raise ReceiptRejected("Exit code must be an integer or unknown")

    # Use only public ConsumerAPI/proposals; no direct KO/storage mutations.
    from cognitive_harness.consumer.api import ConsumerAPI
    from cognitive_harness.model.ko import KOType, FalsifiableValidator
    from cognitive_harness.model.proposal import Proposal, ProposalType
    from cognitive_harness.orchestration.engine import OrchestrationEngine
    from cognitive_harness.reasoning.rule_engine import RuleEngineReasoner
    from cognitive_harness.storage.inmemory import InMemoryStorage
    storage = InMemoryStorage()
    engine = OrchestrationEngine(storage, RuleEngineReasoner(storage))
    api = ConsumerAPI(storage, engine)
    receipts = []

    def execute(proposal_id):
        item = engine.execute_proposal(proposal_id)
        if item.state.value != "accepted":
            raise ReceiptRejected("CH rejected proposal: " + str(item.rejection_reason))
        receipts.append({"proposal_id": proposal_id, "state": item.state.value,
                         "created_ko_id": item.created_ko_id})
        return item

    evidence_id = execute(api.propose_ko(
        "h2-offline-bridge", KOType.FINDING, "Imported external runner receipt",
        {"run_id": receipt["run_id"], "receipt_sha256": digest(raw),
         "result_sha256": digest(result_bytes), "reported_result": result,
         "verification": "byte integrity and declared bindings; producer execution not re-run"}, [],
    )).created_ko_id
    provenance = {
        "repo_remote_canonical": canonical_remote(expected_repo),
        "repo_remote_sanitized": sanitize_remote(workflow["repo_remote"]),
        "commit": expected_commit,
        "tested_commit": result.get("tested_commit", ""),
        "worktree_clean": None,
        "test_run_id": receipt["run_id"],
        "validator_ko_id": evidence_id,
        "test_command": result.get("command", ""),
        "test_exit_code": exit_code,
        "test_timestamp": result.get("timestamp", ""),
        "test_result_sha256": digest(result_bytes),
        # No fabricated Git checkout or source-freshness observation.
    }
    claim_id = execute(api.propose_ko(
        "h2-offline-bridge", KOType.FINDING, "Recorded H2 candidate test result",
        {"description": "External receipt reports a test result for a separately digested candidate",
         "declared_remotes": [canonical_remote(expected_repo)],
         "candidate_sha256": digest(candidate), "oracle_sha256": digest(oracle),
         "implementation_provenance": provenance,
         "limits": "Does not establish candidate committed at workflow SHA, physical truth, or independent evidence roots."}, [],
    )).created_ko_id
    validator = FalsifiableValidator(
        description="Recorded test outcome with verified file bindings",
        what_would_falsify="Nonzero exit, mismatched tested revision, missing result, or changed candidate/oracle/result bytes.",
        ko_id=evidence_id, passes=exit_code == 0,
        observation="Receipt imported offline; the external test process was not executed by this importer.",
    )
    proposal = Proposal(type=ProposalType.UPDATE_KO, proposer="h2-offline-bridge",
                        target_ko_id=claim_id, updates={"validators": [validator]})
    execute(engine.submit_proposal(proposal))
    assert api.explain(claim_id) is not None and api.explain(evidence_id) is not None
    gates = ImplementationGatePolicy(storage).evaluate_gates(claim_id)
    return {"import_status": "IMPORTED", "receipt_sha256": digest(raw),
            "claim_ko_id": claim_id, "evidence_ko_id": evidence_id,
            "candidate_sha256": digest(candidate), "oracle_sha256": digest(oracle),
            "gates": gates, "warrant": api.check_warrant(claim_id),
            "adoption_allowed": False, "external_test_reexecuted": False,
            "graph": {"kos": [asdict(ko) for ko in storage.list_all_kos()], "proposals": receipts}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--receipt-sha256", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    try:
        report = evaluate(args.receipt, args.receipt_sha256, args.repo, args.commit)
    except (ReceiptRejected, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"import_status": "REJECTED", "error": str(exc)}))
        return 2
    print(json.dumps(report, indent=2, default=str))
    # This exit represents import completion only, not design approval.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
