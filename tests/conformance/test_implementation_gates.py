# FILE: tests/conformance/test_implementation_gates.py
"""Conformance tests for ImplementationGatePolicy — N-IMPL-PROV.

Tests the six gates for implementation-bearing claims:
  provenance → scope → worktree → test → falsifiability → dependency

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
    """An 'implemented' claim on a remote not declared in scope → BLOCK."""
    policy = ImplementationGatePolicy(storage)
    prov = {
        "repo_remote_canonical": "github.com/example/antares-pilot",
        "commit": "60a5dc881d8f39ab8365b4fc9c9b93f4b0d47dce",
        "worktree_clean": True,
    }
    storage.create_ko(mk_impl_claim(
        "claim-remote-mismatch",
        "Remote not in scope",
        impl_prov=prov,
        declared_remotes=["github.com/example/superretometer"],
    ))
    result = policy.evaluate_gates("claim-remote-mismatch")
    assert result["scope"]["status"] == "block", f"Expected BLOCK, got: {result['scope']['reason']}"
    assert not result["design_bearing"]


# ================================================================
# TEST 4: Remote match → PASS
# ================================================================

def test_remote_match_pass(storage):
    """With complete test evidence, remote match → all gates PASS."""
    policy = ImplementationGatePolicy(storage)
    remote = "github.com/example/project"
    commit = "a1b2c3d4e5f6"
    prov = {
        "repo_remote_canonical": remote,
        "commit": commit,
        "branch": "implementation-provenance",
        "worktree_clean": True,
        "test_run_id": "test-pass",
        "validator_ko_id": "validator-pass",
        "test_command": "pytest -v",
        "test_exit_code": 0,
        "test_result_sha256": "deadbeef" * 8,
        "tested_commit": commit,
        "test_timestamp": "2026-01-01T00:00:00Z",
    }
    storage.create_ko(_mk_claim_with_validators(
        "claim-remote-match",
        "Implementation provenance spec merged",
        impl_prov=prov,
        declared_remotes=[remote],
        validators=[_mk_falsifiable_validator("val-rm")],
    ))
    storage.create_ko(_mk_validator("validator-pass"))
    result = policy.evaluate_gates("claim-remote-match")
    assert result["provenance"]["status"] == "pass"
    assert result["scope"]["status"] == "pass"
    assert result["worktree"]["status"] == "pass"
    assert result["test"]["status"] == "pass"
    assert result["falsifiability"]["status"] == "pass"
    assert result["dependency"]["status"] == "pass"
    assert result["design_bearing"]


# ================================================================
# TEST 5: Missing test run → BLOCK
# ================================================================

def test_missing_test_run(storage):
    """No test_run_id → test gate UNKNOWN (not BLOCK — insufficient evidence)."""
    policy = ImplementationGatePolicy(storage)
    prov = {
        "repo_remote_canonical": "github.com/example/project",
        "commit": "da827a9",
        "worktree_clean": True,
    }
    storage.create_ko(mk_impl_claim(
        "claim-no-test",
        "No test run",
        impl_prov=prov,
        declared_remotes=["github.com/example/project"],
    ))
    result = policy.evaluate_gates("claim-no-test")
    assert result["test"]["status"] == "unknown"
    assert not result["design_bearing"]


# ================================================================
# TEST 6: Remote normalization (git@ vs https)
# ================================================================

def test_remote_normalization(storage):
    """Remote match should survive git@ → https normalization."""
    policy = ImplementationGatePolicy(storage)
    prov = {
        "repo_remote_canonical": "github.com/example/project",
        "commit": "da827a9",
        "worktree_clean": True,
        "test_run_id": "test-norm",
        "validator_ko_id": "validator-norm",
        "test_command": "pytest",
        "test_exit_code": 0,
        "test_result_sha256": "cafe" * 16,
        "tested_commit": "da827a9",
    }
    storage.create_ko(mk_impl_claim(
        "claim-normalize",
        "HTTPS remote matches git@ declaration",
        impl_prov=prov,
        declared_remotes=["git@github.com:example/project.git"],
    ))
    storage.create_ko(_mk_validator("validator-norm"))
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
# Legacy test: backward compat with repo_remote field (D1.6)
# Legacy provenance is incomplete → test gate UNKNOWN, not PASS
# ================================================================

def test_backward_compat_repo_remote_field(storage):
    """Old claims using only repo_remote + partial test evidence → provenance/scope PASS, test UNKNOWN.

    Legacy test provenance (test_run_id + test_result_sha256 without validator_ko_id,
    tested_commit, test_command, test_exit_code) does NOT yield PASS under hardened semantics.
    """
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
    # Legacy test provenance is incomplete → UNKNOWN, not PASS
    assert result["test"]["status"] == "unknown", \
        f"Legacy test should be UNKNOWN under hardened semantics, got {result['test']['status']}"
    assert not result["design_bearing"]


# ================================================================
# CH-IMPL-007: clean worktree + complete test chain → PASS
# ================================================================

def _mk_validator(ko_id):
    """Create a validator KO for test evidence."""
    return KnowledgeObject(
        id=ko_id, type=KOType.EVIDENCE_ITEM, title="Validator KO",
        content="", truth_category=TruthCategory.VALIDATION_RESULT,
        epistemic_status=EpistemicStatus.VALIDATED, confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="pytest", author="ci", independent=True),
    )


def _mk_complete_prov(remote, commit, validator_id="validator-1",
                       worktree_clean=True, worktree_diff="",
                       tested_commit=None, tested_diff="",
                       exit_code=0):
    """Build a complete implementation provenance dict."""
    if tested_commit is None:
        tested_commit = commit
    return {
        "repo_remote_canonical": remote,
        "commit": commit,
        "worktree_clean": worktree_clean,
        "worktree_diff_sha256": worktree_diff,
        "test_run_id": "run-12345",
        "validator_ko_id": validator_id,
        "test_command": "pytest tests/ -v",
        "test_exit_code": exit_code,
        "test_result_sha256": "ff" * 32,
        "tested_commit": tested_commit,
        "tested_worktree_diff_sha256": tested_diff,
        "test_timestamp": "2026-01-01T00:00:00Z",
    }


def test_ch_impl_007_complete_chain_pass(storage):
    """Clean worktree + exact commit + matching complete test → all gates PASS."""
    policy = ImplementationGatePolicy(storage)
    remote = "github.com/example/project"
    commit = "abcdef1234567890"
    prov = _mk_complete_prov(remote, commit)
    storage.create_ko(_mk_claim_with_validators(
        "claim-007",
        "Complete evidence chain",
        impl_prov=prov,
        declared_remotes=[remote],
        validators=[_mk_falsifiable_validator("val-007")],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-007")
    assert result["provenance"]["status"] == "pass"
    assert result["scope"]["status"] == "pass"
    assert result["worktree"]["status"] == "pass"
    assert result["test"]["status"] == "pass"
    assert result["falsifiability"]["status"] == "pass"
    assert result["design_bearing"]


# ================================================================
# CH-IMPL-008: dirty worktree without diff hash → BLOCK
# ================================================================

def test_ch_impl_008_dirty_no_diff_block(storage):
    """Dirty worktree without diff hash → worktree gate BLOCK."""
    policy = ImplementationGatePolicy(storage)
    prov = _mk_complete_prov("github.com/example/project", "abcdef1234567890",
                              worktree_clean=False, worktree_diff="")
    storage.create_ko(mk_impl_claim(
        "claim-008", "Dirty no diff", impl_prov=prov,
        declared_remotes=["github.com/example/project"],
    ))
    result = policy.evaluate_gates("claim-008")
    assert result["worktree"]["status"] == "block"
    assert not result["design_bearing"]


# ================================================================
# CH-IMPL-009: dirty worktree with diff hash → UNKNOWN (not PASS)
# ================================================================

def test_ch_impl_009_dirty_with_diff_unknown(storage):
    """Dirty worktree with diff hash → worktree gate UNKNOWN, never PASS."""
    policy = ImplementationGatePolicy(storage)
    diff_hash = "aa" * 32
    prov = _mk_complete_prov("github.com/example/project", "abcdef1234567890",
                              worktree_clean=False, worktree_diff=diff_hash,
                              tested_diff=diff_hash)
    storage.create_ko(mk_impl_claim(
        "claim-009", "Dirty with diff", impl_prov=prov,
        declared_remotes=["github.com/example/project"],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-009")
    assert result["worktree"]["status"] == "unknown"
    assert result["worktree"]["status"] != "pass"


# ================================================================
# CH-IMPL-010: claim commit != tested_commit → BLOCK
# ================================================================

def test_ch_impl_010_commit_mismatch_block(storage):
    """tested_commit != claim.commit → test gate BLOCK."""
    policy = ImplementationGatePolicy(storage)
    prov = _mk_complete_prov("github.com/example/project", "aaaaaaaaaaaaaaaa",
                              tested_commit="bbbbbbbbbbbbbbbb")
    storage.create_ko(mk_impl_claim(
        "claim-010", "Commit mismatch", impl_prov=prov,
        declared_remotes=["github.com/example/project"],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-010")
    assert result["test"]["status"] == "block"
    assert not result["design_bearing"]


# ================================================================
# CH-IMPL-011: dirty diff mismatch → BLOCK
# ================================================================

def test_ch_impl_011_dirty_diff_mismatch_block(storage):
    """claim dirty diff != tested dirty diff → test gate BLOCK."""
    policy = ImplementationGatePolicy(storage)
    prov = _mk_complete_prov("github.com/example/project", "abcdef1234567890",
                              worktree_clean=False, worktree_diff="aa" * 32,
                              tested_diff="bb" * 32)
    storage.create_ko(mk_impl_claim(
        "claim-011", "Dirty diff mismatch", impl_prov=prov,
        declared_remotes=["github.com/example/project"],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-011")
    assert result["test"]["status"] == "block"


# ================================================================
# CH-IMPL-012: test_exit_code != 0 → BLOCK
# ================================================================

def test_ch_impl_012_nonzero_exit_block(storage):
    """test_exit_code != 0 → test gate BLOCK."""
    policy = ImplementationGatePolicy(storage)
    prov = _mk_complete_prov("github.com/example/project", "abcdef1234567890",
                              exit_code=1)
    storage.create_ko(mk_impl_claim(
        "claim-012", "Failed tests", impl_prov=prov,
        declared_remotes=["github.com/example/project"],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-012")
    assert result["test"]["status"] == "block"


# ================================================================
# CH-IMPL-013: result hash exists but command missing → never PASS
# ================================================================

def test_ch_impl_013_no_command_unknown(storage):
    """test_command missing → test gate UNKNOWN, never PASS."""
    policy = ImplementationGatePolicy(storage)
    prov = _mk_complete_prov("github.com/example/project", "abcdef1234567890")
    prov["test_command"] = ""
    storage.create_ko(mk_impl_claim(
        "claim-013", "No command", impl_prov=prov,
        declared_remotes=["github.com/example/project"],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-013")
    assert result["test"]["status"] == "unknown"
    assert result["test"]["status"] != "pass"


# ================================================================
# CH-IMPL-014: test_run_id exists but validator_ko_id absent → never PASS
# ================================================================

def test_ch_impl_014_no_validator_unknown(storage):
    """validator_ko_id absent → test gate UNKNOWN, never PASS."""
    policy = ImplementationGatePolicy(storage)
    prov = _mk_complete_prov("github.com/example/project", "abcdef1234567890",
                              validator_id="")
    storage.create_ko(mk_impl_claim(
        "claim-014", "No validator", impl_prov=prov,
        declared_remotes=["github.com/example/project"],
    ))
    result = policy.evaluate_gates("claim-014")
    assert result["test"]["status"] == "unknown"


# ================================================================
# CH-IMPL-015: validator exists but test_run_id absent → never PASS
# ================================================================

def test_ch_impl_015_no_test_run_unknown(storage):
    """test_run_id absent → test gate UNKNOWN, never PASS."""
    policy = ImplementationGatePolicy(storage)
    prov = _mk_complete_prov("github.com/example/project", "abcdef1234567890")
    prov["test_run_id"] = ""
    storage.create_ko(mk_impl_claim(
        "claim-015", "No test run", impl_prov=prov,
        declared_remotes=["github.com/example/project"],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-015")
    assert result["test"]["status"] == "unknown"


# ================================================================
# CH-IMPL-016: complete successful validation → PASS
# ================================================================

def test_ch_impl_016_complete_success(storage):
    """All evidence present and consistent → all gates PASS, design-bearing."""
    policy = ImplementationGatePolicy(storage)
    remote = "github.com/example/project"
    commit = "abcdef1234567890"
    prov = _mk_complete_prov(remote, commit)
    storage.create_ko(_mk_claim_with_validators(
        "claim-016", "Full validation", impl_prov=prov,
        declared_remotes=[remote],
        validators=[_mk_falsifiable_validator("val-016")],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-016")
    assert result["provenance"]["status"] == "pass"
    assert result["scope"]["status"] == "pass"
    assert result["worktree"]["status"] == "pass"
    assert result["test"]["status"] == "pass"
    assert result["design_bearing"]


# ================================================================
# Helpers for falsifiability and dependency tests
# ================================================================

def _mk_falsifiable_validator(ko_id, what_would_falsify="pytest tests/ fails"):
    """Create a FalsifiableValidator with what_would_falsify."""
    return FalsifiableValidator(
        id=ko_id,
        description="Test validation",
        what_would_falsify=what_would_falsify,
        passes=True,
    )


def _mk_claim_with_validators(ko_id, title, impl_prov=None, declared_remotes=None,
                               validators=None, scope=""):
    """Create an implementation-bearing claim KO with validators."""
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
# CH-IMPL-017: complete validation + falsifier → falsifiability PASS
# ================================================================

def test_ch_impl_017_falsifier_present(storage):
    policy = ImplementationGatePolicy(storage)
    remote = "github.com/example/project"
    commit = "abcdef1234567890"
    prov = _mk_complete_prov(remote, commit)
    storage.create_ko(_mk_claim_with_validators(
        "claim-017", "Has falsifier", impl_prov=prov,
        declared_remotes=[remote],
        validators=[_mk_falsifiable_validator("val-017")],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-017")
    assert result["falsifiability"]["status"] == "pass"
    assert result["design_bearing"]


# ================================================================
# CH-IMPL-018: validator exists but no what_would_falsify → UNKNOWN
# ================================================================

def test_ch_impl_018_empty_falsifier_unknown(storage):
    policy = ImplementationGatePolicy(storage)
    remote = "github.com/example/project"
    commit = "abcdef1234567890"
    prov = _mk_complete_prov(remote, commit)
    storage.create_ko(_mk_claim_with_validators(
        "claim-018", "Empty falsifier", impl_prov=prov,
        declared_remotes=[remote],
        validators=[FalsifiableValidator(id="val-018", what_would_falsify="")],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-018")
    assert result["falsifiability"]["status"] == "unknown"
    assert not result["design_bearing"]


# ================================================================
# CH-IMPL-019: no applicable validator → UNKNOWN / UNGROUNDED
# ================================================================

def test_ch_impl_019_no_validator_ungrounded(storage):
    policy = ImplementationGatePolicy(storage)
    remote = "github.com/example/project"
    commit = "abcdef1234567890"
    prov = _mk_complete_prov(remote, commit)
    storage.create_ko(_mk_claim_with_validators(
        "claim-019", "No validators", impl_prov=prov,
        declared_remotes=[remote],
        validators=[],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-019")
    assert result["falsifiability"]["status"] == "unknown"
    assert not result["design_bearing"]


# ================================================================
# CH-IMPL-020: identical submodule pins → dependency PASS
# ================================================================

def test_ch_impl_020_identical_submodule_pins(storage):
    policy = ImplementationGatePolicy(storage)
    remote = "github.com/example/project"
    commit = "abcdef1234567890"
    sub_pins = {
        "lib-a": {
            "path": "vendor/lib-a",
            "repo_remote_canonical": "github.com/example/lib-a",
            "commit": "1111111111111111",
        }
    }
    prov = _mk_complete_prov(remote, commit)
    prov["submodule_pins"] = sub_pins
    prov["tested_submodule_pins"] = dict(sub_pins)
    storage.create_ko(_mk_claim_with_validators(
        "claim-020", "Matching submodules", impl_prov=prov,
        declared_remotes=[remote],
        validators=[_mk_falsifiable_validator("val-020")],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-020")
    assert result["dependency"]["status"] == "pass"


# ================================================================
# CH-IMPL-021: submodule commit mismatch → BLOCK
# ================================================================

def test_ch_impl_021_submodule_commit_mismatch(storage):
    policy = ImplementationGatePolicy(storage)
    remote = "github.com/example/project"
    commit = "abcdef1234567890"
    prov = _mk_complete_prov(remote, commit)
    prov["submodule_pins"] = {
        "lib-a": {
            "repo_remote_canonical": "github.com/example/lib-a",
            "commit": "1111111111111111",
        }
    }
    prov["tested_submodule_pins"] = {
        "lib-a": {
            "repo_remote_canonical": "github.com/example/lib-a",
            "commit": "2222222222222222",
        }
    }
    storage.create_ko(_mk_claim_with_validators(
        "claim-021", "Submodule commit mismatch", impl_prov=prov,
        declared_remotes=[remote],
        validators=[_mk_falsifiable_validator("val-021")],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-021")
    assert result["dependency"]["status"] == "block"
    assert not result["design_bearing"]


# ================================================================
# CH-IMPL-022: same commit, different canonical remote → BLOCK
# ================================================================

def test_ch_impl_022_submodule_remote_mismatch(storage):
    policy = ImplementationGatePolicy(storage)
    remote = "github.com/example/project"
    commit = "abcdef1234567890"
    prov = _mk_complete_prov(remote, commit)
    prov["submodule_pins"] = {
        "lib-a": {
            "repo_remote_canonical": "github.com/example/lib-a",
            "commit": "1111111111111111",
        }
    }
    prov["tested_submodule_pins"] = {
        "lib-a": {
            "repo_remote_canonical": "github.com/fork/lib-a",
            "commit": "1111111111111111",
        }
    }
    storage.create_ko(_mk_claim_with_validators(
        "claim-022", "Submodule remote mismatch", impl_prov=prov,
        declared_remotes=[remote],
        validators=[_mk_falsifiable_validator("val-022")],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-022")
    assert result["dependency"]["status"] == "block"


# ================================================================
# CH-IMPL-023: claim-bearing submodule has no tested pin → UNKNOWN
# ================================================================

def test_ch_impl_023_submodule_no_tested_pin(storage):
    policy = ImplementationGatePolicy(storage)
    remote = "github.com/example/project"
    commit = "abcdef1234567890"
    prov = _mk_complete_prov(remote, commit)
    prov["submodule_pins"] = {
        "lib-a": {
            "repo_remote_canonical": "github.com/example/lib-a",
            "commit": "1111111111111111",
        }
    }
    storage.create_ko(_mk_claim_with_validators(
        "claim-023", "Submodule no tested pin", impl_prov=prov,
        declared_remotes=[remote],
        validators=[_mk_falsifiable_validator("val-023")],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-023")
    assert result["dependency"]["status"] == "unknown"


# ================================================================
# CH-IMPL-024: valid test_timestamp → complete provenance eligible
# ================================================================

def test_ch_impl_024_valid_timestamp(storage):
    policy = ImplementationGatePolicy(storage)
    remote = "github.com/example/project"
    commit = "abcdef1234567890"
    prov = _mk_complete_prov(remote, commit)
    prov["test_timestamp"] = "2026-01-01T12:30:00Z"
    storage.create_ko(_mk_claim_with_validators(
        "claim-024", "Valid timestamp", impl_prov=prov,
        declared_remotes=[remote],
        validators=[_mk_falsifiable_validator("val-024")],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-024")
    assert result["test"]["status"] == "pass"


# ================================================================
# CH-IMPL-025: missing test_timestamp → UNKNOWN
# ================================================================

def test_ch_impl_025_missing_timestamp_unknown(storage):
    policy = ImplementationGatePolicy(storage)
    remote = "github.com/example/project"
    commit = "abcdef1234567890"
    prov = _mk_complete_prov(remote, commit)
    prov["test_timestamp"] = ""
    storage.create_ko(_mk_claim_with_validators(
        "claim-025", "Missing timestamp", impl_prov=prov,
        declared_remotes=[remote],
        validators=[_mk_falsifiable_validator("val-025")],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-025")
    assert result["test"]["status"] == "unknown"


# ================================================================
# CH-IMPL-026: invalid test_timestamp → BLOCK
# ================================================================

def test_ch_impl_026_invalid_timestamp_block(storage):
    policy = ImplementationGatePolicy(storage)
    remote = "github.com/example/project"
    commit = "abcdef1234567890"
    prov = _mk_complete_prov(remote, commit)
    prov["test_timestamp"] = "not-a-timestamp"
    storage.create_ko(_mk_claim_with_validators(
        "claim-026", "Invalid timestamp", impl_prov=prov,
        declared_remotes=[remote],
        validators=[_mk_falsifiable_validator("val-026")],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-026")
    assert result["test"]["status"] == "block"


# ================================================================
# CH-IMPL-027: naive timestamp (no timezone) → UNKNOWN
# ================================================================

def test_ch_impl_027_naive_timestamp_unknown(storage):
    """Naive ISO 8601 timestamp (no TZ offset) → UNKNOWN, not portable."""
    policy = ImplementationGatePolicy(storage)
    remote = "github.com/example/project"
    commit = "abcdef1234567890"
    prov = _mk_complete_prov(remote, commit)
    prov["test_timestamp"] = "2026-09-06T20:23:00"  # No timezone
    storage.create_ko(_mk_claim_with_validators(
        "claim-027", "Naive timestamp", impl_prov=prov,
        declared_remotes=[remote],
        validators=[_mk_falsifiable_validator("val-027")],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-027")
    assert result["test"]["status"] == "unknown"


# ================================================================
# CH-IMPL-028: timezone-aware timestamp → PASS contribution
# ================================================================

def test_ch_impl_028_tz_aware_timestamp_pass(storage):
    """Timezone-aware ISO 8601 with offset → contributes to PASS."""
    policy = ImplementationGatePolicy(storage)
    remote = "github.com/example/project"
    commit = "abcdef1234567890"
    prov = _mk_complete_prov(remote, commit)
    prov["test_timestamp"] = "2026-09-06T20:23:00+02:00"
    storage.create_ko(_mk_claim_with_validators(
        "claim-028", "TZ-aware timestamp", impl_prov=prov,
        declared_remotes=[remote],
        validators=[_mk_falsifiable_validator("val-028")],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-028")
    assert result["test"]["status"] == "pass"


# ================================================================
# CH-IMPL-029: no submodules → dependency PASS
# ================================================================

def test_ch_impl_029_no_submodules_pass(storage):
    """No submodules declared → dependency gate PASS (not applicable)."""
    policy = ImplementationGatePolicy(storage)
    remote = "github.com/example/project"
    commit = "abcdef1234567890"
    prov = _mk_complete_prov(remote, commit)
    storage.create_ko(_mk_claim_with_validators(
        "claim-029", "No submodules", impl_prov=prov,
        declared_remotes=[remote],
        validators=[_mk_falsifiable_validator("val-029")],
    ))
    storage.create_ko(_mk_validator("validator-1"))
    result = policy.evaluate_gates("claim-029")
    assert result["dependency"]["status"] == "pass"


# ================================================================
# CH-IMPL-030: worktree unobserved → UNKNOWN
# ================================================================

def test_ch_impl_030_worktree_unobserved_unknown(storage):
    """worktree_clean not set (None) → worktree gate UNKNOWN."""
    policy = ImplementationGatePolicy(storage)
    remote = "github.com/example/project"
    commit = "abcdef1234567890"
    prov = {
        "repo_remote_canonical": remote,
        "commit": commit,
        "test_run_id": "run-x",
        "validator_ko_id": "validator-30",
        "test_command": "pytest",
        "test_exit_code": 0,
        "test_result_sha256": "cc" * 32,
        "tested_commit": commit,
        "test_timestamp": "2026-01-01T00:00:00Z",
    }
    storage.create_ko(_mk_claim_with_validators(
        "claim-030", "Unobserved worktree", impl_prov=prov,
        declared_remotes=[remote],
        validators=[_mk_falsifiable_validator("val-030")],
    ))
    storage.create_ko(_mk_validator("validator-30"))
    result = policy.evaluate_gates("claim-030")
    assert result["worktree"]["status"] == "unknown"
