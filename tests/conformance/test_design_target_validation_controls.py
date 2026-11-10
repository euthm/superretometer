"""Point 3: design-target fitting, in-sample validation, and a positive control.

These are synthetic structural tests, not evidence that a real model generalises.
The narrative, declared independence, successful validator and observations stay
the same: only dataset lineage changes. Both direct and multi-hop lineages must
produce the same decision through the public warrant and simulation-gate APIs.
"""

import pytest

from cognitive_harness.analysis.simulation_gate_policy import SimulationGatePolicy
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer
from cognitive_harness.model.ko import (
    AntiPattern,
    ConfidenceLevel,
    Dataset,
    DerivationRelation,
    DerivationType,
    EpistemicStatus,
    FalsifiableValidator,
    GateStatus,
    KnowledgeObject,
    KOType,
    Provenance,
    RelationType,
    TruthCategory,
    WarrantStatus,
)


def _case(storage, scenario, multi_hop):
    """Build identical declared results with one of three provenance layouts."""
    for name in ("run", "model"):
        storage.create_ko(KnowledgeObject(id=name, title=name))

    for name in ("lab-a", "lab-b"):
        storage.create_ko(KnowledgeObject(
            id=name,
            title="Recorded component measurement",
            truth_category=TruthCategory.PHYSICAL_OBSERVATION,
            provenance=Provenance(source=name, author="fixture", independent=True),
            evidence_ids=[f"record-{name}"],
        ))
        # F4: the observation's record must exist, not merely be named in a KO.
        storage.add_evidence(
            evidence_id=f"record-{name}", claim_id=name, status="pass",
            observation="Measured response = 10", records=[{"response": 10}],
            source_ko_id=name,
        )

    storage.create_ko(KnowledgeObject(
        id="claim", type=KOType.CONCLUSION,
        title="Component response meets the design target",
        truth_category=TruthCategory.MODEL_DERIVED,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="simulation", author="fixture", independent=False),
        scope="component benchmark",
        content={
            "simulation_provenance": {
                "result_artifact": "synthetic-result.json",
                "result_sha256": "a" * 64,
                "source_commit": "b" * 40,
                "source_path": "synthetic-model.py",
                "run_id": "run", "model_id": "model",
            },
            "scope_declaration": {
                "modeled_domain": "component benchmark",
                "system_boundary": "component benchmark",
                "included_components": ["component"],
                "excluded_components": [],
                "allowed_claim_classes": [], "disallowed_claim_classes": [],
            },
        },
        validators=[FalsifiableValidator(
            description="Compare measured and predicted response",
            what_would_falsify="Absolute error exceeds 1 response unit",
            passes=True, observation="Measured = 10, predicted = 10",
        )],
    ))

    train_source = "claim" if scenario == "design_target" else "lab-a"
    if multi_hop:
        # Cross both supported lineage representations: a KO derivation and
        # a graph edge, followed below by a derived-dataset hop.
        storage.create_ko(KnowledgeObject(
            id="training-transform", title="Prepared training input",
            derivation=DerivationRelation(
                derivation_type=DerivationType.MODELED,
                upstream_ko_ids=[train_source],
            ),
        ))
        storage.create_ko(KnowledgeObject(id="training-copy", title="Training input copy"))
        storage.create_relation("training-copy", "training-transform", RelationType.DERIVED_FROM)
        train_source = "training-copy"

    storage.create_dataset(Dataset(id="training-base", source_ko_id=train_source))
    storage.create_dataset(Dataset(id="training", derived_from_dataset_ids=["training-base"]))
    if scenario == "in_sample":
        # Different dataset IDs and a fresh 'pass' do not create a holdout.
        storage.create_dataset(Dataset(id="testing", derived_from_dataset_ids=["training-base"]))
    elif multi_hop:
        storage.create_dataset(Dataset(id="testing-base", source_ko_id="lab-b"))
        storage.create_dataset(Dataset(id="testing", derived_from_dataset_ids=["testing-base"]))
    else:
        storage.create_dataset(Dataset(id="testing", source_ko_id="lab-b"))

    storage.create_ko(KnowledgeObject(
        id="fit", title="Fitted response parameter",
        truth_category=TruthCategory.FITTED_PARAMETER,
        epistemic_status=EpistemicStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        provenance=Provenance(source="fit-report", author="fixture", independent=True),
        derivation=DerivationRelation(
            derivation_type=DerivationType.FITTED,
            training_dataset_id="training", test_dataset_id="testing",
        ),
    ))
    storage.create_relation("fit", "claim", RelationType.SUPPORTS)
    return (
        WarrantAnalyzer(storage).compute_warrant("claim"),
        SimulationGatePolicy(storage).evaluate_gates("claim"),
    )


