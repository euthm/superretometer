# FILE: cognitive-harness/model/ko.py
"""Knowledge Object model v0.5 — Structural Epistemic Warrant.

Three independent dimensions:
  1. KOType     — what the KO is (requirement, observation, decision, ...)
  2. TruthCategory — what KIND of truth claim it makes (physical observation,
                      conservation law, documented decision, fitted parameter, ...)
  3. EpistemicStatus — lifecycle state (proposed, validated, canonical, ...)

v0.5 changes:
  - DerivationType enum: explicit classification of HOW a KO was produced
  - Dataset: first-class observation population for independence analysis
  - DerivationRelation: typed derivation with dataset references
  - DomainMapping: explicit cross-domain transfer justification
  - Keyword-based anti-pattern detectors deprecated (v0.4 legacy only)

Warrant is computed by the WarrantAnalyzer over the justification graph.
No text content is used for epistemic classification.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ── 1. Content type: what the KO is ───────────────────────────────────────

class KOType(str, Enum):
    REQUIREMENT = "requirement"
    OBSERVATION = "observation"
    HYPOTHESIS = "hypothesis"
    DECISION = "decision"
    CONSTRAINT = "constraint"
    MODEL_RESULT = "model_result"
    SPECIFICATION = "specification"
    FINDING = "finding"
    EVIDENCE_ITEM = "evidence"
    CONCLUSION = "conclusion"
    DOMAIN_MAPPING = "domain_mapping"   # Explicit cross-domain equivalence argument


# ── 2. Truth category: what kind of truth claim ───────────────────────────

class TruthCategory(str, Enum):
    PHYSICAL_OBSERVATION = "physical_observation"
    SOURCED_MATERIAL_DATA = "sourced_material_data"
    CONSERVATION_LAW = "conservation_law"
    DOCUMENTED_DECISION = "documented_decision"
    ASSUMPTION = "assumption"
    FITTED_PARAMETER = "fitted_parameter"
    MODEL_DERIVED = "model_derived"
    VALIDATION_RESULT = "validation_result"
    MATHEMATICAL_IDENTITY = "mathematical_identity"


# ── 3. Epistemic status: lifecycle ────────────────────────────────────────

class EpistemicStatus(str, Enum):
    PROPOSED = "proposed"
    TENTATIVE = "tentative"
    VALIDATED = "validated"
    CANONICAL = "canonical"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"

    @property
    def is_terminal(self) -> bool:
        return self in (EpistemicStatus.SUPERSEDED, EpistemicStatus.INVALIDATED)

    @property
    def is_active(self) -> bool:
        return self in (EpistemicStatus.VALIDATED, EpistemicStatus.CANONICAL)


# ── 4. Warrant status ─────────────────────────────────────────────────────

class WarrantStatus(str, Enum):
    WARRANTED = "warranted"
    CONDITIONALLY_WARRANTED = "conditionally_warranted"
    UNWARRANTED = "unwarranted"
    UNRESOLVED = "unresolved"


# ── 5. Epistemic anti-patterns (derived diagnoses, not primary classifiers) ─

class AntiPattern(str, Enum):
    CALIBRATED_TO_CONCLUSION = "calibrated_to_conclusion"
    TAUTOLOGICAL_VALIDATION = "tautological_validation"
    INERT_PARAMETER = "inert_parameter"
    PHYSICALLY_UNREALIZABLE = "physically_unrealizable"
    UNSUPPORTED_TRANSFER = "unsupported_transfer"
    CIRCULAR_DEPENDENCY = "circular_dependency"


# ── 6. Confidence ─────────────────────────────────────────────────────────

class ConfidenceLevel(str, Enum):
    SPECULATIVE = "speculative"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CERTAIN = "certain"


# ── 7. Valid transitions ──────────────────────────────────────────────────

VALID_TRANSITIONS: dict[EpistemicStatus, set[EpistemicStatus]] = {
    EpistemicStatus.PROPOSED: {
        EpistemicStatus.TENTATIVE, EpistemicStatus.VALIDATED,
        EpistemicStatus.INVALIDATED, EpistemicStatus.SUPERSEDED,
    },
    EpistemicStatus.TENTATIVE: {
        EpistemicStatus.VALIDATED, EpistemicStatus.INVALIDATED, EpistemicStatus.SUPERSEDED,
    },
    EpistemicStatus.VALIDATED: {
        EpistemicStatus.CANONICAL, EpistemicStatus.SUPERSEDED, EpistemicStatus.INVALIDATED,
    },
    EpistemicStatus.CANONICAL: {EpistemicStatus.SUPERSEDED},
    EpistemicStatus.SUPERSEDED: set(),
    EpistemicStatus.INVALIDATED: set(),
}


# ── 8. Relations ──────────────────────────────────────────────────────────

class RelationType(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    REFINES = "refines"
    DEPENDS_ON = "depends_on"
    VALIDATES = "validates"
    SUPERSEDES = "supersedes"
    DERIVED_FROM = "derived_from"
    CONSTRAINS = "constrains"
    IMPACTS = "impacts"
    FITTED_ON = "fitted_on"            # KO was fitted/calibrated on this dataset
    TESTED_AGAINST = "tested_against"  # KO was validated against this dataset
    TRANSFERRED_FROM = "transferred_from"  # KO is a property transferred from another domain
    EQUIVALENT_TO = "equivalent_to"    # Domain mapping: equivalence claim


JUSTIFICATION_RELATIONS = frozenset({
    RelationType.SUPPORTS,
    RelationType.DEPENDS_ON,
    RelationType.DERIVED_FROM,
    RelationType.VALIDATES,
    RelationType.FITTED_ON,
    RelationType.TESTED_AGAINST,
    RelationType.TRANSFERRED_FROM,
})

IMPACT_RELATIONS = frozenset({
    RelationType.SUPPORTS,
    RelationType.DEPENDS_ON,
    RelationType.DERIVED_FROM,
    RelationType.VALIDATES,
    RelationType.CONSTRAINS,
    RelationType.IMPACTS,
})


# ── 9. Derivation type: how a KO was produced (explicit, not inferred) ────

class DerivationType(str, Enum):
    MEASURED = "measured"               # Direct physical measurement
    SOURCED = "sourced"                 # From external datasheet/standard
    MATHEMATICAL = "mathematical"       # Derived by mathematical identity/theorem
    FITTED = "fitted"                   # Calibrated/fitted from a dataset
    MODELED = "modeled"                # Output of a model/simulation
    TRANSFERRED = "transferred"         # Transferred from another domain
    DECIDED = "decided"                # Human decision/assertion
    VALIDATED = "validated"            # Result of a verification test
    ASSUMED = "assumed"               # Stated assumption
    COMBINED = "combined"             # Aggregation of multiple sources


# ── 10. Derivation relation: explicit provenance edge ────────────────────
# Replaces vague "derived_from" with structured derivation.

@dataclass
class DerivationRelation:
    """Explicit derivation edge: this KO was produced FROM these upstream KOs/datasets."""
    derivation_type: DerivationType
    upstream_ko_ids: list[str] = field(default_factory=list)     # KOs this KO depends on
    training_dataset_id: str = ""                                 # Dataset used for fitting (if FITTED)
    test_dataset_id: str = ""                                     # Dataset used for validation (if FITTED/VALIDATED)
    domain_source_ko_id: str = ""                                 # Source KO for TRANSFERRED
    domain_mapping_ko_id: str = ""                                # DomainMapping KO justifying the transfer


# ── 11. Dataset: observation population for independence analysis ─────────

@dataclass
class Dataset:
    """A named collection of observations/data points.
    Used to test independence: two derivations using the same dataset are NOT independent.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    source_ko_id: str = ""       # The primary observation/measurement KO this dataset comes from
    observation_count: int = 0
    # Which upstream provenance roots this dataset ultimately traces to
    # Empty = primary source; populated = derived from another source
    derived_from_dataset_ids: list[str] = field(default_factory=list)


