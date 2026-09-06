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
from cognitive_harness.analysis.implementation_gate_policy import (
    ImplementationGatePolicy, canonical_remote, sanitize_remote,
)


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
    """Missing canonical remote or commit -> BLOCK. Missing optional fields -> PASS."""
    policy = ImplementationGatePolicy(storage)
    prov = {
        "repo_remote_sanitized": "git@github.com:euthm/superretometer.git",
        "repo_path": "",  # Optional — no longer required
        "branch": "cp-007-impl",
        "commit": "af2bd3c",
    }
    # This should PASS now: has canonical (derived from raw) + commit
    storage.create_ko(mk_impl_claim("claim-incomplete-path", "Missing repo_path only", impl_prov=prov))
    result = policy.evaluate_gates("claim-incomplete-path")
    assert result["provenance"]["status"] == "pass", "repo_path is optional, provenance should pass"

    # Missing commit -> BLOCK
    prov_no_commit = {
        "repo_remote_raw": "git@github.com:euthm/superretometer.git",
    }
    storage.create_ko(mk_impl_claim("claim-missing-commit", "No commit", impl_prov=prov_no_commit))
    result2 = policy.evaluate_gates("claim-missing-commit")
    assert result2["provenance"]["status"] == "block", "Missing commit must block"

    # Missing both raw and canonical -> BLOCK
    prov_no_remote = {
        "commit": "af2bd3c",
    }
    storage.create_ko(mk_impl_claim("claim-missing-remote", "No remote", impl_prov=prov_no_remote))
    result3 = policy.evaluate_gates("claim-missing-remote")
    assert result3["provenance"]["status"] == "block", "Missing remote must block"


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


# ================================================================
# CH-IMPL-001: equivalent remotes normalize equal (git@ vs https)
# ================================================================

def test_ch_impl_001_git_https_normalize_equal():
    """git@ and https:// forms of the same repo must normalize identically."""
    git_form = "git@github.com:example/foo.git"
    https_form = "https://github.com/example/foo.git"
    assert canonical_remote(git_form) == canonical_remote(https_form)
    assert canonical_remote(git_form) == "github.com/example/foo"


# ================================================================
# CH-IMPL-002: ssh:// form normalizes equal
# ================================================================

def test_ch_impl_002_ssh_normalizes_equal():
    """ssh://git@host/path must normalize to same canonical as git@ and https."""
    ssh_form = "ssh://git@github.com/example/foo.git"
    git_form = "git@github.com:example/foo.git"
    https_form = "https://github.com/example/foo.git"
    assert canonical_remote(ssh_form) == canonical_remote(git_form)
    assert canonical_remote(ssh_form) == canonical_remote(https_form)
    assert canonical_remote(ssh_form) == "github.com/example/foo"


# ================================================================
# CH-IMPL-003: same SHA + different canonical repo -> BLOCK
# ================================================================

def test_ch_impl_003_same_sha_wrong_repo_block(storage):
    """Commit SHA alone is NOT global identity. Different repo -> BLOCK."""
    policy = ImplementationGatePolicy(storage)
    prov = {
        "repo_remote_canonical": "github.com/example/repo-a",
        "commit": "abcdef1234567890",
    }
    storage.create_ko(mk_impl_claim(
        "claim-003",
        "Same commit, different repo",
        impl_prov=prov,
        declared_remotes=["github.com/example/repo-b"],
    ))
    result = policy.evaluate_gates("claim-003")
    assert result["scope"]["status"] == "block", f"Expected BLOCK, got: {result['scope']['reason']}"


# ================================================================
# CH-IMPL-004: branch changes, commit same -> provenance valid
# ================================================================

