# FILE: cognitive-harness/test_adversarial_v05.py
"""Adversarial benchmark v0.5 — structural edition.

Same test scenarios as v0.4.1 but with explicit graph-structural primitives:
  DerivationRelation, Dataset, DomainMapping, typed relations.

KO content/text is identical between positive and negative controls
where possible — warrant must differ solely from graph structure.

Expected: zero vocabulary-driven false positives, correct structural detection.
"""
import sys, logging
sys.path.insert(0, ".")

from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus, ConfidenceLevel,
    RelationType, Provenance, FalsifiableValidator, Relation, WarrantStatus,
    DerivationType, DerivationRelation, Dataset, AntiPatternDiagnosis, AntiPattern,
)
from cognitive_harness.storage.inmemory import InMemoryStorage
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
log = logging.getLogger(__name__)


class BenchResult:
    def __init__(self):
        self.tp = 0
        self.tn = 0
        self.fp = 0
        self.fn = 0
        self.misses: list[str] = []
        self.errors: list[str] = []

    def record(self, name: str, expect_detect: bool, got_detect: bool, detail: str = ""):
        if expect_detect and got_detect:
            self.tp += 1
            log.info(f"  PASS [{name}] detected as expected")
        elif not expect_detect and not got_detect:
            self.tn += 1
            log.info(f"  PASS [{name}] not detected as expected")
        elif expect_detect and not got_detect:
            self.fn += 1
            msg = f"  FAIL [{name}] FALSE NEGATIVE: {detail}"
            self.misses.append(msg)
            log.warning(msg)
        else:
            self.fp += 1
            msg = f"  FAIL [{name}] FALSE POSITIVE: {detail}"
            self.errors.append(msg)
            log.error(msg)

    def summary(self) -> dict:
        tp, fp, fn = self.tp, self.fp, self.fn
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        return {"total": self.tp + self.tn + self.fp + self.fn,
                "tp": tp, "tn": self.tn, "fp": fp, "fn": fn,
                "precision": precision, "recall": recall}


# Content text deliberately identical across controls
SHARED_CONTENT = "Parameter value: 0.42. Derived from experimental data."


def mk_ko(ko_id, title, truth_cat,
          ep_status=EpistemicStatus.VALIDATED,
          conf=ConfidenceLevel.MEDIUM,
          independent=True, source="test", author="test",
          relations=None, evidence_ids=None,
          derivation=None, ko_type=KOType.MODEL_RESULT):
    return KnowledgeObject(
        id=ko_id, type=ko_type, title=title,
        content=SHARED_CONTENT,  # identical across all tests
        truth_category=truth_cat, epistemic_status=ep_status,
        confidence=conf, viewpoint_ids=["conceptual"],
        provenance=Provenance(source=source, author=author, independent=independent),
        relations=relations or [], evidence_ids=evidence_ids or [],
        derivation=derivation, anti_patterns=[],  # NO keyword anti_patterns
        scope="adversarial-bench",
    )


# ================================================================
# 1. CALIBRATED_TO_CONCLUSION
# ================================================================

