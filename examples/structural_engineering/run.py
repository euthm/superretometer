"""Structural engineering example — bridge cable safety.

Demonstrates warrant analysis over a structural engineering claim.
Independent material tests vs. model-derived quantities.
"""
from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus,
    ConfidenceLevel, RelationType, Provenance, Relation,
)
from cognitive_harness.storage.inmemory import InMemoryStorage
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer

storage = InMemoryStorage()

# Independent evidence: material test
mat_test = KnowledgeObject(
    id="cable-tensile-test",
    type=KOType.OBSERVATION,
    title="Cable tensile strength test: 1770 MPa",
    content="Tensile strength measured on sample cable per ASTM A416.",
    truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
    epistemic_status=EpistemicStatus.CANONICAL,
    confidence=ConfidenceLevel.HIGH,
    provenance=Provenance(source="independent-lab", author="materials-lab", independent=True),
)
storage.create_ko(mat_test)

# Independent evidence: load measurement
load_meas = KnowledgeObject(
    id="bridge-load-meas",
    type=KOType.OBSERVATION,
    title="Maximum bridge load measurement: 850 kN",
    content="Instrumented measurement during peak traffic conditions.",
    truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
    epistemic_status=EpistemicStatus.VALIDATED,
    confidence=ConfidenceLevel.MEDIUM,
    provenance=Provenance(source="traffic-instrumentation", author="civil-eng", independent=True),
)
storage.create_ko(load_meas)

# Conservation: equilibrium
equilibrium = KnowledgeObject(
    id="static-equilibrium",
    type=KOType.CONSTRAINT,
    title="Static equilibrium: sum of forces = 0",
    content="Fundamental constraint of structural analysis.",
    truth_category=TruthCategory.CONSERVATION_LAW,
    epistemic_status=EpistemicStatus.CANONICAL,
    confidence=ConfidenceLevel.CERTAIN,
    provenance=Provenance(source="physics", author="physics", independent=True),
)
storage.create_ko(equilibrium)

# Model-derived (dependent on single model)
cable_stress = KnowledgeObject(
    id="cable-stress-model",
    type=KOType.MODEL_RESULT,
    title="Cable stress (model computed)",
    content="Maximum cable stress computed from FEA model.",
    truth_category=TruthCategory.MODEL_DERIVED,
    epistemic_status=EpistemicStatus.VALIDATED,
    confidence=ConfidenceLevel.MEDIUM,
    provenance=Provenance(source="fea-model", author="fea-eng", independent=False),
)
storage.create_ko(cable_stress)

# Conclusion
conclusion = KnowledgeObject(
    id="safe-for-design-life",
    type=KOType.CONCLUSION,
    title="Cable system safe for 100-year design life",
    content="Computed stress is below fatigue limit with factor of safety > 2.0.",
    truth_category=TruthCategory.MODEL_DERIVED,
    epistemic_status=EpistemicStatus.PROPOSED,
    confidence=ConfidenceLevel.MEDIUM,
    provenance=Provenance(source="structural-analysis", author="civil-eng"),
    relations=[
        Relation(to="cable-tensile-test", type=RelationType.DEPENDS_ON),
        Relation(to="bridge-load-meas", type=RelationType.DEPENDS_ON),
        Relation(to="static-equilibrium", type=RelationType.DEPENDS_ON),
        Relation(to="cable-stress-model", type=RelationType.DEPENDS_ON),
    ],
)
storage.create_ko(conclusion)

# Graph edges
storage.create_relation("cable-tensile-test", "safe-for-design-life", RelationType.SUPPORTS)
storage.create_relation("bridge-load-meas", "safe-for-design-life", RelationType.SUPPORTS)

# Analyze
wa = WarrantAnalyzer(storage)
result = wa.compute_warrant("safe-for-design-life")

print("Bridge cable safety — warrant analysis")
print(f"  Warrant: {result.warrant_status.value}")
print(f"  Supporting: {len(result.supporting_kos)}")
print(f"  Independent: {len(result.independent_kos)}")
print(f"  Dependent: {len(result.dependent_kos)}")