def test_ch_impl_004_branch_change_provenance_valid(storage):
    """Changing branch name while commit stays same must not invalidate provenance."""
    policy = ImplementationGatePolicy(storage)
    remote = "github.com/example/project"
    # First provenance on branch "main"
    prov = {
        "repo_remote_canonical": remote,
        "branch": "main",
        "commit": "abcdef1234567890",
    }
    storage.create_ko(mk_impl_claim(
        "claim-004",
        "Branch changed, commit same",
        impl_prov=prov,
        declared_remotes=[remote],
    ))
    result = policy.evaluate_gates("claim-004")
    assert result["provenance"]["status"] == "pass"
    assert result["scope"]["status"] == "pass"

    # Update to different branch, same commit
    prov["branch"] = "feature/new-branch"
    storage.create_ko(mk_impl_claim(
        "claim-004-updated",
        "Branch changed, commit same",
        impl_prov=prov,
        declared_remotes=[remote],
    ))
    result2 = policy.evaluate_gates("claim-004-updated")
    assert result2["provenance"]["status"] == "pass"
    assert result2["scope"]["status"] == "pass"


# ================================================================
# CH-IMPL-005: detached HEAD (empty branch) -> eligible for PASS
# ================================================================

def test_ch_impl_005_detached_head_eligible(storage):
    """Detached HEAD with canonical remote + exact commit -> provenance PASS."""
    policy = ImplementationGatePolicy(storage)
    remote = "github.com/example/project"
    prov = {
        "repo_remote_canonical": remote,
        "branch": "",  # detached HEAD
        "commit": "abcdef1234567890",
    }
    storage.create_ko(mk_impl_claim(
        "claim-005",
        "Detached HEAD implementation",
        impl_prov=prov,
        declared_remotes=[remote],
    ))
    result = policy.evaluate_gates("claim-005")
    assert result["provenance"]["status"] == "pass", f"Expected PASS, got: {result['provenance']['reason']}"
    assert result["scope"]["status"] == "pass"


# ================================================================
# CH-IMPL-006: raw + canonical disagree -> fail closed
# ================================================================

def test_ch_impl_006_raw_canonical_disagree_block(storage):
    """If raw remote canonicalizes to different identity than explicit canonical -> BLOCK."""
    policy = ImplementationGatePolicy(storage)
    # Raw says github.com/example/repo-x, canonical claims github.com/example/repo-y
    prov = {
        "repo_remote_sanitized": "git@github.com:example/repo-x.git",
        "repo_remote_canonical": "github.com/example/repo-y",
        "commit": "abcdef1234567890",
    }
    storage.create_ko(mk_impl_claim(
        "claim-006",
        "Raw and canonical disagree",
        impl_prov=prov,
        declared_remotes=["github.com/example/repo-x"],
    ))
    result = policy.evaluate_gates("claim-006")
    # The parser detects the conflict and returns an empty provenance -> provenance gate BLOCK
    assert result["provenance"]["status"] == "block", f"Expected BLOCK on conflict, got: {result['provenance']['reason']}"


# ================================================================
# Additional canonicalization unit tests
# ================================================================

def test_canonical_remote_generic_gitlab():
    """Generic GitLab/self-hosted remote normalizes correctly."""
    assert canonical_remote("git@gitlab.example.com:group/subgroup/repo.git") == "gitlab.example.com/group/subgroup/repo"
    assert canonical_remote("https://gitlab.example.com/group/subgroup/repo.git") == "gitlab.example.com/group/subgroup/repo"


def test_canonical_remote_http_without_git_suffix():
    """HTTP URL without .git suffix normalizes correctly."""
    assert canonical_remote("http://github.com/example/foo") == "github.com/example/foo"


def test_canonical_remote_git_protocol():
    """git:// protocol normalizes correctly."""
    assert canonical_remote("git://github.com/example/foo.git") == "github.com/example/foo"


def test_canonical_remote_empty():
    """Empty or whitespace remote returns empty string."""
    assert canonical_remote("") == ""
    assert canonical_remote("   ") == ""


def test_canonical_remote_lowercase_hostname():
    """Only hostname is lowercased; repo path preserves case."""
    assert canonical_remote("https://GitHub.com/Example/Repo.git") == "github.com/Example/Repo"


def test_canonical_remote_hostname_case_already_canonical():
    """Already-canonical input with mixed-case hostname must still lowercase host."""
    assert canonical_remote("GitHub.com/example/foo") == "github.com/example/foo"
    assert canonical_remote("GITHUB.com/Owner/Repo") == "github.com/Owner/Repo"