def _assert_other_gates_pass(report):
    # A failure must be attributable to grounding, not incomplete metadata.
    for gate in (report.provenance, report.scope, report.falsifiability):
        assert gate.status == GateStatus.PASS, gate.reason


@pytest.mark.parametrize("multi_hop", [False, True], ids=["direct", "multi-hop"])
def test_fitting_on_design_target_is_blocked_even_with_separate_test_data(storage, multi_hop):
    warrant, report = _case(storage, "design_target", multi_hop)

    _assert_other_gates_pass(report)
    diagnoses = [d for d in warrant.anti_pattern_diagnoses
                 if d.pattern == AntiPattern.CALIBRATED_TO_CONCLUSION]
    assert diagnoses
    assert any({"fit", "claim"} <= set(d.offending_ko_ids) for d in diagnoses)
    assert warrant.warrant_status == WarrantStatus.UNWARRANTED
    assert report.reality.status == GateStatus.BLOCK
    assert not report.design_bearing


@pytest.mark.parametrize("multi_hop", [False, True], ids=["direct", "multi-hop"])
def test_in_sample_validation_with_distinct_dataset_ids_is_blocked(storage, multi_hop):
    warrant, report = _case(storage, "in_sample", multi_hop)

    _assert_other_gates_pass(report)
    # Require an explainable overlap diagnosis without deciding F2's name.
    diagnoses = [d for d in warrant.anti_pattern_diagnoses
                 if "fit" in d.offending_ko_ids]
    assert diagnoses
    assert any("lab-a" in d.shared_roots for d in diagnoses)
    assert warrant.warrant_status == WarrantStatus.UNWARRANTED
    assert report.reality.status == GateStatus.BLOCK
    assert not report.design_bearing


@pytest.mark.parametrize("multi_hop", [False, True], ids=["direct", "multi-hop"])
def test_independent_train_and_test_sources_are_a_passing_control(storage, multi_hop):
    warrant, report = _case(storage, "independent", multi_hop)

    _assert_other_gates_pass(report)
    assert warrant.anti_pattern_diagnoses == []
    assert warrant.warrant_status == WarrantStatus.WARRANTED
    assert "fit" in warrant.independent_kos
    assert report.reality.status == GateStatus.PASS
    assert report.design_bearing


@pytest.mark.parametrize("side", ["training", "testing"])
@pytest.mark.parametrize("broken_link", [
    "missing_source_ko", "missing_parent_dataset", "blank_source",
    "no_source_label", "empty_lineage", "cyclic_lineage",
])
def test_incomplete_lineage_cannot_become_independent_validation(storage, side, broken_link):
    _, control = _case(storage, "independent", False)
    assert control.design_bearing, "fixture must first demonstrate a passing control"

    dataset = storage.get_dataset("training-base" if side == "training" else "testing")
    if broken_link == "missing_source_ko":
        dataset.source_ko_id = "unregistered-source"
    elif broken_link == "missing_parent_dataset":
        # A valid branch must not conceal a second, unresolved branch.
        dataset.derived_from_dataset_ids = ["unregistered-parent"]
    elif broken_link in ("blank_source", "no_source_label"):
        storage.get_ko("lab-a" if side == "training" else "lab-b").provenance.source = (
            " \t " if broken_link == "blank_source" else ""
        )
    elif broken_link == "cyclic_lineage":
        dataset.source_ko_id = ""
        dataset.derived_from_dataset_ids = [side]
    else:
        dataset.source_ko_id = ""
        dataset.derived_from_dataset_ids = []

    _assert_missing_validation(storage)


@pytest.mark.parametrize("missing_dataset", ["no_holdout", "training", "testing"])
def test_missing_dataset_has_the_specific_missing_validation_diagnosis(storage, missing_dataset):
    _, control = _case(storage, "independent", False)
    assert control.design_bearing
    fit = storage.get_ko("fit")
    if missing_dataset == "no_holdout":
        fit.derivation.test_dataset_id = ""
    elif missing_dataset == "training":
        fit.derivation.training_dataset_id = "unregistered-training"
    else:
        fit.derivation.test_dataset_id = "unregistered-testing"

    _assert_missing_validation(storage)


def _assert_missing_validation(storage):
    warrant = WarrantAnalyzer(storage).compute_warrant("claim")
    report = SimulationGatePolicy(storage).evaluate_gates("claim")
    _assert_other_gates_pass(report)
    patterns = {d.pattern for d in warrant.anti_pattern_diagnoses}
    assert AntiPattern.MISSING_INDEPENDENT_VALIDATION in patterns
    assert AntiPattern.CALIBRATED_TO_CONCLUSION not in patterns
    assert warrant.warrant_status == WarrantStatus.UNWARRANTED
    assert "fit" not in warrant.independent_kos
    assert report.reality.status == GateStatus.BLOCK
    assert not report.design_bearing