# ── 12. Falsifiable validator ─────────────────────────────────────────────

@dataclass
class FalsifiableValidator:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    what_would_falsify: str = ""
    ko_id: str = ""
    passes: bool = True
    observation: str = ""


# ── 13. Provenance ────────────────────────────────────────────────────────

@dataclass
class Provenance:
    source: str
    author: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    revision: int = 1
    derived_from: str | None = None
    independent: bool = True


# ── 14. Relation ──────────────────────────────────────────────────────────

@dataclass
class Relation:
    to: str
    type: RelationType


# ── 14.5 SimulationGatePolicy types (v0.6) ─────────────────────────────────

class GateStatus(str, Enum):
    """Status of a single gate in the SimulationGatePolicy."""
    PASS = "pass"
    BLOCK = "block"
    UNKNOWN = "unknown"


@dataclass
class GateResult:
    """Result of evaluating a single gate."""
    gate_name: str
    status: GateStatus
    reason: str = ""
    evidence: list[str] = field(default_factory=list)


@dataclass
class ScopeDeclaration:
    """Explicit physical scope of a model. Acts as a warrant boundary."""
    modeled_domain: str = ""
    modeled_extent: str = ""
    included_components: list[str] = field(default_factory=list)
    excluded_components: list[str] = field(default_factory=list)
    system_boundary: str = ""
    allowed_claim_classes: list[str] = field(default_factory=list)
    disallowed_claim_classes: list[str] = field(default_factory=list)