def test_calibrated(storage, bench):
    log.info("\n== CALIBRATED_TO_CONCLUSION ==")
    analyzer = WarrantAnalyzer(storage)

    # POS: fitted parameter with NO test dataset
    ko = mk_ko("cal-pos", "Gain coefficient", TruthCategory.FITTED_PARAMETER,
        derivation=DerivationRelation(
            derivation_type=DerivationType.FITTED,
            training_dataset_id="ds-cal-train",
            test_dataset_id="",  # NO test dataset
        ))
    storage.create_ko(ko)
    storage.create_dataset(Dataset(id="ds-cal-train", name="training data",
                                    source_ko_id="obs-cal-source"))
    storage.create_ko(mk_ko("obs-cal-source", "Calibration source",
                             TruthCategory.PHYSICAL_OBSERVATION, source="lab-1"))
    diagnoses = analyzer.detect_all_anti_patterns()
    got = any(d.pattern == AntiPattern.CALIBRATED_TO_CONCLUSION
              and "cal-pos" in d.offending_ko_ids for d in diagnoses)
    bench.record("cal_POS", True, got, "Fitted with no test dataset")

    # SUBTLE: fitted and tested on SAME dataset (overlapping observations)
    ko_sub = mk_ko("cal-sub", "Damping ratio", TruthCategory.FITTED_PARAMETER,
        derivation=DerivationRelation(
            derivation_type=DerivationType.FITTED,
            training_dataset_id="ds-cal-train",  # SAME dataset
            test_dataset_id="ds-cal-train",       # SAME dataset
        ))
    storage.create_ko(ko_sub)
    diagnoses = analyzer.detect_all_anti_patterns()
    got = any(d.pattern == AntiPattern.CALIBRATED_TO_CONCLUSION
              and "cal-sub" in d.offending_ko_ids for d in diagnoses)
    bench.record("cal_SUBTLE", True, got, "Fitted and tested on identical dataset")

    # NEG: genuinely independent training and test datasets
    ko_neg = mk_ko("cal-neg", "Stiffness parameter", TruthCategory.FITTED_PARAMETER,
        derivation=DerivationRelation(
            derivation_type=DerivationType.FITTED,
            training_dataset_id="ds-neg-train",
            test_dataset_id="ds-neg-test",
        ))
    storage.create_ko(ko_neg)
    # Training from lab A, test from lab B — disjoint roots
    storage.create_ko(mk_ko("obs-neg-a", "Training source A",
                             TruthCategory.PHYSICAL_OBSERVATION, source="lab-a"))
    storage.create_ko(mk_ko("obs-neg-b", "Test source B",
                             TruthCategory.PHYSICAL_OBSERVATION, source="lab-b"))
    storage.create_dataset(Dataset(id="ds-neg-train", name="training",
                                    source_ko_id="obs-neg-a"))
    storage.create_dataset(Dataset(id="ds-neg-test", name="holdout",
                                    source_ko_id="obs-neg-b"))
    diagnoses = analyzer.detect_all_anti_patterns()
    got = any(d.pattern == AntiPattern.CALIBRATED_TO_CONCLUSION
              and "cal-neg" in d.offending_ko_ids for d in diagnoses)
    bench.record("cal_NEG", False, got,
        "Disjoint training/test datasets — should NOT flag")


# ================================================================
# 2. TAUTOLOGICAL_VALIDATION
# ================================================================

def test_tautology(storage, bench):
    log.info("\n== TAUTOLOGICAL_VALIDATION ==")
    analyzer = WarrantAnalyzer(storage)

    # POS: all validated quantities trace to single source
    ko_src = mk_ko("taut-src", "Model output", TruthCategory.MODEL_DERIVED)
    storage.create_ko(ko_src)
    ko_q1 = mk_ko("taut-q1", "Quantity A", TruthCategory.MODEL_DERIVED,
        derivation=DerivationRelation(derivation_type=DerivationType.MATHEMATICAL,
                                      upstream_ko_ids=["taut-src"]))
    storage.create_ko(ko_q1)
    ko_q2 = mk_ko("taut-q2", "Quantity B", TruthCategory.MODEL_DERIVED,
        derivation=DerivationRelation(derivation_type=DerivationType.MATHEMATICAL,
                                      upstream_ko_ids=["taut-src"]))
    storage.create_ko(ko_q2)
    ko_pos = mk_ko("taut-pos", "Validation check", TruthCategory.VALIDATION_RESULT,
        derivation=DerivationRelation(derivation_type=DerivationType.VALIDATED,
                                      upstream_ko_ids=["taut-q1", "taut-q2"]))
    storage.create_ko(ko_pos)
    diagnoses = analyzer.detect_all_anti_patterns()
    got = any(d.pattern == AntiPattern.TAUTOLOGICAL_VALIDATION
              and "taut-pos" in d.offending_ko_ids for d in diagnoses)
    bench.record("taut_POS", True, got,
        "All quantities derive from same source")

    # SUBTLE: two quantities share identical root sets
    ko_src2 = mk_ko("taut-src2", "Shared source", TruthCategory.PHYSICAL_OBSERVATION)
    storage.create_ko(ko_src2)
    ko_s1 = mk_ko("taut-s1", "Derived A", TruthCategory.MODEL_DERIVED,
        derivation=DerivationRelation(derivation_type=DerivationType.MATHEMATICAL,
                                      upstream_ko_ids=["taut-src2"]))
    storage.create_ko(ko_s1)
    ko_s2 = mk_ko("taut-s2", "Derived B", TruthCategory.MODEL_DERIVED,
        derivation=DerivationRelation(derivation_type=DerivationType.MATHEMATICAL,
                                      upstream_ko_ids=["taut-src2"]))
    storage.create_ko(ko_s2)
    ko_sub = mk_ko("taut-sub", "Residual check", TruthCategory.VALIDATION_RESULT,
        derivation=DerivationRelation(derivation_type=DerivationType.VALIDATED,
                                      upstream_ko_ids=["taut-s1", "taut-s2"]))
    storage.create_ko(ko_sub)
    diagnoses = analyzer.detect_all_anti_patterns()
    got = any(d.pattern == AntiPattern.TAUTOLOGICAL_VALIDATION
              and "taut-sub" in d.offending_ko_ids for d in diagnoses)
    bench.record("taut_SUBTLE", True, got,
        "Quantities share identical provenance roots")

    # NEG: quantities from different sources
    ko_na = mk_ko("taut-na", "Measured input", TruthCategory.PHYSICAL_OBSERVATION,
                   source="wattmeter")
    storage.create_ko(ko_na)
    ko_nb = mk_ko("taut-nb", "Measured output", TruthCategory.PHYSICAL_OBSERVATION,
                   source="dynamometer")
    storage.create_ko(ko_nb)
    ko_neg = mk_ko("taut-neg", "Power balance", TruthCategory.VALIDATION_RESULT,
        derivation=DerivationRelation(derivation_type=DerivationType.VALIDATED,
                                      upstream_ko_ids=["taut-na", "taut-nb"]))
    storage.create_ko(ko_neg)
    diagnoses = analyzer.detect_all_anti_patterns()
    got = any(d.pattern == AntiPattern.TAUTOLOGICAL_VALIDATION
              and "taut-neg" in d.offending_ko_ids for d in diagnoses)
    bench.record("taut_NEG", False, got,
        "Quantities from different measurement sources")