# ================================================================
# SSH port handling
# ================================================================

def test_canonical_remote_ssh_port():
    """Explicit SSH port is transport metadata, not repository identity."""
    assert canonical_remote("ssh://git@git.example.com:2222/group/repo.git") == "git.example.com/group/repo"
    assert canonical_remote("ssh://git@git.example.com:22/group/repo.git") == "git.example.com/group/repo"


# ================================================================
# Credential sanitization
# ================================================================

def test_sanitize_remote_token():
    """Tokens in URL auth must be stripped."""
    assert sanitize_remote("https://TOKEN@github.com/example/foo.git") == "https://github.com/example/foo.git"


def test_sanitize_remote_user_pass():
    """user:pass@ must be stripped."""
    assert sanitize_remote("https://user:pass@github.com/example/foo.git") == "https://github.com/example/foo.git"


def test_sanitize_remote_scp_pass_through():
    """SCP-style git@host:path has no embedded tokens — passes through."""
    assert sanitize_remote("git@github.com:euthm/foo.git") == "git@github.com:euthm/foo.git"


def test_sanitize_remote_ssh_no_creds():
    """ssh://git@host has no credentials to strip (git is the SSH user, not a token)."""
    assert sanitize_remote("ssh://git@git.example.com:2222/group/repo.git") == "ssh://git@git.example.com:2222/group/repo.git"


def test_sanitize_remote_empty():
    """Empty or whitespace input returns empty."""
    assert sanitize_remote("") == ""
    assert sanitize_remote("   ") == ""


def test_impl_provenance_strips_credentials(storage):
    """Parser must not store credential-bearing URLs in provenance."""
    policy = ImplementationGatePolicy(storage)
    prov = {
        "repo_remote_sanitized": "https://ghp_ABCDEFGHIJKLMNOPQRST@github.com/example/project.git",
        "repo_remote_canonical": "github.com/example/project",
        "commit": "abcdef1234567890",
    }
    storage.create_ko(mk_impl_claim(
        "claim-creds",
        "Token in URL",
        impl_prov=prov,
        declared_remotes=["github.com/example/project"],
    ))
    result = policy.evaluate_gates("claim-creds")
    assert result["provenance"]["status"] == "pass"
    assert result["scope"]["status"] == "pass"
    # Ensure no token appears in evidence or reason
    for gate_key in ("provenance", "scope", "test"):
        reason = result.get(gate_key, {}).get("reason", "")
        evidence = result.get(gate_key, {}).get("evidence", [])
        assert "ghp_ABCDEFGHIJKLMNOPQRST" not in reason, f"Token leaked in {gate_key} reason"
        for e in evidence:
            assert "ghp_ABCDEFGHIJKLMNOPQRST" not in e, f"Token leaked in {gate_key} evidence"


# ================================================================
# Legacy test still validates backward compat with repo_remote field
# ================================================================

def test_backward_compat_repo_remote_field(storage):
    """Old claims using only repo_remote should still work via backward compat parsing."""
    policy = ImplementationGatePolicy(storage)
    prov = {
        "repo_remote": "git@github.com:example/project.git",
        "repo_path": "/src/project",
        "branch": "main",
        "commit": "da827a9",
        "test_run_id": "test-legacy",
        "test_result_sha256": "ab" * 32,
    }
    storage.create_ko(mk_impl_claim(
        "claim-legacy",
        "Legacy repo_remote format",
        impl_prov=prov,
        declared_remotes=["https://github.com/example/project"],
    ))
    test_ko = KnowledgeObject(
        id="test-legacy", type=KOType.EVIDENCE_ITEM, title="Test run",
        content="", truth_category=TruthCategory.VALIDATION_RESULT,
        epistemic_status=EpistemicStatus.VALIDATED, confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="pytest", author="ci", independent=True),
    )
    storage.create_ko(test_ko)
    result = policy.evaluate_gates("claim-legacy")
    assert result["provenance"]["status"] == "pass"
    assert result["scope"]["status"] == "pass"
    assert result["test"]["status"] == "pass"
