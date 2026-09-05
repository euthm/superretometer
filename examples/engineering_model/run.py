"""Engineering model example — structural warrant analysis.

A plausible engineering conclusion with three structural defects.

Demonstrates:
  1. Engineering claim that appears well-supported
  2. Apparently reasonable model results
  3. Provenance analysis reveals three structural defects
  4. UNWARRANTED conclusion
  5. Evidence gaps → path to CONDITIONALLY_WARRANTED / WARRANTED
"""
from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, TruthCategory, EpistemicStatus,
    ConfidenceLevel, RelationType, Provenance, Relation,
    DerivationType, DerivationRelation, FalsifiableValidator,
)
from cognitive_harness.storage.inmemory import InMemoryStorage
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer

storage = InMemoryStorage()

# ── Independent material data (CANONICAL) ──
steel = KnowledgeObject(
    id="steel-datasheet",
    type=KOType.OBSERVATION,
    title="Lamination steel material properties",
    content="Manufacturer datasheet: conductivity, density, yield stress.",
    truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
    epistemic_status=EpistemicStatus.CANONICAL,
    confidence=ConfidenceLevel.HIGH,
    provenance=Provenance(source="manufacturer", author="materials-dept", independent=True),
    scope="sanitized-example",
)
storage.create_ko(steel)

bertotti = KnowledgeObject(
    id="bertotti-fit",
    type=KOType.OBSERVATION,
    title="Iron loss coefficients: fit to 133 data points",
    content="Coefficients fitted to measurement data with high goodness-of-fit.",
    truth_category=TruthCategory.FITTED_PARAMETER,
    epistemic_status=EpistemicStatus.CANONICAL,
    confidence=ConfidenceLevel.HIGH,
    provenance=Provenance(source="manufacturer", author="materials-dept", independent=True),
    validators=[
        FalsifiableValidator(
            description="Fit quality check",
            what_would_falsify="New measurement data showing R² < 0.95 or systematic residual pattern",
            passes=True,
            observation="R² = 0.997, residuals randomly distributed",
        )
    ],
    scope="sanitized-example",
)
storage.create_ko(bertotti)

conservation = KnowledgeObject(
    id="conservation-law",
    type=KOType.CONSTRAINT,
    title="Physical conservation laws: energy, momentum",
    content="Newton's 2nd law and energy balance. Numerical error < 10⁻¹³.",
    truth_category=TruthCategory.CONSERVATION_LAW,
    epistemic_status=EpistemicStatus.CANONICAL,
    confidence=ConfidenceLevel.CERTAIN,
    provenance=Provenance(source="physics", author="physics", independent=True),
    scope="sanitized-example",
)
storage.create_ko(conservation)

# ── Anti-pattern 1: CALIBRATED_TO_CONCLUSION ──
# A magnetic parameter fitted to produce a desired field value
apole = KnowledgeObject(
    id="apole-calibrated",
    type=KOType.OBSERVATION,
    title="Pole area: calibrated to produce target field",
    content="Pole area parameter set to produce target magnetic flux density at operating point. "
            "Does not predict anything — calibrated to the desired conclusion.",
    truth_category=TruthCategory.FITTED_PARAMETER,
    epistemic_status=EpistemicStatus.VALIDATED,
    confidence=ConfidenceLevel.HIGH,
    provenance=Provenance(source="calibration", author="simulation", independent=False),
    derivation=DerivationRelation(
        derivation_type=DerivationType.FITTED,
        training_dataset_id="ds-apole-self",  # Self-referential
        test_dataset_id="",  # No independent test
    ),
    scope="sanitized-example",
)
storage.create_ko(apole)
storage.create_dataset(
    __import__("cognitive_harness.model.ko").model.ko.Dataset(
        id="ds-apole-self", name="A_pole training", source_ko_id="apole-calibrated"
    )
)

# ── Anti-pattern 2: TAUTOLOGICAL_VALIDATION ──
# All quantities derive from single model source
model = KnowledgeObject(
    id="machine-model",
    type=KOType.MODEL_RESULT,
    title="Machine model (single source)",
    content="The simulation model — all computed quantities derive from it.",
    truth_category=TruthCategory.MODEL_DERIVED,
    epistemic_status=EpistemicStatus.VALIDATED,
    confidence=ConfidenceLevel.HIGH,
    provenance=Provenance(source="simulation", author="simulation", independent=False),
    scope="sanitized-example",
)
storage.create_ko(model)

