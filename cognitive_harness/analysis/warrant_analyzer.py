# FILE: cognitive-harness/analysis/warrant_analyzer.py
"""Warrant Analyzer v0.5 — Structural Epistemic Warrant.

Replaces keyword-based anti-pattern detection with graph-structural analysis.

Core principle: warrant depends on graph structure and provenance independence,
NOT on KO type, labels, names, confidence, or content text.

Every classification must be explainable by returning the relevant graph path
and violated structural condition.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from cognitive_harness.model.ko import (
    KnowledgeObject, EpistemicStatus, TruthCategory, WarrantStatus,
    AntiPattern, RelationType, JUSTIFICATION_RELATIONS, Dataset,
    DerivationType, AntiPatternDiagnosis,
)
from cognitive_harness.storage.interface import StorageInterface

log = logging.getLogger(__name__)


@dataclass
class IndependenceResult:
    """Result of independence analysis for a set of evidence KOs."""
    evidence_ids: list[str] = field(default_factory=list)
    evidence_count: int = 0
    independent_root_count: int = 0
    root_sets: dict[str, set[str]] = field(default_factory=dict)  # evidence_id -> {root_ko_ids}
    shared_ancestors: dict[str, set[str]] = field(default_factory=dict)  # root_id -> {evidence_ids sharing it}


@dataclass
class WarrantResult:
    conclusion_ko_id: str
    warrant_status: WarrantStatus
    supporting_kos: list[str] = field(default_factory=list)
    independent_kos: list[str] = field(default_factory=list)
    dependent_kos: list[str] = field(default_factory=list)
    anti_pattern_diagnoses: list[AntiPatternDiagnosis] = field(default_factory=list)
    conditional_assumptions: list[str] = field(default_factory=list)
    justification_path: list[str] = field(default_factory=list)
    # Independence analysis
    independence: IndependenceResult | None = None
    # Cycles found
    cycles: list[list[str]] = field(default_factory=list)


class WarrantAnalyzer:
    """Computes warrant for conclusions by analyzing the justification graph structure."""

    def __init__(self, storage: StorageInterface):
        self.storage = storage

    # ── Public API ──────────────────────────────────────────────────────

    def compute_warrant(self, conclusion_ko_id: str) -> WarrantResult:
        result = WarrantResult(
            conclusion_ko_id=conclusion_ko_id,
            warrant_status=WarrantStatus.UNRESOLVED,
        )

        conclusion = self.storage.get_ko(conclusion_ko_id)
        if conclusion is None:
            return result

        # 1. Build justification graph (BFS backward)
        path, cycles = self._collect_justification_path(conclusion_ko_id)
        result.supporting_kos = path
        result.justification_path = path
        result.cycles = cycles

        # 2. Structural anti-pattern detection
        diagnoses = self._detect_structural_anti_patterns(conclusion_ko_id, path)
        result.anti_pattern_diagnoses = diagnoses

        # 3. Independence analysis for supporting evidence
        indep = self._analyze_independence(path)
        result.independence = indep

        # 4. Classify each carrying KO
        independent = []
        dependent = []

        for ko_id in path:
            if ko_id == conclusion_ko_id:
                continue
            ko = self.storage.get_ko(ko_id)
            if ko is None:
                dependent.append(ko_id)
                continue

            if self._has_independent_grounding(ko, path):
                independent.append(ko_id)
            elif ko.truth_category == TruthCategory.ASSUMPTION:
                result.conditional_assumptions.append(f"{ko_id}: {ko.title}")
                dependent.append(ko_id)
            elif ko.truth_category == TruthCategory.DOCUMENTED_DECISION:
                # Decisions are grounded AS decisions but do not prove physical reality
                independent.append(ko_id)
            else:
                dependent.append(ko_id)

        result.independent_kos = independent
        result.dependent_kos = dependent

        # 4b. If conclusion has no supporting premises, check its own grounding
        has_premises = len(path) > 1
        if not has_premises:
            conc = self.storage.get_ko(conclusion_ko_id)
            if conc is not None:
                if conc.provenance is None or not conc.provenance.independent:
                    dependent.append(conclusion_ko_id)
                    result.dependent_kos = dependent

        # 5. Check if all SUPPORTS premises share the same provenance root
        shared_root_weakness = False
        supports_premises: list[str] = []
        if indep:
            supports_premises = [
                kid for kid in path
                if kid != conclusion_ko_id
                and any(
                    rel.type == RelationType.SUPPORTS and rel.to == kid
                    for rel in (self.storage.get_ko(conclusion_ko_id) or KnowledgeObject()).relations
                )
            ]
            if len(supports_premises) >= 2:
                premise_roots = [indep.root_sets.get(p, set()) for p in supports_premises]
                non_empty_roots = [r for r in premise_roots if r]
                if len(non_empty_roots) >= 2:
                    # Check if all share the same root set
                    first_roots = non_empty_roots[0]
                    if all(r == first_roots for r in non_empty_roots[1:]):
                        shared_root_weakness = True

        # 6. Determine warrant status
        has_structural_defect = any(
            d.pattern in (AntiPattern.CALIBRATED_TO_CONCLUSION,
                          AntiPattern.TAUTOLOGICAL_VALIDATION,
                          AntiPattern.CIRCULAR_DEPENDENCY,
                          AntiPattern.PHYSICALLY_UNREALIZABLE,
                          AntiPattern.UNSUPPORTED_TRANSFER)
            for d in diagnoses
        )

        has_cycles = len(cycles) > 0

        if has_structural_defect or has_cycles:
            result.warrant_status = WarrantStatus.UNWARRANTED
        elif dependent and not has_structural_defect:
            all_assumptions = all(
                (self.storage.get_ko(kid) or KnowledgeObject()).truth_category == TruthCategory.ASSUMPTION
                for kid in dependent
                if self.storage.get_ko(kid)
            )
            if all_assumptions:
                result.warrant_status = WarrantStatus.CONDITIONALLY_WARRANTED
            else:
                result.warrant_status = WarrantStatus.UNWARRANTED
        elif shared_root_weakness:
            result.warrant_status = WarrantStatus.CONDITIONALLY_WARRANTED
            for r in (indep.root_sets.get(supports_premises[0], set()) if supports_premises else set()):
                result.conditional_assumptions.append(
                    f"All SUPPORTS premises share provenance root: {r}")
        elif not dependent:
            result.warrant_status = WarrantStatus.WARRANTED
        else:
            result.warrant_status = WarrantStatus.UNWARRANTED

        return result

    def detect_all_anti_patterns(self) -> list[AntiPatternDiagnosis]:
        all_ko_ids = [ko.id for ko in self._iter_all_kos()]
        all_diagnoses: list[AntiPatternDiagnosis] = []

        # Build a constraint index: all KOs that are conservation laws
        constraint_ids = {
            ko.id for ko in self._iter_all_kos()
            if ko.truth_category == TruthCategory.CONSERVATION_LAW
        }

        for ko in self._iter_all_kos():
            # Check TRANSFERRED derivation
            if ko.derivation and ko.derivation.derivation_type == DerivationType.TRANSFERRED:
                d = self._check_unsupported_transfer(ko)
                if d:
                    all_diagnoses.append(d)

            # Check FITTED derivation (calibrated_to_conclusion)
            if ko.derivation and ko.derivation.derivation_type == DerivationType.FITTED:
                d = self._check_calibrated_to_conclusion(ko, ko.id, [ko.id])
                if d:
                    all_diagnoses.append(d)

            # Check VALIDATED derivation (tautological)
            if ko.derivation and ko.derivation.derivation_type == DerivationType.VALIDATED:
                d = self._check_tautological_validation(ko, all_ko_ids)
                if d:
                    all_diagnoses.append(d)

            # Check physically unrealizable (constraint contradiction)
            d = self._check_physically_unrealizable_all(ko, constraint_ids)
            if d:
                all_diagnoses.append(d)

            # Check circular dependency (self-referential evidence)
            d = self._check_self_referential_evidence(ko)
            if d:
                all_diagnoses.append(d)

        return all_diagnoses

    # ── Justification graph traversal with cycle detection ──────────────

    def _collect_justification_path(
        self, ko_id: str,
    ) -> tuple[list[str], list[list[str]]]:
        """BFS backward through justification relations.
        Returns (path, cycles_found). Detects direct and indirect cycles.
        """
        visited: set[str] = set()
        in_stack: set[str] = set()
        path: list[str] = []
        cycles: list[list[str]] = []
        parent: dict[str, str | None] = {}
        queue = [ko_id]

        while queue:
            current = queue.pop(0)
            if current in in_stack:
                # Found a cycle — trace it
                cycle = [current]
                p = parent.get(current)
                while p and p != current:
                    cycle.append(p)
                    p = parent.get(p)
                if p == current:
                    cycle.append(current)
                    cycle.reverse()
                    cycles.append(cycle)
                continue
            if current in visited:
                continue
            visited.add(current)
            in_stack.add(current)
            path.append(current)

            ko = self.storage.get_ko(current)
            if ko is None:
                in_stack.discard(current)
                continue

            # Follow justification relations backward
            for rel in ko.relations:
                if rel.type in JUSTIFICATION_RELATIONS and rel.to not in visited:
                    parent[rel.to] = current
                    queue.append(rel.to)

            # Follow derivation upstream
            if ko.derivation:
                for up_id in ko.derivation.upstream_ko_ids:
                    if up_id not in visited:
                        parent[up_id] = current
                        queue.append(up_id)

            in_stack.discard(current)

        return path, cycles

    # ── Structural anti-pattern detection ───────────────────────────────

    def _detect_structural_anti_patterns(
        self, conclusion_ko_id: str, path: list[str],
    ) -> list[AntiPatternDiagnosis]:
        diagnoses: list[AntiPatternDiagnosis] = []

        for ko_id in path:
            ko = self.storage.get_ko(ko_id)
            if ko is None:
                continue

            # 1. CALIBRATED_TO_CONCLUSION: fitted parameter with no independent test dataset
            if ko.derivation and ko.derivation.derivation_type == DerivationType.FITTED:
                d = self._check_calibrated_to_conclusion(ko, conclusion_ko_id, path)
                if d:
                    diagnoses.append(d)

            # 2. TAUTOLOGICAL_VALIDATION: validator quantities share same derived source
            if ko.derivation and ko.derivation.derivation_type == DerivationType.VALIDATED:
                d = self._check_tautological_validation(ko, path)
                if d:
                    diagnoses.append(d)

            # 3. UNSUPPORTED_TRANSFER: transfer without domain mapping
            if ko.derivation and ko.derivation.derivation_type == DerivationType.TRANSFERRED:
                d = self._check_unsupported_transfer(ko)
                if d:
                    diagnoses.append(d)

        # 4. CIRCULAR_DEPENDENCY: any cycle in justification graph
        cycles = self._find_cycles_in_path(path)
        if cycles:
            for cycle in cycles:
                diagnoses.append(AntiPatternDiagnosis(
                    pattern=AntiPattern.CIRCULAR_DEPENDENCY,
                    offending_ko_ids=cycle,
                    justification_path=cycle,
                    violated_condition=(
                        f"Cycle in justification graph: {' -> '.join(cycle)}"
                    ),
                    resolution_hint="Break the cycle by providing at least one independently sourced premise.",
                ))

        # 5. PHYSICALLY_UNREALIZABLE: KO violates a constraint in the graph
        for ko_id in path:
            ko = self.storage.get_ko(ko_id)
            if ko is None:
                continue
            d = self._check_physically_unrealizable(ko, path)
            if d:
                diagnoses.append(d)

        return diagnoses

    # ── Individual structural checks ────────────────────────────────────

    def _check_calibrated_to_conclusion(
        self, ko: KnowledgeObject, conclusion_ko_id: str, path: list[str],
    ) -> AntiPatternDiagnosis | None:
        """Structural: fitted parameter is calibrated to the conclusion if
        its training and test datasets share provenance roots, OR if it
        has no test dataset (fitted and tested on same data).
        """
        if not ko.derivation:
            return None

        training_id = ko.derivation.training_dataset_id
        test_id = ko.derivation.test_dataset_id

        # No test dataset at all → fitted parameter is pure calibration
        if not test_id:
            return AntiPatternDiagnosis(
                pattern=AntiPattern.CALIBRATED_TO_CONCLUSION,
                offending_ko_ids=[ko.id],
                justification_path=[ko.id],
                violated_condition="Fitted parameter has no independent test dataset.",
                resolution_hint="Add a test dataset that is disjoint from the training dataset.",
            )

        # Check dataset independence
        train_ds = self.storage.get_dataset(training_id)
        test_ds = self.storage.get_dataset(test_id)

        if train_ds is None or test_ds is None:
            # Datasets not registered — cannot verify independence
            return AntiPatternDiagnosis(
                pattern=AntiPattern.CALIBRATED_TO_CONCLUSION,
                offending_ko_ids=[ko.id],
                justification_path=[ko.id],
                violated_condition="Training or test dataset not found in storage.",
                resolution_hint="Register both training and test datasets.",
            )

        # Check if training and test datasets share provenance roots
        train_roots = self._trace_dataset_roots(train_ds)
        test_roots = self._trace_dataset_roots(test_ds)

        shared = train_roots & test_roots
        if shared:
            return AntiPatternDiagnosis(
                pattern=AntiPattern.CALIBRATED_TO_CONCLUSION,
                offending_ko_ids=[ko.id],
                shared_roots=list(shared),
                violated_condition=(
                    f"Training and test datasets share provenance roots: {shared}. "
                    f"Parameter was fitted and tested on overlapping observations."
                ),
                resolution_hint="Use a test dataset with disjoint provenance roots from the training set.",
            )

        return None  # Genuinely independent training/test split

    def _check_tautological_validation(
        self, ko: KnowledgeObject, path: list[str],
    ) -> AntiPatternDiagnosis | None:
        """Structural: a validation is tautological if all quantities it compares
        ultimately derive from the same source KO.
        """
        if not ko.derivation:
            return None

        upstream_ids = ko.derivation.upstream_ko_ids
        if not upstream_ids:
            return None

        # Trace all upstream KOs to their provenance roots
        all_roots: set[str] = set()
        root_map: dict[str, set[str]] = {}
        for up_id in upstream_ids:
            roots = self._trace_provenance_roots(up_id)
            root_map[up_id] = roots
            all_roots |= roots

        # If all upstream quantities trace to the same single root, it's tautological
        if len(all_roots) == 1:
            single_root = list(all_roots)[0]
            return AntiPatternDiagnosis(
                pattern=AntiPattern.TAUTOLOGICAL_VALIDATION,
                offending_ko_ids=[ko.id] + upstream_ids,
                justification_path=upstream_ids,
                shared_roots=[single_root],
                violated_condition=(
                    f"All validated quantities trace to a single source: {single_root}. "
                    f"This is an identity check, not an independent measurement."
                ),
                resolution_hint="Include at least one quantity measured or derived from an independent source.",
            )

        # If any pair of upstream quantities share all their roots
        root_pairs = list(root_map.items())
        for i in range(len(root_pairs)):
            for j in range(i + 1, len(root_pairs)):
                id_a, roots_a = root_pairs[i]
                id_b, roots_b = root_pairs[j]
                if roots_a and roots_b and roots_a == roots_b:
                    return AntiPatternDiagnosis(
                        pattern=AntiPattern.TAUTOLOGICAL_VALIDATION,
                        offending_ko_ids=[ko.id, id_a, id_b],
                        justification_path=[id_a, id_b],
                        shared_roots=list(roots_a),
                        violated_condition=(
                            f"Quantities {id_a} and {id_b} share identical provenance roots: {roots_a}. "
                            f"Comparing them is a tautological check."
                        ),
                        resolution_hint="Compare quantities derived from different provenance roots.",
                    )

        return None

    def _check_unsupported_transfer(
        self, ko: KnowledgeObject,
    ) -> AntiPatternDiagnosis | None:
        """Structural: a cross-domain transfer requires an explicit DomainMapping KO
        in the graph that justifies the transfer.
        """
        if not ko.derivation:
            return None
        if ko.derivation.derivation_type != DerivationType.TRANSFERRED:
            return None

        mapping_id = ko.derivation.domain_mapping_ko_id

        if not mapping_id:
            # No domain mapping provided
            src_id = ko.derivation.domain_source_ko_id
            return AntiPatternDiagnosis(
                pattern=AntiPattern.UNSUPPORTED_TRANSFER,
                offending_ko_ids=[ko.id] + ([src_id] if src_id else []),
                violated_condition=(
                    f"KO {ko.id} was transferred from domain source {src_id or 'unknown'} "
                    f"but no domain mapping KO justifies the transfer."
                ),
                resolution_hint=(
                    "Create a DomainMapping KO with EQUIVALENT_TO relations "
                    "connecting source and target domains, including assumptions and invariants."
                ),
            )

        # Domain mapping exists — verify it is properly structured
        mapping_ko = self.storage.get_ko(mapping_id)
        if mapping_ko is None:
            return AntiPatternDiagnosis(
                pattern=AntiPattern.UNSUPPORTED_TRANSFER,
                offending_ko_ids=[ko.id],
                violated_condition=f"Domain mapping KO {mapping_id} not found in storage.",
                resolution_hint="Create the referenced DomainMapping KO.",
            )

        # Check that the mapping has upstream evidence (assumptions with provenance)
        if mapping_ko.derivation and mapping_ko.derivation.upstream_ko_ids:
            return None  # Mapping has structural support

        # Mapping exists but has no structural support — conditional
        return AntiPatternDiagnosis(
            pattern=AntiPattern.UNSUPPORTED_TRANSFER,
            offending_ko_ids=[ko.id, mapping_id],
            violated_condition=(
                f"Domain mapping KO {mapping_id} exists but has no upstream evidence."
            ),
            resolution_hint="Add assumptions or invariants to the domain mapping with independent provenance.",
        )

    def _check_physically_unrealizable(
        self, ko: KnowledgeObject, path: list[str],
    ) -> AntiPatternDiagnosis | None:
        """Structural: check if a KO is contradicted by a constraint KO in the graph.
        A constraint KO with type=CONSTRAINT and truth_category=CONSERVATION_LAW
        that CONTRADICTS this KO indicates physical unrealizability.
        """
        for rel in ko.relations:
            if rel.type == RelationType.CONTRADICTS:
                # This KO contradicts something — check if that something is a constraint
                other = self.storage.get_ko(rel.to)
                if other and other.truth_category == TruthCategory.CONSERVATION_LAW:
                    return AntiPatternDiagnosis(
                        pattern=AntiPattern.PHYSICALLY_UNREALIZABLE,
                        offending_ko_ids=[ko.id, other.id],
                        violated_condition=(
                            f"KO {ko.id} contradicts conservation law/constraint {other.id}: {other.title}"
                        ),
                        resolution_hint="Correct the model to satisfy the physical constraint.",
                    )

        # Also check: is this KO contradicted by a constraint?
        for pid in path:
            if pid == ko.id:
                continue
            other = self.storage.get_ko(pid)
            if other is None:
                continue
            for rel in other.relations:
                if rel.type == RelationType.CONTRADICTS and rel.to == ko.id:
                    if other.truth_category == TruthCategory.CONSERVATION_LAW:
                        return AntiPatternDiagnosis(
                            pattern=AntiPattern.PHYSICALLY_UNREALIZABLE,
                            offending_ko_ids=[other.id, ko.id],
                            violated_condition=(
                                f"Constraint {other.id} ({other.title}) contradicts {ko.id}."
                            ),
                            resolution_hint="Resolve the contradiction with the physical constraint.",
                        )

        return None

    def _check_physically_unrealizable_all(
        self, ko: KnowledgeObject, constraint_ids: set[str],
    ) -> AntiPatternDiagnosis | None:
        """Check if a KO contradicts a conservation law (all-KOs variant)."""
        for rel in ko.relations:
            if rel.type == RelationType.CONTRADICTS:
                other = self.storage.get_ko(rel.to)
                if other and other.truth_category == TruthCategory.CONSERVATION_LAW:
                    return AntiPatternDiagnosis(
                        pattern=AntiPattern.PHYSICALLY_UNREALIZABLE,
                        offending_ko_ids=[ko.id, other.id],
                        violated_condition=(
                            f"KO {ko.id} contradicts conservation law/constraint {other.id}: {other.title}"
                        ),
                        resolution_hint="Correct the model to satisfy the physical constraint.",
                    )

        # Check if this KO is contradicted by a constraint
        for cid in constraint_ids:
            if cid == ko.id:
                continue
            other = self.storage.get_ko(cid)
            if other is None:
                continue
            for rel in other.relations:
                if rel.type == RelationType.CONTRADICTS and rel.to == ko.id:
                    return AntiPatternDiagnosis(
                        pattern=AntiPattern.PHYSICALLY_UNREALIZABLE,
                        offending_ko_ids=[other.id, ko.id],
                        violated_condition=(
                            f"Constraint {other.id} ({other.title}) contradicts {ko.id}."
                        ),
                        resolution_hint="Resolve the contradiction with the physical constraint.",
                    )

        return None

    def _check_self_referential_evidence(
        self, ko: KnowledgeObject,
    ) -> AntiPatternDiagnosis | None:
        """Check if any evidence for this KO has claim_id == ko.id (self-referential)."""
        for ev_id in ko.evidence_ids:
            ev = self.storage.get_evidence(ev_id)
            if ev and ev.get("claim_id") == ko.id:
                return AntiPatternDiagnosis(
                    pattern=AntiPattern.CIRCULAR_DEPENDENCY,
                    offending_ko_ids=[ko.id],
                    justification_path=[ko.id],
                    violated_condition=(
                        f"KO {ko.id} cites evidence {ev_id} with claim_id == {ko.id} "
                        f"(self-referential evidence)."
                    ),
                    resolution_hint="Evidence must reference an independent claim, not the KO itself.",
                )
        return None

    def _find_cycles_in_path(self, path: list[str]) -> list[list[str]]:
        """Detect cycles in the justification graph using DFS."""
        # Build adjacency: for each KO, which KOs does it depend on?
        adj: dict[str, list[str]] = {}
        for ko_id in path:
            ko = self.storage.get_ko(ko_id)
            if ko is None:
                continue
            neighbors = []
            for rel in ko.relations:
                if rel.type in JUSTIFICATION_RELATIONS and rel.to in path:
                    neighbors.append(rel.to)
            if ko.derivation:
                for up_id in ko.derivation.upstream_ko_ids:
                    if up_id in path:
                        neighbors.append(up_id)
            adj[ko_id] = neighbors

        # DFS cycle detection
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in path}
        cycles: list[list[str]] = []
        stack_path: list[str] = []

        def dfs(node: str):
            color[node] = GRAY
            stack_path.append(node)
            for nb in adj.get(node, []):
                if color.get(nb) == GRAY:
                    # Found cycle
                    ci = stack_path.index(nb)
                    cycle = stack_path[ci:] + [nb]
                    cycles.append(cycle)
                elif color.get(nb) == WHITE:
                    dfs(nb)
            stack_path.pop()
            color[node] = BLACK

        for nid in path:
            if color.get(nid) == WHITE:
                dfs(nid)

        return cycles

    # ── Independence analysis ───────────────────────────────────────────

    def _analyze_independence(self, path: list[str]) -> IndependenceResult:
        """Compute independent provenance roots for every supporting evidence item.
        Evidence count is not source count.
        """
        result = IndependenceResult(evidence_ids=path)

        # For each KO in the path, find its provenance roots
        root_sets: dict[str, set[str]] = {}
        for ko_id in path:
            roots = self._trace_provenance_roots(ko_id)
            root_sets[ko_id] = roots

        result.root_sets = root_sets

        # Count distinct root sets (independent sources)
        all_root_sets = set()
        for roots in root_sets.values():
            if roots:
                all_root_sets.add(frozenset(roots))

        result.evidence_count = len(path)
        result.independent_root_count = len(all_root_sets)

        # Find shared ancestors
        shared: dict[str, set[str]] = {}
        for ko_id, roots in root_sets.items():
            for root in roots:
                if root not in shared:
                    shared[root] = set()
                shared[root].add(ko_id)

        # Only report roots shared by multiple KOs
        result.shared_ancestors = {
            r: kos for r, kos in shared.items() if len(kos) > 1
        }

        return result

    def _trace_provenance_roots(self, ko_id: str) -> set[str]:
        """Trace a KO back to its ultimate provenance roots.
        Roots are KOs with no further upstream derivation (leaf nodes).
        """
        visited: set[str] = set()
        roots: set[str] = set()
        queue = [ko_id]

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            ko = self.storage.get_ko(current)
            if ko is None:
                roots.add(current)
                continue

            has_upstream = False

            # Follow derivation upstream
            if ko.derivation:
                for up_id in ko.derivation.upstream_ko_ids:
                    has_upstream = True
                    if up_id not in visited:
                        queue.append(up_id)

                # Follow datasets
                if ko.derivation.training_dataset_id:
                    ds = self.storage.get_dataset(ko.derivation.training_dataset_id)
                    if ds and ds.source_ko_id:
                        has_upstream = True
                        if ds.source_ko_id not in visited:
                            queue.append(ds.source_ko_id)
                if ko.derivation.test_dataset_id:
                    ds = self.storage.get_dataset(ko.derivation.test_dataset_id)
                    if ds and ds.source_ko_id:
                        has_upstream = True
                        if ds.source_ko_id not in visited:
                            queue.append(ds.source_ko_id)

            # Follow derivation relations
            for rel in ko.relations:
                if rel.type in (RelationType.DERIVED_FROM, RelationType.TRANSFERRED_FROM):
                    has_upstream = True
                    if rel.to not in visited:
                        queue.append(rel.to)

            if not has_upstream:
                roots.add(current)

        return roots

    def _trace_dataset_roots(self, dataset: 'Dataset') -> set[str]:
        """Trace a dataset back to its ultimate source KOs."""
        visited: set[str] = set()
        roots: set[str] = set()

        if dataset.source_ko_id:
            roots |= self._trace_provenance_roots(dataset.source_ko_id)

        # If derived from other datasets, trace those
        for ds_id in dataset.derived_from_dataset_ids:
            parent_ds = self.storage.get_dataset(ds_id)
            if parent_ds:
                if ds_id not in visited:
                    visited.add(ds_id)
                    roots |= self._trace_dataset_roots(parent_ds)

        if not roots and dataset.source_ko_id:
            roots.add(dataset.source_ko_id)

        return roots

    # ── Independent grounding check ─────────────────────────────────────

    def _has_independent_grounding(
        self, ko: KnowledgeObject, path: list[str],
    ) -> bool:
        """Check if a KO has independent structural grounding.
        Does NOT use truth category alone — uses graph structure.
        """
        if ko.provenance is None or not ko.provenance.independent:
            return False

        # Conservation laws and mathematical identities are always grounded
        if ko.truth_category in (TruthCategory.CONSERVATION_LAW, TruthCategory.MATHEMATICAL_IDENTITY):
            return True

        # Fitted parameters: must have independent test dataset
        if ko.derivation and ko.derivation.derivation_type == DerivationType.FITTED:
            test_id = ko.derivation.test_dataset_id
            if test_id:
                test_ds = self.storage.get_dataset(test_id)
                if test_ds:
                    train_id = ko.derivation.training_dataset_id
                    train_ds = self.storage.get_dataset(train_id)
                    if train_ds:
                        train_roots = self._trace_dataset_roots(train_ds)
                        test_roots = self._trace_dataset_roots(test_ds)
                        return train_roots != test_roots and not (train_roots & test_roots)
            return False

        # Transferred: must have domain mapping
        if ko.derivation and ko.derivation.derivation_type == DerivationType.TRANSFERRED:
            return bool(ko.derivation.domain_mapping_ko_id)

        # Physical observations: must have evidence
        if ko.truth_category == TruthCategory.PHYSICAL_OBSERVATION:
            return bool(ko.evidence_ids)

        # Sourced material data: must have non-system source
        if ko.truth_category == TruthCategory.SOURCED_MATERIAL_DATA:
            return ko.provenance.source != "system"

        # Validation results: check for tautology
        if ko.derivation and ko.derivation.derivation_type == DerivationType.VALIDATED:
            upstream = ko.derivation.upstream_ko_ids
            if len(upstream) < 2:
                return False
            # Check that upstream quantities have different roots
            root_sets = []
            for up_id in upstream:
                roots = self._trace_provenance_roots(up_id)
                root_sets.append(roots)
            # At least two must have different roots
            if len(root_sets) >= 2:
                return root_sets[0] != root_sets[1]
            return False

        # Model-derived: must have upstream derivation
        if ko.derivation and ko.derivation.derivation_type == DerivationType.MODELED:
            return len(ko.derivation.upstream_ko_ids) > 0

        # Default: has independent provenance
        return ko.provenance.independent

    # ── Helpers ─────────────────────────────────────────────────────────

    def _iter_all_kos(self):
        """Iterate all KOs via the public storage interface.

        Uses list_all_kos() (v0.6.3+).  Callers must not reach into
        internal storage details like _kos.
        """
        yield from self.storage.list_all_kos()
