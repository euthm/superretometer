"""Adversarial warrant-bypass tests (found against v0.7.1, main 69d58f7).

Each finding has a negative control that is expected to FAIL until the
analyzer is fixed, and a positive control that must keep passing so the
fix cannot be "block everything".

  F1  CALIBRATED_TO_CONCLUSION never inspects the conclusion
  F2  "no hold-out" is mislabelled as calibrated_to_conclusion
  F3  provenance roots are compared as raw free-text strings
  F4  evidence_ids are never resolved against storage

A check that cannot fail is not evidence — these are the checks that
currently cannot fail.
"""
import pytest

from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, RelationType, Provenance,
    Relation, WarrantStatus, DerivationType, DerivationRelation, Dataset,
    AntiPattern,
)
from cognitive_harness.storage.inmemory import InMemoryStorage
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer

SCOPE = "adversarial-warrant-bypass"
CONCLUSION = "c-target-rpm-reached"


# ── helpers ──────────────────────────────────────────────────────────────

def _observation(storage, ko_id, source, *, register_evidence=True, relations=()):
    """Independent physical observation. Evidence is really registered
    unless register_evidence=False (then the id dangles)."""
    evidence_id = f"ev-{ko_id}"
    storage.create_ko(KnowledgeObject(
        id=ko_id, type=KOType.OBSERVATION, title=ko_id, content=ko_id,
        truth_category=TruthCategory.PHYSICAL_OBSERVATION,
        provenance=Provenance(source=source, author="lab", independent=True),
        evidence_ids=[evidence_id], relations=list(relations), scope=SCOPE,
    ))
    if register_evidence:
        storage.add_evidence(
            evidence_id=evidence_id, claim_id=ko_id, status="pass",
            observation="measured", records=[{"value": 1.0}], source_ko_id=ko_id,
        )


def _fitted_parameter(storage, ko_id, training_dataset_id, test_dataset_id):
    storage.create_ko(KnowledgeObject(
        id=ko_id, type=KOType.OBSERVATION, title=ko_id, content=ko_id,
        truth_category=TruthCategory.FITTED_PARAMETER,
        provenance=Provenance(source="fit", author="sim", independent=True),
        derivation=DerivationRelation(
            derivation_type=DerivationType.FITTED,
            training_dataset_id=training_dataset_id,
            test_dataset_id=test_dataset_id,
        ),
        scope=SCOPE,
    ))


def _conclusion(storage, relations=()):
    storage.create_ko(KnowledgeObject(
        id=CONCLUSION, type=KOType.MODEL_RESULT,
        title="Machine reaches target RPM", content="Simulation reports target RPM.",
        truth_category=TruthCategory.MODEL_DERIVED,
        provenance=Provenance(source="simulation", author="sim", independent=False),
        relations=list(relations), scope=SCOPE,
    ))


def _warrant(storage):
    return WarrantAnalyzer(storage).compute_warrant(CONCLUSION)


def _patterns(result):
    return {d.pattern for d in result.anti_pattern_diagnoses}


SUPPORTS_C = (Relation(type=RelationType.SUPPORTS, to=CONCLUSION),)
C_DEPENDS_ON_P = (Relation(type=RelationType.DEPENDS_ON, to="p-magnetic"),)


# ── F1: parameter trained on the conclusion itself ───────────────────────

def _f1_storage(training_dataset):
    """Conclusion depends on a fitted parameter; the test split is a
    genuinely unrelated bench observation, so train/test roots are disjoint."""
    s = InMemoryStorage()
    _observation(s, "bench-holdout", "bench series B")
    _observation(s, "bench-train", "bench series A")
    for ds in training_dataset:
        s.create_dataset(ds)
    s.create_dataset(Dataset(id="ds-test", name="hold-out", source_ko_id="bench-holdout"))
    _fitted_parameter(s, "p-magnetic", "ds-train", "ds-test")
    _conclusion(s, C_DEPENDS_ON_P)
    return s


def _assert_calibration_caught(result):
    assert result.warrant_status != WarrantStatus.WARRANTED, (
        "parameter trained on the conclusion must not yield WARRANTED")
    hits = [d for d in result.anti_pattern_diagnoses
            if d.pattern in (AntiPattern.CALIBRATED_TO_CONCLUSION,
                             AntiPattern.CIRCULAR_DEPENDENCY)]
    assert hits, f"no calibration/circularity diagnosis, got {_patterns(result)}"
    assert any("p-magnetic" in d.offending_ko_ids for d in hits)


def test_f1_training_dataset_sourced_from_conclusion():
    s = _f1_storage([Dataset(id="ds-train", name="train", source_ko_id=CONCLUSION)])
    _assert_calibration_caught(_warrant(s))