p_mech = KnowledgeObject(
    id="p-mech",
    type=KOType.MODEL_RESULT,
    title="Mechanical power (model computed)",
    content="Mechanical power from model equations.",
    truth_category=TruthCategory.MODEL_DERIVED,
    epistemic_status=EpistemicStatus.VALIDATED,
    confidence=ConfidenceLevel.HIGH,
    provenance=Provenance(source="simulation", author="simulation", independent=False),
    derivation=DerivationRelation(
        derivation_type=DerivationType.MATHEMATICAL,
        upstream_ko_ids=["machine-model"],
    ),
    scope="sanitized-example",
)
storage.create_ko(p_mech)

p_loss = KnowledgeObject(
    id="p-loss",
    type=KOType.MODEL_RESULT,
    title="Total loss (model computed)",
    content="Total loss from model equations.",
    truth_category=TruthCategory.MODEL_DERIVED,
    epistemic_status=EpistemicStatus.VALIDATED,
    confidence=ConfidenceLevel.HIGH,
    provenance=Provenance(source="simulation", author="simulation", independent=False),
    derivation=DerivationRelation(
        derivation_type=DerivationType.MATHEMATICAL,
        upstream_ko_ids=["machine-model"],
    ),
    scope="sanitized-example",
)
storage.create_ko(p_loss)

energy_check = KnowledgeObject(
    id="energy-check-tautology",
    type=KOType.OBSERVATION,
    title="Power balance check (tautology)",
    content="P_input_check = P_mech + P_total_loss. Always holds by construction. "
            "All three quantities derive from the same model.",
    truth_category=TruthCategory.VALIDATION_RESULT,
    epistemic_status=EpistemicStatus.VALIDATED,
    confidence=ConfidenceLevel.CERTAIN,
    provenance=Provenance(source="model-identity", author="simulation", independent=False),
    derivation=DerivationRelation(
        derivation_type=DerivationType.VALIDATED,
        upstream_ko_ids=["p-mech", "p-loss"],
    ),
    scope="sanitized-example",
)
storage.create_ko(energy_check)

# ── Anti-pattern 3: UNSUPPORTED_TRANSFER ──
# Load profile from compressor domain, applied to different application
compressor = KnowledgeObject(
    id="compressor-load",
    type=KOType.OBSERVATION,
    title="Compressor load profile (source domain)",
    content="Operational load characteristic from compressor application.",
    truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
    epistemic_status=EpistemicStatus.VALIDATED,
    confidence=ConfidenceLevel.MEDIUM,
    provenance=Provenance(source="compressor-ops", author="operations", independent=True),
    scope="sanitized-example",
)
storage.create_ko(compressor)

transferred_load = KnowledgeObject(
    id="transferred-load",
    type=KOType.OBSERVATION,
    title="Load profile (transferred from compressor to turbine)",
    content="Load profile borrowed from compressor domain and applied to turbine application. "
            "No evidence that the two load profiles are equivalent.",
    truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
    epistemic_status=EpistemicStatus.VALIDATED,
    confidence=ConfidenceLevel.LOW,
    provenance=Provenance(source="operational-doc", author="operations", independent=True),
    derivation=DerivationRelation(
        derivation_type=DerivationType.TRANSFERRED,
        domain_source_ko_id="compressor-load",
        domain_mapping_ko_id="",  # No domain mapping
    ),
    scope="sanitized-example",
)
storage.create_ko(transferred_load)

# ── Other premises ──
# Assumption: stress parameter unresolved
sigma = KnowledgeObject(
    id="sigma-assumption",
    type=KOType.CONSTRAINT,
    title="Stress parameter (unresolved)",
    content="Stress parameter value unresolved between two contract specifications.",
    truth_category=TruthCategory.ASSUMPTION,
    epistemic_status=EpistemicStatus.TENTATIVE,
    confidence=ConfidenceLevel.LOW,
    provenance=Provenance(source="contract", author="contract", independent=True),
    scope="sanitized-example",
)
storage.create_ko(sigma)

# Assumption: generator efficiency not modeled
gen_eff = KnowledgeObject(
    id="gen-eff-assumption",
    type=KOType.HYPOTHESIS,
    title="Generator efficiency (not modeled)",
    content="Generator efficiency not modeled. All values assume motor mode.",
    truth_category=TruthCategory.ASSUMPTION,
    epistemic_status=EpistemicStatus.PROPOSED,
    confidence=ConfidenceLevel.SPECULATIVE,
    provenance=Provenance(source="simulation", author="simulation", independent=True),
    scope="sanitized-example",
)
storage.create_ko(gen_eff)

