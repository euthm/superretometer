# FILE: tests/conformance/test_issue12_semantic_decisions.py
"""Regression tests for Issue #12 — five semantic decisions + Gate 7."""
import hashlib
from pathlib import Path

import pytest

from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus, ConfidenceLevel,
    RelationType, Provenance, Relation, DerivationRelation, DerivationType,
    Dataset, WarrantStatus, AntiPattern, FalsifiableValidator,
)
from cognitive_harness.storage.inmemory import InMemoryStorage
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer
from cognitive_harness.analysis.implementation_gate_policy import ImplementationGatePolicy


def mk(ko_id, title, truth_cat, **kw):
    kw.setdefault("provenance", Provenance(source=ko_id, author="test", independent=True))
    return KnowledgeObject(id=ko_id, title=title, truth_category=truth_cat, **kw)


class TestProvenanceSourceIndependence:
    def test_same_source_collapse_to_one_root(self):
        storage = InMemoryStorage()
        same = dict(source="ASME-BPVC-2023-VIII", author="one-person")
        storage.create_ko(mk("a", "allowable stress", TruthCategory.SOURCED_MATERIAL_DATA,
                             provenance=Provenance(**same, independent=True)))
        storage.create_ko(mk("b", "joint efficiency", TruthCategory.SOURCED_MATERIAL_DATA,
                             provenance=Provenance(**same, independent=True)))
        storage.create_ko(mk("c", "wall thickness adequate", TruthCategory.MODEL_DERIVED))
        storage.create_relation("a", "c", RelationType.SUPPORTS)
        storage.create_relation("b", "c", RelationType.SUPPORTS)

        analyzer = WarrantAnalyzer(storage)
        result = analyzer.compute_warrant("c")
        assert "ASME-BPVC-2023-VIII" in result.independence.root_sets.get("a", set())
        assert "ASME-BPVC-2023-VIII" in result.independence.root_sets.get("b", set())
        assert result.independence.independent_root_count == 1
        assert result.warrant_status == WarrantStatus.CONDITIONALLY_WARRANTED

    def test_different_sources_remain_independent(self):
        storage = InMemoryStorage()
        storage.create_ko(mk("a", "stress", TruthCategory.SOURCED_MATERIAL_DATA,
                             provenance=Provenance(source="ASME", author="eng", independent=True)))
        storage.create_ko(mk("b", "efficiency", TruthCategory.SOURCED_MATERIAL_DATA,
                             provenance=Provenance(source="AWS", author="eng", independent=True)))
        storage.create_ko(mk("c", "adequate", TruthCategory.MODEL_DERIVED))
        storage.create_relation("a", "c", RelationType.SUPPORTS)
        storage.create_relation("b", "c", RelationType.SUPPORTS)

        result = WarrantAnalyzer(storage).compute_warrant("c")
        assert result.independence.independent_root_count == 2
        assert result.warrant_status == WarrantStatus.WARRANTED


class TestProvenanceIndependenceDefault:
    def test_unspecified_independent_is_none(self):
        p = Provenance(source="test", author="test")
        assert p.independent is None

    def test_no_auto_provenance(self):
        ko = KnowledgeObject(id="x", title="x")
        assert ko.provenance is None

    def test_none_independent_is_not_grounding(self):
        storage = InMemoryStorage()
        storage.create_ko(mk("e", "evidence", TruthCategory.SOURCED_MATERIAL_DATA,
                             provenance=Provenance(source="src", author="lab", independent=None)))
        storage.create_ko(mk("c", "conclusion", TruthCategory.MODEL_DERIVED))
        storage.create_relation("e", "c", RelationType.SUPPORTS)
        result = WarrantAnalyzer(storage).compute_warrant("c")
        assert result.warrant_status != WarrantStatus.WARRANTED


class TestSelfReferentialEvidence:
    def test_normal_evidence_not_circular(self):
        storage = InMemoryStorage()
        for i, src in enumerate(["lab-a", "lab-b", "lab-c"]):
            storage.create_ko(mk(f"m{i}", f"measurement {i}", TruthCategory.PHYSICAL_OBSERVATION,
                                 provenance=Provenance(source=src, author="lab", independent=True),
                                 evidence_ids=[f"ev{i}"]))
            storage.add_evidence(f"ev{i}", f"m{i}", "verified", "data", [])
        diagnoses = WarrantAnalyzer(storage).detect_all_anti_patterns()
        circular = [d for d in diagnoses if d.pattern == AntiPattern.CIRCULAR_DEPENDENCY]
        assert len(circular) == 0

    def test_evidence_source_ko_id_accepted(self):
        storage = InMemoryStorage()
        storage.create_ko(mk("claim", "claim", TruthCategory.PHYSICAL_OBSERVATION,
                             provenance=Provenance(source="src", author="test", independent=True),
                             evidence_ids=["ev1"]))
        storage.add_evidence("ev1", "claim", "verified", "obs", [], source_ko_id="claim")
        ev = storage.get_evidence("ev1")
        assert ev["source_ko_id"] == "claim"