def test_f1_training_dataset_derived_from_dataset_sourced_from_conclusion():
    """Same loop, one dataset hop removed (derived_from_dataset_ids)."""
    s = _f1_storage([
        Dataset(id="ds-raw", name="raw", source_ko_id=CONCLUSION),
        Dataset(id="ds-train", name="train", derived_from_dataset_ids=["ds-raw"]),
    ])
    _assert_calibration_caught(_warrant(s))


def test_f1_training_source_derived_from_conclusion():
    """Same loop, one KO hop removed (DERIVED_FROM the conclusion)."""
    s = InMemoryStorage()
    _observation(s, "bench-holdout", "bench series B")
    s.create_ko(KnowledgeObject(
        id="rpm-trace", type=KOType.MODEL_RESULT, title="RPM trace", content="post-processed",
        truth_category=TruthCategory.MODEL_DERIVED,
        provenance=Provenance(source="simulation", author="sim", independent=False),
        relations=[Relation(type=RelationType.DERIVED_FROM, to=CONCLUSION)], scope=SCOPE,
    ))
    s.create_dataset(Dataset(id="ds-train", name="train", source_ko_id="rpm-trace"))
    s.create_dataset(Dataset(id="ds-test", name="hold-out", source_ko_id="bench-holdout"))
    _fitted_parameter(s, "p-magnetic", "ds-train", "ds-test")
    _conclusion(s, C_DEPENDS_ON_P)
    _assert_calibration_caught(_warrant(s))


def test_f1_control_independent_train_and_test_is_warranted():
    """Positive control: honest fit on bench data with disjoint hold-out."""
    s = _f1_storage([Dataset(id="ds-train", name="train", source_ko_id="bench-train")])
    result = _warrant(s)
    assert result.warrant_status == WarrantStatus.WARRANTED
    assert not result.anti_pattern_diagnoses


# ── F2: missing hold-out is not "calibrated to conclusion" ───────────────

def test_f2_missing_holdout_on_independent_data_is_not_labelled_calibrated_to_conclusion():
    """Fit on independent lab data with no test split. Blocking is right;
    the label is wrong — the training target is unrelated to the conclusion.
    Needs its own pattern (a spec decision: the site says *six* anti-patterns)."""
    s = InMemoryStorage()
    _observation(s, "bench-train", "bench series A")
    s.create_dataset(Dataset(id="ds-train", name="train", source_ko_id="bench-train"))
    _fitted_parameter(s, "p-magnetic", "ds-train", "")
    _conclusion(s, C_DEPENDS_ON_P)
    result = _warrant(s)

    assert result.warrant_status != WarrantStatus.WARRANTED          # passes today
    assert any("p-magnetic" in d.offending_ko_ids
               for d in result.anti_pattern_diagnoses)               # passes today
    assert AntiPattern.CALIBRATED_TO_CONCLUSION not in _patterns(result)  # fails today


# ── F3: provenance root identity is a raw string ─────────────────────────

@pytest.mark.parametrize("variant", [
    "LAB A REPORT 2026-03",        # case
    "  Lab A report 2026-03  ",    # surrounding whitespace
    "Lab A  report   2026-03",     # internal whitespace runs
])
def test_f3_trivial_spelling_variants_of_one_source_are_one_root(variant):
    s = InMemoryStorage()
    _observation(s, "m1", "Lab A report 2026-03", relations=SUPPORTS_C)
    _observation(s, "m2", variant, relations=SUPPORTS_C)
    _conclusion(s)
    result = _warrant(s)

    assert result.independence.independent_root_count == 1
    assert result.warrant_status != WarrantStatus.WARRANTED, (
        "two transcriptions of one report must not count as independent evidence")


def test_f3_control_two_distinct_sources_are_two_roots():
    s = InMemoryStorage()
    _observation(s, "m1", "Lab A report 2026-03", relations=SUPPORTS_C)
    _observation(s, "m2", "Lab B report 2026-04", relations=SUPPORTS_C)
    _conclusion(s)
    result = _warrant(s)
    assert result.independence.independent_root_count == 2
    assert result.warrant_status == WarrantStatus.WARRANTED


# ── F4: evidence_ids are never resolved ──────────────────────────────────

def test_f4_dangling_evidence_id_does_not_ground_an_observation():
    s = InMemoryStorage()
    _observation(s, "m1", "Lab A report 2026-03", register_evidence=False,
                 relations=SUPPORTS_C)
    _conclusion(s)
    assert s.get_evidence("ev-m1") is None          # precondition: it really dangles
    result = _warrant(s)
    assert result.warrant_status != WarrantStatus.WARRANTED
    assert "m1" in result.dependent_kos


def test_f4_control_registered_evidence_grounds_the_observation():
    s = InMemoryStorage()
    _observation(s, "m1", "Lab A report 2026-03", relations=SUPPORTS_C)
    _conclusion(s)
    assert s.get_evidence("ev-m1") is not None
    result = _warrant(s)
    assert result.warrant_status == WarrantStatus.WARRANTED
    assert "m1" in result.independent_kos