# ================================================================
# 3. INERT_PARAMETER (structural: not in causal path)
# ================================================================
# Note: inert parameter detection requires a causal graph. In v0.5,
# we test that the warrant analyzer does NOT flag a parameter
# simply for existing — it must be in the justification path to matter.
# Inert parameters not in the path are irrelevant to warrant.
# We test: a KO that is in the path but has no causal connection
# to the result. This is tested via the justification cycle test.

# ================================================================
# 4. PHYSICALLY_UNREALIZABLE (structural: constraint contradiction)
# ================================================================

def test_physical(storage, bench):
    log.info("\n== PHYSICALLY_UNREALIZABLE ==")
    analyzer = WarrantAnalyzer(storage)

    # POS: KO contradicts a conservation law
    ko_constraint = mk_ko("phys-law", "Energy conservation",
                           TruthCategory.CONSERVATION_LAW,
                           ko_type=KOType.CONSTRAINT, source="physics")
    storage.create_ko(ko_constraint)
    ko_pos = mk_ko("phys-pos", "Negative conductivity",
                    TruthCategory.MODEL_DERIVED,
                    relations=[Relation(to="phys-law", type=RelationType.CONTRADICTS)])
    storage.create_ko(ko_pos)
    diagnoses = analyzer.detect_all_anti_patterns()
    got = any(d.pattern == AntiPattern.PHYSICALLY_UNREALIZABLE
              and "phys-pos" in d.offending_ko_ids for d in diagnoses)
    bench.record("phys_POS", True, got,
        "KO explicitly contradicts conservation law")

    # NEG: no contradiction relation — unusual but valid
    ko_neg = mk_ko("phys-neg", "High density CO2",
                    TruthCategory.PHYSICAL_OBSERVATION, source="NIST")
    storage.create_ko(ko_neg)
    diagnoses = analyzer.detect_all_anti_patterns()
    got = any(d.pattern == AntiPattern.PHYSICALLY_UNREALIZABLE
              and "phys-neg" in d.offending_ko_ids for d in diagnoses)
    bench.record("phys_NEG", False, got,
        "No constraint contradiction — should NOT flag")


# ================================================================
# 5. UNSUPPORTED_TRANSFER (structural: no domain mapping)
# ================================================================