@dataclass
class SimulationProvenance:
    """Provenance chain for an executable simulation.
    The actual chain is stored as graph relations. This dataclass provides
    structured metadata that must be present for the provenance gate to PASS.
    """
    result_artifact: str = ""
    result_sha256: str = ""
    run_id: str = ""
    parameter_set_id: str = ""
    build_artifact: str = ""
    model_id: str = ""
    source_path: str = ""
    source_commit: str = ""
    source_version: str = ""


@dataclass
class FrozenBaseline:
    """Immutable snapshot of a simulation study."""
    baseline_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    version: int = 1
    model_id: str = ""
    source_commit: str = ""
    parameter_set_id: str = ""
    run_command: str = ""
    result_artifact: str = ""
    result_sha256: str = ""
    gate_report: str = ""
    allowed_claims: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    immutable: bool = True


@dataclass
class SimulationGateReport:
    """Report of all four gate evaluations for a simulation-bearing claim."""
    claim_ko_id: str = ""
    provenance: GateResult = field(default_factory=lambda: GateResult("provenance", GateStatus.UNKNOWN))
    scope: GateResult = field(default_factory=lambda: GateResult("scope", GateStatus.UNKNOWN))
    reality: GateResult = field(default_factory=lambda: GateResult("reality", GateStatus.UNKNOWN))
    falsifiability: GateResult = field(default_factory=lambda: GateResult("falsifiability", GateStatus.UNKNOWN))
    design_bearing: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def all_pass(self) -> bool:
        return all(
            g.status == GateStatus.PASS
            for g in (self.provenance, self.scope, self.reality, self.falsifiability)
        )

    def any_block(self) -> bool:
        return any(
            g.status == GateStatus.BLOCK
            for g in (self.provenance, self.scope, self.reality, self.falsifiability)
        )

    def any_unknown(self) -> bool:
        return any(
            g.status == GateStatus.UNKNOWN
            for g in (self.provenance, self.scope, self.reality, self.falsifiability)
        )

    def to_dict(self) -> dict:
        return {
            "claim_ko_id": self.claim_ko_id,
            "provenance": {"gate": self.provenance.gate_name, "status": self.provenance.status.value, "reason": self.provenance.reason},
            "scope": {"gate": self.scope.gate_name, "status": self.scope.status.value, "reason": self.scope.reason},
            "reality": {"gate": self.reality.gate_name, "status": self.reality.status.value, "reason": self.reality.reason},
            "falsifiability": {"gate": self.falsifiability.gate_name, "status": self.falsifiability.status.value, "reason": self.falsifiability.reason},
            "design_bearing": self.design_bearing,
            "timestamp": self.timestamp,
        }


# ── 15. Anti-pattern diagnosis (structural, not keyword) ──────────────────

@dataclass
class AntiPatternDiagnosis:
    """Output of structural graph analysis. Replaces keyword-based detection."""
    pattern: AntiPattern
    offending_ko_ids: list[str] = field(default_factory=list)
    justification_path: list[str] = field(default_factory=list)
    shared_roots: list[str] = field(default_factory=list)
    violated_condition: str = ""
    resolution_hint: str = ""       # what additional evidence would resolve


# ── 16. Knowledge Object ──────────────────────────────────────────────────

@dataclass
class KnowledgeObject:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: KOType = KOType.REQUIREMENT
    title: str = ""
    content: Any = None

    truth_category: TruthCategory = TruthCategory.ASSUMPTION
    viewpoint_ids: list[str] = field(default_factory=list)

    # Provenance
    provenance: Provenance | None = None

    # Derivation: explicit HOW this KO was produced
    derivation: DerivationRelation | None = None

    # Epistemic status (lifecycle)
    epistemic_status: EpistemicStatus = EpistemicStatus.PROPOSED
    confidence: ConfidenceLevel = ConfidenceLevel.SPECULATIVE

    # Temporal and contextual validity
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    assumptions: list[str] = field(default_factory=list)
    scope: str = ""

    # Revision linkage
    supersedes_id: str | None = None
    superseded_by_id: str | None = None

    # Cross-references
    evidence_ids: list[str] = field(default_factory=list)
    tension_ids: list[str] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)

    # Anti-patterns detected on this KO (v0.4 legacy, deprecated)
    anti_patterns: list[str] = field(default_factory=list)

    # Falsifiable validators attached to this KO
    validators: list[FalsifiableValidator] = field(default_factory=list)

    # Review flag (from v0.3 impact propagation)
    review_required: bool = False
    review_reason: str = ""

    def is_canonical(self) -> bool:
        return self.epistemic_status == EpistemicStatus.CANONICAL

    def can_transition_to(self, target: EpistemicStatus) -> bool:
        return target in VALID_TRANSITIONS.get(self.epistemic_status, set())

    def __post_init__(self):
        if self.provenance is None:
            self.provenance = Provenance(source="system", author="system")
