# FILE: tests/conformance/test_implementation_gates.py
"""Conformance tests for ImplementationGatePolicy — N-IMPL-PROV.

Tests the three gates for implementation-bearing claims:
  provenance → scope (remote match) → test

CP-007 conformance: an "implemented" claim whose commit is on a remote
that is NOT declared in scope → BLOCK.
"""
import pytest
from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus, ConfidenceLevel,
    Provenance, FalsifiableValidator, GateStatus,
)
from cognitive_harness.storage.inmemory import InMemoryStorage
from cognitive_harness.analysis.implementation_gate_policy import ImplementationGatePolicy


# ── Helpers ────────────────────────────────────────────────────────────────

def mk_impl_claim(
    ko_id, title, impl_prov=None, declared_remotes=None,
    validators=None, scope="",
):
    """Create an implementation-bearing claim KO."""
    c = {}
    if impl_prov:
        c["implementation_provenance"] = impl_prov
    if declared_remotes:
        c["declared_remotes"] = declared_remotes
    return KnowledgeObject(
        id=ko_id, type=KOType.FINDING, title=title,
        content=c if c else None,
        truth_category=TruthCategory.DOCUMENTED_DECISION,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.MEDIUM,
        provenance=Provenance(source="code_repository", author="dev", independent=True),
        scope=scope,
        validators=validators or [],
    )


# ================================================================
# TEST 1: No implementation provenance → BLOCK
# ================================================================

def test_no_impl_provenance(storage):
    policy = ImplementationGatePolicy(storage)
    storage.create_ko(mk_impl_claim("claim-no-impl", "CP-007 is implemented"))
    result = policy.evaluate_gates("claim-no-impl")
    assert result["provenance"]["status"] == "block"
    assert not result["design_bearing"]


# ================================================================
# TEST 2: Incomplete provenance chain → BLOCK
# ================================================================

def test_incomplete_impl_provenance(storage):
    policy = ImplementationGatePolicy(storage)
    prov = {
        "repo_remote": "git@github.com:euthm/superretometer.git",
        "repo_path": "",  # Missing
        "branch": "cp-007-impl",
        "commit": "af2bd3c",
    }
    storage.create_ko(mk_impl_claim("claim-incomplete", "Partial provenance", impl_prov=prov))
    result = policy.evaluate_gates("claim-incomplete")
    assert result["provenance"]["status"] == "block"


# ================================================================
# TEST 3: Remote mismatch → BLOCK (CP-007 conformance test)
# ================================================================

def test_remote_mismatch_block(storage):
    """An 'implemented' claim on a remote not declared in scope → BLOCK.

    This IS the CP-007 test scenario: the implementation commits exist
    on antares-pilot/hrrm but the claim's scope declares a different remote.
    """
    policy = ImplementationGatePolicy(storage)
    prov = {
        "repo_remote": "git@github.com:euthm/antares-pilot.git",
        "repo_path": "/home/egiuth/antares-pilot/hrrm",
        "branch": "cp-007-impl",
        "commit": "60a5dc881d8f39ab8365b4fc9c9b93f4b0d47dce",
        "test_run_id": "test-cp007",
    }
    storage.create_ko(mk_impl_claim(
        "claim-remote-mismatch",
        "CP-007 agent identity implemented",
        impl_prov=prov,
        declared_remotes=["git@github.com:euthm/superretometer.git"],
    ))
    test_ko = KnowledgeObject(
        id="test-cp007", type=KOType.EVIDENCE_ITEM, title="CP-007 test run",
        content="", truth_category=TruthCategory.VALIDATION_RESULT,
        epistemic_status=EpistemicStatus.VALIDATED, confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="pytest", author="ci", independent=True),
    )
    storage.create_ko(test_ko)
    result = policy.evaluate_gates("claim-remote-mismatch")
    assert result["scope"]["status"] == "block", f"Expected BLOCK, got: {result['scope']['reason']}"
    assert not result["design_bearing"]


# ================================================================
# TEST 4: Remote match → PASS
# ================================================================

def test_remote_match_pass(storage):
    policy = ImplementationGatePolicy(storage)
    remote = "git@github.com:euthm/superretometer.git"
    prov = {
        "repo_remote": remote,
        "repo_path": "/home/egiuth/euthm/superretometer",
        "branch": "implementation-provenance",
        "commit": "a1b2c3d4e5f6",
        "test_run_id": "test-pass",
        "test_result_sha256": "deadbeef" * 8,
    }
    storage.create_ko(mk_impl_claim(
        "claim-remote-match",
        "Implementation provenance spec merged",
        impl_prov=prov,
        declared_remotes=[remote],
    ))
    test_ko = KnowledgeObject(
        id="test-pass", type=KOType.EVIDENCE_ITEM, title="Test run",
        content="", truth_category=TruthCategory.VALIDATION_RESULT,
        epistemic_status=EpistemicStatus.VALIDATED, confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="pytest", author="ci", independent=True),
    )
    storage.create_ko(test_ko)
    result = policy.evaluate_gates("claim-remote-match")
    assert result["provenance"]["status"] == "pass"
    assert result["scope"]["status"] == "pass"
    assert result["test"]["status"] == "pass"
    assert result["design_bearing"]


# ================================================================
# TEST 5: Missing test run → BLOCK
# ================================================================

def test_missing_test_run(storage):
    policy = ImplementationGatePolicy(storage)
    remote = "git@github.com:euthm/superretometer.git"
    prov = {
        "repo_remote": remote,
        "repo_path": "/home/egiuth/euthm/superretometer",
        "branch": "main",
        "commit": "da827a9",
    }
    storage.create_ko(mk_impl_claim(
        "claim-no-test",
        "No test run",
        impl_prov=prov,
        declared_remotes=[remote],
    ))
    result = policy.evaluate_gates("claim-no-test")
    assert result["test"]["status"] == "block"
    assert not result["design_bearing"]


# ================================================================
# TEST 6: Remote normalization (git@ vs https)
# ================================================================

def test_remote_normalization(storage):
    """Remote match should survive git@ → https normalization."""
    policy = ImplementationGatePolicy(storage)
    prov = {
        "repo_remote": "https://github.com/euthm/superretometer.git",
        "repo_path": "/home/egiuth/euthm/superretometer",
        "branch": "main",
        "commit": "da827a9",
        "test_run_id": "test-norm",
        "test_result_sha256": "cafe" * 16,
    }
    storage.create_ko(mk_impl_claim(
        "claim-normalize",
        "HTTPS remote matches git@ declaration",
        impl_prov=prov,
        declared_remotes=["git@github.com:euthm/superretometer.git"],
    ))
    test_ko = KnowledgeObject(
        id="test-norm", type=KOType.EVIDENCE_ITEM, title="Test run",
        content="", truth_category=TruthCategory.VALIDATION_RESULT,
        epistemic_status=EpistemicStatus.VALIDATED, confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="pytest", author="ci", independent=True),
    )
    storage.create_ko(test_ko)
    result = policy.evaluate_gates("claim-normalize")
    assert result["scope"]["status"] == "pass", f"Normalization failed: {result['scope']['reason']}"


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def storage():
    return InMemoryStorage()