def test_transfer(storage, bench):
    log.info("\n== UNSUPPORTED_TRANSFER ==")
    analyzer = WarrantAnalyzer(storage)

    # POS: transferred without domain mapping
    ko_src = mk_ko("trans-src", "Compressor load data",
                    TruthCategory.SOURCED_MATERIAL_DATA, source="compressor")
    storage.create_ko(ko_src)
    ko_pos = mk_ko("trans-pos", "Windmill load", TruthCategory.SOURCED_MATERIAL_DATA,
        derivation=DerivationRelation(
            derivation_type=DerivationType.TRANSFERRED,
            domain_source_ko_id="trans-src",
            domain_mapping_ko_id="",  # NO mapping
        ))
    storage.create_ko(ko_pos)
    diagnoses = analyzer.detect_all_anti_patterns()
    got = any(d.pattern == AntiPattern.UNSUPPORTED_TRANSFER
              and "trans-pos" in d.offending_ko_ids for d in diagnoses)
    bench.record("trans_POS", True, got,
        "Transfer without domain mapping")

    # NEG: transferred WITH explicit domain mapping
    ko_mapping = mk_ko("trans-map", "Aero-to-marine similarity mapping",
                        TruthCategory.DOCUMENTED_DECISION,
                        ko_type=KOType.DOMAIN_MAPPING, source="similarity-theory",
                        derivation=DerivationRelation(
                            derivation_type=DerivationType.DECIDED,
                            upstream_ko_ids=["obs-reynolds", "obs-froude"]))
    storage.create_ko(ko_mapping)
    storage.create_ko(mk_ko("obs-reynolds", "Reynolds similarity verified",
                             TruthCategory.PHYSICAL_OBSERVATION, source="dimensional-analysis"))
    storage.create_ko(mk_ko("obs-froude", "Froude number matching",
                             TruthCategory.PHYSICAL_OBSERVATION, source="dimensional-analysis"))
    ko_neg = mk_ko("trans-neg", "Marine turbulence constants",
                    TruthCategory.SOURCED_MATERIAL_DATA,
                    derivation=DerivationRelation(
                        derivation_type=DerivationType.TRANSFERRED,
                        domain_source_ko_id="trans-src",
                        domain_mapping_ko_id="trans-map",
                    ))
    storage.create_ko(ko_neg)
    diagnoses = analyzer.detect_all_anti_patterns()
    got = any(d.pattern == AntiPattern.UNSUPPORTED_TRANSFER
              and "trans-neg" in d.offending_ko_ids for d in diagnoses)
    bench.record("trans_NEG", False, got,
        "Transfer with explicit domain mapping supported by upstream evidence")


# ================================================================
# 6. CIRCULAR_DEPENDENCY (graph-structural)
# ================================================================

def test_circular(storage, bench):
    log.info("\n== CIRCULAR_DEPENDENCY ==")
    analyzer = WarrantAnalyzer(storage)

    # POS: self-referential evidence
    ko = mk_ko("circ-a", "Calculated efficiency", TruthCategory.MODEL_DERIVED,
        evidence_ids=["ev-circ-1"])
    storage.create_ko(ko)
    storage.add_evidence("ev-circ-1", "circ-a", "verified", "confirmed", [])
    diagnoses = analyzer.detect_all_anti_patterns()
    got = any(d.pattern == AntiPattern.CIRCULAR_DEPENDENCY
              and "circ-a" in d.offending_ko_ids for d in diagnoses)
    bench.record("circ_POS", True, got, "Self-referential evidence")

    # NEG: independent evidence chain
    ko_b = mk_ko("circ-b", "Measured efficiency", TruthCategory.PHYSICAL_OBSERVATION,
                 evidence_ids=["ev-circ-2"])
    storage.create_ko(ko_b)
    ko_c = mk_ko("circ-c", "Calorimetric data", TruthCategory.PHYSICAL_OBSERVATION)
    storage.create_ko(ko_c)
    storage.add_evidence("ev-circ-2", "circ-c", "verified", "data", [])
    diagnoses = analyzer.detect_all_anti_patterns()
    got = any(d.pattern == AntiPattern.CIRCULAR_DEPENDENCY
              and "circ-b" in d.offending_ko_ids for d in diagnoses)
    bench.record("circ_NEG", False, got, "Independent evidence chain")


# ================================================================
# STRUCTURAL EDGE CASES
# ================================================================