class TestImplementationGateSelfConsistency:
    def test_fabricated_claim_passes_if_consistent(self):
        storage = InMemoryStorage()
        storage.create_ko(mk("val", "validator", TruthCategory.VALIDATION_RESULT))
        ko = mk("claim", "fabricated", TruthCategory.MODEL_DERIVED,
                validators=[FalsifiableValidator(
                    id="fv1", what_would_falsify="the moon turning into cheese",
                )])
        ko.content = {
            "implementation_provenance": {
                "repo_remote_canonical": "github.com/fake/repo",
                "commit": "0" * 40, "worktree_clean": True,
                "test_run_id": "invented", "validator_ko_id": "val",
                "test_command": "true", "test_exit_code": 0,
                "test_result_sha256": "ff" * 32, "tested_commit": "0" * 40,
                "test_timestamp": "2026-01-01T00:00:00Z",
            },
            "declared_remotes": ["github.com/fake/repo"],
        }
        storage.create_ko(ko)
        result = ImplementationGatePolicy(storage).evaluate_gates("claim")
        for g in ("provenance", "scope", "worktree", "test", "falsifiability", "dependency"):
            assert result[g]["status"] == "pass"
        assert result["freshness"]["status"] == "unknown"


class TestStorageMutability:
    def test_get_ko_returns_mutable_reference(self):
        storage = InMemoryStorage()
        ko = mk("k", "mutable", TruthCategory.MODEL_DERIVED)
        storage.create_ko(ko)
        handle = storage.get_ko("k")
        assert handle is ko
        handle.title = "mutated"
        assert storage.get_ko("k").title == "mutated"


class TestFreshnessGate:
    def test_freshness_unknown_without_blob_digest(self):
        storage = InMemoryStorage()
        storage.create_ko(mk("val", "validator", TruthCategory.VALIDATION_RESULT))
        prov = {
            "repo_remote_canonical": "github.com/example/project",
            "commit": "abc123", "worktree_clean": True,
            "test_run_id": "r1", "validator_ko_id": "val",
            "test_command": "true", "test_exit_code": 0,
            "test_result_sha256": "ff" * 32, "tested_commit": "abc123",
            "test_timestamp": "2026-01-01T00:00:00Z",
        }
        storage.create_ko(mk("claim", "no digest", TruthCategory.MODEL_DERIVED,
                             content={"implementation_provenance": prov,
                                      "declared_remotes": ["github.com/example/project"]}))
        result = ImplementationGatePolicy(storage).evaluate_gates("claim")
        assert result["freshness"]["status"] == "unknown"

    def test_freshness_pass_with_matching_digest(self, tmp_path):
        storage = InMemoryStorage()
        storage.create_ko(mk("val", "validator", TruthCategory.VALIDATION_RESULT))
        test_file = tmp_path / "test.py"
        test_file.write_text("# test")
        digest = hashlib.sha256(test_file.read_bytes()).hexdigest()
        prov = {
            "repo_remote_canonical": "github.com/example/project",
            "commit": "abc123", "worktree_clean": True,
            "repo_path": str(tmp_path),
            "test_run_id": "r1", "validator_ko_id": "val",
            "test_command": "true", "test_exit_code": 0,
            "test_result_sha256": "ff" * 32, "tested_commit": "abc123",
            "test_timestamp": "2026-01-01T00:00:00Z",
            "blob_digest": digest, "blob_paths": ["test.py"],
        }
        storage.create_ko(mk("claim", "fresh", TruthCategory.MODEL_DERIVED,
                             content={"implementation_provenance": prov,
                                      "declared_remotes": ["github.com/example/project"]}))
        result = ImplementationGatePolicy(storage).evaluate_gates("claim")
        assert result["freshness"]["status"] == "pass"

    def test_freshness_block_on_drift(self, tmp_path):
        storage = InMemoryStorage()
        storage.create_ko(mk("val", "validator", TruthCategory.VALIDATION_RESULT))
        test_file = tmp_path / "test.py"
        test_file.write_text("# original")
        old_digest = hashlib.sha256(test_file.read_bytes()).hexdigest()
        prov = {
            "repo_remote_canonical": "github.com/example/project",
            "commit": "abc123", "worktree_clean": True,
            "repo_path": str(tmp_path),
            "test_run_id": "r1", "validator_ko_id": "val",
            "test_command": "true", "test_exit_code": 0,
            "test_result_sha256": "ff" * 32, "tested_commit": "abc123",
            "test_timestamp": "2026-01-01T00:00:00Z",
            "blob_digest": old_digest, "blob_paths": ["test.py"],
        }
        storage.create_ko(mk("claim", "drifted", TruthCategory.MODEL_DERIVED,
                             content={"implementation_provenance": prov,
                                      "declared_remotes": ["github.com/example/project"]}))
        test_file.write_text("# modified")
        result = ImplementationGatePolicy(storage).evaluate_gates("claim")
        assert result["freshness"]["status"] == "block"
        assert "Code drift detected" in result["freshness"]["reason"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
