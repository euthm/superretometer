"""Minimal example — create a warranted conclusion.

Demonstrates the full stack:
  1. Create independent evidence
  2. Create a conclusion supported by evidence
  3. Compute warrant → WARRANTED
"""
from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus,
    ConfidenceLevel, RelationType, Provenance, Relation,
)
from cognitive_harness.storage.inmemory import InMemoryStorage
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer

storage = InMemoryStorage()

# ── Independent evidence ──
ev = KnowledgeObject(
    id="ev-steel-strength",
    type=KOType.OBSERVATION,
    title="Lamination steel yield stress: 450 MPa",
    content="Measured from manufacturer datasheet, independent source.",
    truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
    epistemic_status=EpistemicStatus.CANONICAL,
    confidence=ConfidenceLevel.HIGH,
    provenance=Provenance(
        source="manufacturer-datasheet",
        author="materials-lab",
        independent=True,
    ),
    # Evidence SUPPORTS the conclusion
    relations=[Relation(to="conc-safe-stress", type=RelationType.SUPPORTS)],
)
storage.create_ko(ev)

# ── Conclusion ──
conc = KnowledgeObject(
    id="conc-safe-stress",
    type=KOType.CONCLUSION,
    title="Core stress is within material limits",
    content="Maximum calculated stress (320 MPa) is below yield (450 MPa).",
    truth_category=TruthCategory.MODEL_DERIVED,
    epistemic_status=EpistemicStatus.PROPOSED,
    confidence=ConfidenceLevel.MEDIUM,
    provenance=Provenance(source="calculation", author="design-team"),
)
storage.create_ko(conc)

# ── Graph edge: evidence SUPPORTS conclusion ──
storage.create_relation("ev-steel-strength", "conc-safe-stress", RelationType.SUPPORTS)

# ── Warrant analysis ──
wa = WarrantAnalyzer(storage)
result = wa.compute_warrant("conc-safe-stress")

print(f"Warrant: {result.warrant_status.value}")
print(f"Supporting KOs: {len(result.supporting_kos)}")
print(f"Independent KOs: {len(result.independent_kos)}")
print(f"Dependent KOs: {len(result.dependent_kos)}")
print(f"Anti-patterns: {len(result.anti_pattern_diagnoses)}")

if result.warrant_status.value == "warranted":
    print("\n✓ Conclusion is structurally warranted by independent evidence.")
else:
    print(f"\n✗ Conclusion is {result.warrant_status.value}.")
    for d in result.anti_pattern_diagnoses:
        print(f"  Anti-pattern: {d.pattern.value}")