def test_justification_cycle(storage, bench):
    log.info("\n== JUSTIFICATION CYCLE ==")
    # A depends on B depends on C depends on A
    ko_a = mk_ko("cycle-a", "Torque T", TruthCategory.MODEL_DERIVED,
        relations=[Relation(to="cycle-b", type=RelationType.DEPENDS_ON)])
    ko_b = mk_ko("cycle-b", "Power P", TruthCategory.MODEL_DERIVED,
        relations=[Relation(to="cycle-c", type=RelationType.DEPENDS_ON)])
    ko_c = mk_ko("cycle-c", "Speed omega", TruthCategory.MODEL_DERIVED,
        relations=[Relation(to="cycle-a", type=RelationType.DEPENDS_ON)])
    for ko in [ko_a, ko_b, ko_c]:
        storage.create_ko(ko)

    analyzer = WarrantAnalyzer(storage)
    result = analyzer.compute_warrant("cycle-a")
    bench.record("just_cycle", True,
        result.warrant_status == WarrantStatus.UNWARRANTED,
        f"Cycle should be unwarranted; got {result.warrant_status.value}. Cycles: {result.cycles}")


def test_same_source(storage, bench):
    log.info("\n== SAME SOURCE ==")
    ko_src = mk_ko("same-src", "Master dataset", TruthCategory.PHYSICAL_OBSERVATION)
    storage.create_ko(ko_src)
    ko_e1 = mk_ko("same-e1", "Peak temp", TruthCategory.MODEL_DERIVED,
        derivation=DerivationRelation(derivation_type=DerivationType.MATHEMATICAL,
                                      upstream_ko_ids=["same-src"]))
    storage.create_ko(ko_e1)
    ko_e2 = mk_ko("same-e2", "Enthalpy", TruthCategory.MODEL_DERIVED,
        derivation=DerivationRelation(derivation_type=DerivationType.MATHEMATICAL,
                                      upstream_ko_ids=["same-src"]))
    storage.create_ko(ko_e2)
    ko_conc = mk_ko("same-conc", "PCM validated", TruthCategory.MODEL_DERIVED,
        relations=[
            Relation(to="same-e1", type=RelationType.SUPPORTS),
            Relation(to="same-e2", type=RelationType.SUPPORTS)])
    storage.create_ko(ko_conc)

    analyzer = WarrantAnalyzer(storage)
    result = analyzer.compute_warrant("same-conc")
    indep = result.independence
    if indep:
        log.info(f"  Evidence count: {indep.evidence_count}, "
                 f"Independent roots: {indep.independent_root_count}")
    is_weakened = result.warrant_status in (WarrantStatus.UNWARRANTED,
                                             WarrantStatus.CONDITIONALLY_WARRANTED)
    bench.record("same_source", True, is_weakened,
        f"Same source should weaken warrant; got {result.warrant_status.value}")


def test_shared_upstream(storage, bench):
    log.info("\n== SHARED UPSTREAM ==")
    ko_up = mk_ko("shared-up", "NIST reference", TruthCategory.PHYSICAL_OBSERVATION,
                   source="NIST")
    storage.create_ko(ko_up)
    ko_sa = mk_ko("shared-a", "Sensor A", TruthCategory.PHYSICAL_OBSERVATION,
        derivation=DerivationRelation(derivation_type=DerivationType.MEASURED,
                                      upstream_ko_ids=["shared-up"]))
    storage.create_ko(ko_sa)
    ko_sb = mk_ko("shared-b", "Sensor B", TruthCategory.PHYSICAL_OBSERVATION,
        derivation=DerivationRelation(derivation_type=DerivationType.MEASURED,
                                      upstream_ko_ids=["shared-up"]))
    storage.create_ko(ko_sb)
    ko_conc = mk_ko("shared-conc", "Temperature confirmed", TruthCategory.MODEL_DERIVED,
        relations=[
            Relation(to="shared-a", type=RelationType.SUPPORTS),
            Relation(to="shared-b", type=RelationType.SUPPORTS)])
    storage.create_ko(ko_conc)

    analyzer = WarrantAnalyzer(storage)
    result = analyzer.compute_warrant("shared-conc")
    is_weakened = result.warrant_status in (WarrantStatus.UNWARRANTED,
                                             WarrantStatus.CONDITIONALLY_WARRANTED)
    bench.record("shared_upstream", True, is_weakened,
        f"Shared upstream should weaken; got {result.warrant_status.value}")