# CAD data (sourced but not independently verified)
cad = KnowledgeObject(
    id="cad-geometry",
    type=KOType.MODEL_RESULT,
    title="Winding geometry (CAD)",
    content="Geometry from CAD model. Sourced from design engineer.",
    truth_category=TruthCategory.SOURCED_MATERIAL_DATA,
    epistemic_status=EpistemicStatus.VALIDATED,
    confidence=ConfidenceLevel.MEDIUM,
    provenance=Provenance(source="cad-model", author="design-eng", independent=False),
    scope="sanitized-example",
)
storage.create_ko(cad)

# Core volume (assumed geometry)
core_vol = KnowledgeObject(
    id="core-volume",
    type=KOType.MODEL_RESULT,
    title="Core volume (assumed geometry)",
    content="Core volume derived from assumed geometry, not measured.",
    truth_category=TruthCategory.MODEL_DERIVED,
    epistemic_status=EpistemicStatus.VALIDATED,
    confidence=ConfidenceLevel.LOW,
    provenance=Provenance(source="assumed-geometry", author="design-eng", independent=False),
    scope="sanitized-example",
)
storage.create_ko(core_vol)

# ── THE CONCLUSION ──
conclusion = KnowledgeObject(
    id="performance-conclusion",
    type=KOType.CONCLUSION,
    title="Machine meets performance target at design speed",
    content="Design conclusion: machine reaches target speed at rated power. "
            "Based on simulation with three-state voltage profile.",
    truth_category=TruthCategory.MODEL_DERIVED,
    epistemic_status=EpistemicStatus.VALIDATED,
    confidence=ConfidenceLevel.MEDIUM,
    provenance=Provenance(source="simulation", author="simulation", independent=False),
    scope="sanitized-example",
    relations=[
        Relation(to="cad-geometry", type=RelationType.DEPENDS_ON),
        Relation(to="core-volume", type=RelationType.DEPENDS_ON),
        Relation(to="sigma-assumption", type=RelationType.DEPENDS_ON),
        Relation(to="transferred-load", type=RelationType.DEPENDS_ON),
        Relation(to="gen-eff-assumption", type=RelationType.DEPENDS_ON),
        Relation(to="apole-calibrated", type=RelationType.DEPENDS_ON),
        Relation(to="energy-check-tautology", type=RelationType.DEPENDS_ON),
        Relation(to="steel-datasheet", type=RelationType.DEPENDS_ON),
        Relation(to="bertotti-fit", type=RelationType.DEPENDS_ON),
        Relation(to="conservation-law", type=RelationType.DEPENDS_ON),
    ],
)
storage.create_ko(conclusion)

# ── Warrant analysis ──
print("=" * 60)
print("ENGINEERING MODEL — Warrant Analysis")
print("=" * 60)

wa = WarrantAnalyzer(storage)

# Anti-pattern scan
findings = wa.detect_all_anti_patterns()
print(f"\nAnti-patterns detected: {len(findings)}")
for f in findings:
    ko = storage.get_ko(f.offending_ko_ids[0]) if f.offending_ko_ids else None
    title = ko.title if ko else f.offending_ko_ids[0]
    print(f"  [{f.pattern.value}] {title[:60]}")

# Warrant computation
result = wa.compute_warrant("performance-conclusion")
print(f"\nWarrant status: {result.warrant_status.value}")
print(f"Supporting KOs: {len(result.supporting_kos)}")
print(f"Independent KOs: {len(result.independent_kos)}")
print(f"Dependent KOs: {len(result.dependent_kos)}")

# Evidence gaps
print("\n── Evidence gaps (minimum to warrant) ──")
print("1. CALIBRATED_TO_CONCLUSION (apole-calibrated):")
print("   → Independent geometric measurement of pole area")
print("   → Holdout test dataset (B-field on points not used for fitting)")
print()
print("2. TAUTOLOGICAL_VALIDATION (energy-check-tautology):")
print("   → Replace with P_input = Σ(V_phase × i_phase) from electrical measurement")
print("   → External power measurement independent of simulation")
print()
print("3. UNSUPPORTED_TRANSFER (transferred-load):")
print("   → Turbine load measurement at operating conditions")
print("   → OR: validated domain mapping proving compressor↔turbine equivalence")
print()
if result.warrant_status.value == "unwarranted":
    print("✓ Conclusion correctly UNWARRANTED — structural defects detected.")
else:
    print(f"✗ Expected UNWARRANTED, got {result.warrant_status.value}")