def test_canonical_dependent(storage, bench):
    log.info("\n== CANONICAL DEPENDENT ==")
    ko = mk_ko("canon-dep", "Authoritative efficiency",
               TruthCategory.PHYSICAL_OBSERVATION,
               ep_status=EpistemicStatus.CANONICAL, conf=ConfidenceLevel.HIGH,
               independent=True, source="test-lab")
    storage.create_ko(ko)
    stored = storage.get_ko("canon-dep")
    if stored and stored.provenance:
        stored.provenance.independent = False

    analyzer = WarrantAnalyzer(storage)
    result = analyzer.compute_warrant("canon-dep")
    bench.record("canon_dependent", True,
        result.warrant_status == WarrantStatus.UNWARRANTED,
        f"Canonical + dependent provenance should be unwarranted; got {result.warrant_status.value}")


def test_multiple_weak_independent(storage, bench):
    log.info("\n== MULTIPLE WEAK INDEPENDENT ==")
    for i, src in enumerate(["lab-a", "lab-b", "lab-c"]):
        ko = mk_ko(f"weak-{i}", f"Lab measurement {i}",
                    TruthCategory.PHYSICAL_OBSERVATION, conf=ConfidenceLevel.LOW,
                    independent=True, source=src, evidence_ids=[f"ev-weak-{i}"])
        storage.add_evidence(f"ev-weak-{i}", f"weak-{i}", "verified", "data", [])
        storage.create_ko(ko)
    ko_conc = mk_ko("weak-conc", "Efficiency consensus", TruthCategory.MODEL_DERIVED,
        relations=[Relation(to=f"weak-{i}", type=RelationType.SUPPORTS) for i in range(3)])
    storage.create_ko(ko_conc)

    analyzer = WarrantAnalyzer(storage)
    result = analyzer.compute_warrant("weak-conc")
    # Multiple genuinely independent observations should be WARRANTED
    bench.record("multi_weak_indep", True,
        result.warrant_status == WarrantStatus.WARRANTED,
        f"Multiple weak independent should be warranted; got {result.warrant_status.value}")


def test_high_conf_no_warrant(storage, bench):
    log.info("\n== HIGH CONF NO WARRANT ==")
    ko = mk_ko("high-no-w", "Predicted performance",
               TruthCategory.MODEL_DERIVED, conf=ConfidenceLevel.CERTAIN,
               independent=False, source="simulation-team")
    storage.create_ko(ko)

    analyzer = WarrantAnalyzer(storage)
    result = analyzer.compute_warrant("high-no-w")
    bench.record("high_conf_no_warrant", True,
        result.warrant_status == WarrantStatus.UNWARRANTED,
        f"High confidence + dependent provenance should be unwarranted; got {result.warrant_status.value}")


def test_low_conf_sound_provenance(storage, bench):
    log.info("\n== LOW CONF SOUND PROVENANCE ==")
    ko = mk_ko("low-sound", "Preliminary efficiency",
               TruthCategory.PHYSICAL_OBSERVATION, conf=ConfidenceLevel.LOW,
               independent=True, source="field-test",
               evidence_ids=["ev-low-1"])
    storage.add_evidence("ev-low-1", "low-sound", "verified", "calibrated instruments", [])
    storage.create_ko(ko)

    analyzer = WarrantAnalyzer(storage)
    result = analyzer.compute_warrant("low-sound")
    # Low confidence but sound independent provenance should be WARRANTED
    bench.record("low_conf_sound", True,
        result.warrant_status == WarrantStatus.WARRANTED,
        f"Low confidence + sound provenance should be warranted; got {result.warrant_status.value}")


# ================================================================
# PROVENANCE-COUNTERFACTUAL TESTS
# Text content identical, only graph structure differs
# ================================================================

def test_counterfactual_shared_vs_independent(storage, bench):
    """Graph A: three tests share one upstream simulation.
       Graph B: three tests derive from independent measurements.
       Content text is identical. Warrant must differ."""
    log.info("\n== COUNTERFACTUAL: shared vs independent ==")

    # Graph A: shared upstream
    ko_sim = mk_ko("cf-sim", "Simulation result",
                    TruthCategory.MODEL_DERIVED, source="simulation")
    storage.create_ko(ko_sim)
    for i in range(3):
        ko = mk_ko(f"cf-a-{i}", "Test result",
                    TruthCategory.MODEL_DERIVED, source="simulation",
                    derivation=DerivationRelation(
                        derivation_type=DerivationType.MODELED,
                        upstream_ko_ids=["cf-sim"]))
        storage.create_ko(ko)
    ko_conc_a = mk_ko("cf-conc-a", "Consensus from tests",
                       TruthCategory.MODEL_DERIVED,
                       relations=[Relation(to=f"cf-a-{i}", type=RelationType.SUPPORTS)
                                  for i in range(3)])
    storage.create_ko(ko_conc_a)

    # Graph B: independent sources
    for i, src in enumerate(["lab-1", "lab-2", "lab-3"]):
        ko = mk_ko(f"cf-b-{i}", "Test result",
                    TruthCategory.PHYSICAL_OBSERVATION, source=src,
                    evidence_ids=[f"ev-cf-b-{i}"])
        storage.add_evidence(f"ev-cf-b-{i}", f"cf-b-{i}", "verified", "data", [])
        storage.create_ko(ko)
    ko_conc_b = mk_ko("cf-conc-b", "Consensus from tests",
                       TruthCategory.MODEL_DERIVED,
                       relations=[Relation(to=f"cf-b-{i}", type=RelationType.SUPPORTS)
                                  for i in range(3)])
    storage.create_ko(ko_conc_b)

    analyzer = WarrantAnalyzer(storage)
    result_a = analyzer.compute_warrant("cf-conc-a")
    result_b = analyzer.compute_warrant("cf-conc-b")

    # Graph A should be weaker than Graph B (shared upstream)
    # Both have identical content text
    log.info(f"  Graph A (shared): {result_a.warrant_status.value}")
    log.info(f"  Graph B (independent): {result_b.warrant_status.value}")

    # Graph A should NOT be WARRANTED (shared upstream simulation)
    # Graph B SHOULD be WARRANTED (independent measurements)
    a_not_warranted = result_a.warrant_status != WarrantStatus.WARRANTED
    b_is_warranted = result_b.warrant_status == WarrantStatus.WARRANTED

    bench.record("counterfactual_differs", True,
        a_not_warranted and b_is_warranted,
        f"Graph A={result_a.warrant_status.value}, Graph B={result_b.warrant_status.value}. "
        f"Same text, different graph structure should yield different warrant.")


# ================================================================
# MAIN
# ================================================================

def run_adversarial():
    log.info("=" * 72)
    log.info("ADVERSARIAL BENCHMARK v0.5 — Structural Epistemic Warrant")
    log.info("KO content text is identical across tests.")
    log.info("Classification must come from graph structure only.")
    log.info("=" * 72)

    storage = InMemoryStorage()
    bench = BenchResult()

    test_calibrated(storage, bench)
    test_tautology(storage, bench)
    test_physical(storage, bench)
    test_transfer(storage, bench)
    test_circular(storage, bench)
    test_justification_cycle(storage, bench)
    test_same_source(storage, bench)
    test_shared_upstream(storage, bench)
    test_canonical_dependent(storage, bench)
    test_multiple_weak_independent(storage, bench)
    test_high_conf_no_warrant(storage, bench)
    test_low_conf_sound_provenance(storage, bench)
    test_counterfactual_shared_vs_independent(storage, bench)

    s = bench.summary()
    log.info("\n" + "=" * 72)
    log.info("RESULTS:")
    log.info(f"  Total: {s['total']}  TP: {s['tp']}  TN: {s['tn']}  FP: {s['fp']}  FN: {s['fn']}")
    log.info(f"  Precision: {s['precision']:.2%}  Recall: {s['recall']:.2%}")

    if bench.errors:
        log.error("\nFALSE POSITIVES (architecture issues):")
        for e in bench.errors:
            log.error(f"  {e}")
    if bench.misses:
        log.warning("\nFALSE NEGATIVES:")
        for m in bench.misses:
            log.warning(f"  {m}")

    if s['fp'] == 0:
        log.info("\nVERDICT: No vocabulary-driven false positives.")
        log.info("Detectors operate on graph structure.")
    else:
        log.error("\nVERDICT: Vocabulary-driven false positives detected.")

    log.info("=" * 72)


if __name__ == "__main__":
    run_adversarial()
