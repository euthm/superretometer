# Cognitive Harness of Harness — OpenSpec v0.6

**Date:** 2026-09-05
**Status:** v0.6 — SimulationGatePolicy
**Scope:** A cognitive harness that distinguishes "the graph contains a conclusion" from "the graph warrants this conclusion." Separates storage, orchestration, reasoning, and analysis. LLM-agnostic: agents submit structured proposals; they never mutate canonical state directly.

**v0.6 additions:**
- SimulationGatePolicy: four-gate evaluation (Provenance, Scope, Reality, Falsifiability) for simulation-bearing claims
- Design-bearing semantics: PASS/BLOCK/UNKNOWN per gate; all PASS required for design-bearing
- ScopeDeclaration: normative scope as warrant boundary, not metadata
- SimulationProvenance: reproducible provenance chain for executable simulations
- FrozenBaseline: immutable snapshot of simulation study with gate report
- Invariant validity: invariants must be valid for declared system boundary, not just computable
- Normative rules N-PROV through N-BASELINE-IMMUTABLE (see spec/WARRANT.md)

**v0.4 additions:**
- Truth categories: every KO declares what KIND of truth claim it makes (physical observation, conservation law, documented decision, fitted parameter, ...)
- Warrant analysis: backward traversal of the justification graph to verify independent grounding of all premises
- Epistemic anti-patterns: calibrated-to-conclusion, tautological validation, inert parameter, physically unrealizable, unsupported transfer
- Falsifiable validators: every validation must declare what observation would falsify it
- Non-linear Threads with transition metadata (Muller's CAFCR Threads of Reasoning)
- Warrant recomputation on supersession (tied to v0.3 impact propagation)

---

## 1. Motivation

Autonomous agents operating over knowledge-intensive domains face three structural problems:

1. **State decay across long trajectories.** Decisions, evidence, and validated knowledge become disconnected from subsequent reasoning. (HoH Yan et al., 2026)
2. **Underspecified next action.** A high-level goal does not determine which knowledge gap to close, which assumption to verify, or which trade-off to resolve. (CAFCR Muller, 2004)
3. **No separation between storage, orchestration, and reasoning.** Storage leaks into reasoning; reasoning artifacts pollute storage; orchestration is embedded in prompts.

Additionally, knowledge is revisable. A "validated" finding may be contradicted by new evidence at a different operating condition. The model must support revision without deleting history.

---

## 2. Authoritative Sources

| Source | Citation | Contribution |
|--------|----------|--------------|
| CAFCR | Muller, G. (2004). *CAFCR: A Multi-view Method for Embedded Systems Architecting*. PhD Thesis, TNO. | Multi-view architecture (Customer, Application, Functional, Conceptual, Realization). Threads of Reasoning: iterative tension analysis across views. Viewpoint hopping. |
| SEMA | Muller, G. (2007). *Architectural Reasoning Explained*. Gaudí. | Conceptual modeling, quality needles, story-telling as requirement elicitation. |
| HoH | Yan et al. (2026). *Harness-of-Harness: Multi-Day Autonomous Software Development with Continual Improvement*. arXiv:2609.01481 | Iterative plan-code-test loops. Evidence bundles. Progressive disclosure. Preservation constraints. |
| ISO 42010 | ISO/IEC/IEEE 42010:2011 | Architecture description: viewpoints, stakeholders, concerns. |
| KBMF | Hendler et al. (2009). *The Knowledge Base Markup Framework*. | Knowledge base lifecycle, provenance, versioning. |

---

## 3. Terminology

| Term | Definition |
|------|-----------|
| **CogHarness** | The cognitive harness system. Three layers: Storage, Orchestration, Reasoning. |
| **Knowledge Object (KO)** | Atomic unit of structured knowledge. Three independent dimensions: **type** (what it is), **truth category** (what kind of truth claim it makes), and **epistemic status** (how well-grounded it is). Each KO has identity, provenance, temporal validity, scope, and succession linkage. |
| **Knowledge Graph (KG)** | Persistent store of KOs and their relationships. Implements the Storage layer contract. |
| **Thread** | First-class executable object: a directed traversal through CAFCR viewpoints, driven by Tensions. Steps examine KOs, ask questions, declare expected transitions, collect evidence, and terminate with an explicit conclusion or unresolved state. |
| **Viewpoint** | CAFCR projection: Customer, Application, Functional, Conceptual, Realization. |
| **Tension** | Documented inconsistency, trade-off, or unresolved question between viewpoints or KOs. Tensions drive the reasoning loop. |
| **Evidence** | Observation, measurement, or test result that supports or refutes a claim. Status: verified, pending, gap, superseded. |
| **Proposal** | Structured mutation request from external sources (agents, humans). Validated deterministically before any state change. |
| **Orchestrator** | Manages Tension queue, Thread lifecycle, Proposal validation, Preservation Constraints. The ONLY component that mutates canonical state. |
| **Reasoner** | Performs analysis within a Thread. Produces structured steps and conclusions. May be rule-based, statistical, or LLM-based. Never writes to storage directly. |
| **Consumer** | Entity (LLM, human, downstream system) that reads knowledge and submits Proposals. Can never mutate canonical state directly. |
| **Truth Category** | Classification of what KIND of truth claim a KO makes: physical observation, sourced material data, conservation law, documented decision, assumption, fitted parameter, model-derived result, validation result. A documented decision has provenance as a decision but is NOT evidence of physical reality. |
| **Warrant** | Epistemic justification for a conclusion. A conclusion is warranted only if every KO that materially carries it has independent grounding. Computed by the WarrantAnalyzer over the justification graph, NOT stored on the KO itself. |
| **Warrant Status** | `WARRANTED`, `CONDITIONALLY_WARRANTED` (exposing conditions), `UNWARRANTED`, `UNRESOLVED`. Separate from epistemic status: a CANONICAL conclusion can be UNWARRANTED if its premises lack independent grounding. |
| **Anti-Pattern** | Epistemic defect in the justification chain: `CALIBRATED_TO_CONCLUSION`, `TAUTOLOGICAL_VALIDATION`, `INERT_PARAMETER`, `PHYSICALLY_UNREALIZABLE`, `UNSUPPORTED_TRANSFER`, `CIRCULAR_DEPENDENCY`. |
| **Falsifiable Validator** | Every validation must declare what observation would falsify it. A check that cannot fail cannot increase epistemic confidence. |
| **WarrantAnalyzer** | Analysis layer component that traverses the justification graph backward (conclusion → premises → provenance) and computes warrant status. Detects anti-patterns. |

---

## 4. Knowledge Model

### 4.1 Knowledge Object — Three Independent Dimensions

A KO separates **what it is** from **what kind of truth claim** it makes from **how well-grounded** it is:

**KO Type** (content classification):
- `REQUIREMENT` — stated requirement or constraint
- `OBSERVATION` — raw observation or measurement
- `HYPOTHESIS` — testable claim
- `DECISION` — recorded choice with alternatives
- `CONSTRAINT` — boundary condition (physical, regulatory, budgetary)
- `MODEL_RESULT` — simulation or analytical output
- `SPECIFICATION` — formal spec clause
- `FINDING` — validated conclusion
- `EVIDENCE_ITEM` — structured evidence record
- `CONCLUSION` — a claim that depends on other KOs

**Truth Category** (what kind of truth claim):
- `PHYSICAL_OBSERVATION` — measured from reality (requires measurement record)
- `SOURCED_MATERIAL_DATA` — datasheet, standard, spec sheet (requires date, revision, manufacturer)
- `CONSERVATION_LAW` — named physical/mathematical law (always independently grounded if correctly cited)
- `DOCUMENTED_DECISION` — human choice; has provenance as a decision but is NOT evidence of physical reality
- `ASSUMPTION` — unverified, testable claim; conditions warrant but never independently grounds
- `FITTED_PARAMETER` — calibrated from data fit (must not be calibrated to the conclusion being tested)
- `MODEL_DERIVED` — output of a model or simulation (requires independent verification path)
- `VALIDATION_RESULT` — result of a verification test (must declare what would falsify it)
- `MATHEMATICAL_IDENTITY` — always true by definition (e.g. P = V*I)

**Epistemic Status** (lifecycle):
- `PROPOSED` — submitted, not evaluated
- `TENTATIVE` — partially supported, insufficient for validation
- `VALIDATED` — sufficient evidence, accepted within scope
- `CANONICAL` — authoritative reference; can only be superseded
- `SUPERSEDED` — replaced by successor (history preserved)
- `INVALIDATED` — contradicted by stronger evidence

**Valid transitions:**
```
PROPOSED  → TENTATIVE | VALIDATED | INVALIDATED | SUPERSEDED
TENTATIVE → VALIDATED | INVALIDATED | SUPERSEDED
VALIDATED → CANONICAL | SUPERSEDED | INVALIDATED
CANONICAL → SUPERSEDED (only)
SUPERSEDED → (terminal)
INVALIDATED → (terminal)
```

A canonical KO can NEVER be directly modified or invalidated. It can only be superseded by creating a new KO and linking them.

### 4.2 Confidence and Provenance

| Dimension | Values | Description |
|-----------|--------|-------------|
| **Confidence** | speculative, low, medium, high, certain | Independent of epistemic status. A hypothesis can be high-confidence (well-reasoned but untested). |
| **Provenance** | source, author, timestamp, revision, derived_from | Full chain of derivation. |

**Simulation provenance (v0.6):** For executable simulations, provenance must be a reproducible chain, not a single attribution:

```
claim → result artifact → result SHA256 → run → parameter set → build artifact → model → source path → source commit → external evidence (optional)
```

Derived artifacts (results, builds) must be distinguishable from canonical source (model code, commit). Orphaned results cannot carry design claims. See N-PROV in spec/WARRANT.md.

### 4.3 Temporal and Contextual Validity

Every KO carries:
- `valid_from` / `valid_to` — temporal bounds
- `assumptions` — conditions under which the KO holds (e.g., ["T = 1173 K", "Fe-Si19 composition"])
- `scope` — domain/context限定 (e.g., "IoStore thermal design")
- `supersedes_id` / `superseded_by_id` — revision linkage

**Scope as warrant boundary (v0.6):** For simulation-bearing claims, scope is normative. A `ScopeDeclaration` must describe: modeled_domain, modeled_extent, included_components, excluded_components, system_boundary, allowed_claim_classes, disallowed_claim_classes. A simulation result may only warrant claims within the explicitly declared scope (N-SCOPE).

### 4.4 Viewpoints (CAFCR)

| Viewpoint | Focus | KO types dominant |
|-----------|-------|-------------------|
| **Customer** | Value, stakeholder needs, success criteria | Requirement, Decision, Specification |
| **Application** | Operating context, environment, interfaces | Observation, Model_Result, Constraint |
| **Functional** | Capabilities, processes, what the system does | Hypothesis, Finding, Requirement |
| **Conceptual** | Architecture, decomposition, trade-offs | Decision, Hypothesis, Finding |
| **Realization** | Implementation, parameters, verified behavior | Observation, Finding, Specification |

### 4.5 Knowledge Graph Schema

Typed property graph:
- **Nodes:** KOs (typed by KOType + EpistemicStatus), Viewpoints, Tensions
- **Edges:** typed relations (supports, contradicts, refines, depends-on, validates, supersedes, derived-from)
- **Indexes:** by viewpoint, by epistemic status, by scope, by temporal validity

---

## 5. Reasoning Model

### 5.1 Threads of Reasoning — First-Class Executable Objects

A Thread is the fundamental reasoning unit. Based on Muller's Threads of Reasoning: reasoning is not a linear chain but a directed traversal through viewpoints driven by tensions.

**Thread structure:**
```
Thread {
    id:                       UUID
    origin_tension_id:        TensionID
    originating_question:     string  # the engineering question
    steps:                    [ThreadStep]
    conclusion:               Conclusion | null
    status:                   active | concluded | unresolved
    viewpoints_visited:       [Viewpoint]  # ordered traversal sequence
}

ThreadStep {
    action:               examine | traverse | question | propose |
                          expect_transition | collect_evidence | evaluate | conclude
    viewpoint:            CAFCR Viewpoint
    input_ko_ids:         KOID[]          # KOs consumed by this step
    output_ko_ids:        KOID[]          # KOs created/modified by this step
    evidence_used:        EvidenceID[]    # evidence consumed
    assumptions_used:     string[]        # assumptions invoked
    transition_reason:    string          # why this transition occurred
    claim:                string          # assertion
    question:             string          # explicit question
    expected_from:        KOID            # KO expected to change
    expected_status:      string          # target epistemic status
    missing_evidence:     string[]        # what evidence is still needed
    speculative:          bool            # unverified claim
}

Conclusion {
    type:           decision | validation | refutation | deferral |
                    promotion | supersession
    target_ko_id:   KOID
    successor_ko_id: KOID        # for supersession
    rationale:      string
    unresolved_tensions: string[] # tensions still open
}
```

**Thread lifecycle:**
1. **Initiation:** Tension → Thread with originating question
2. **Traversal:** Steps traverse CAFCR viewpoints (C→A→F→C→R, not phase-linear)
3. **Questions:** Explicit questions posed at viewpoint boundaries
4. **Hypothesis:** Proposal steps declare expected transitions
5. **Evidence:** Collection and evaluation steps
6. **Termination:** Explicit conclusion OR unresolved state (tension persists)

### 5.2 Tension-Driven Reasoning Loop

```
Loop:
    1. Select highest-priority open Tension
    2. Create Thread with originating question
    3. Thread traverses CAFCR viewpoints, examines KOs
    4. Thread proposes hypotheses, collects evidence
    5. Thread concludes: validation, decision, refutation, deferral, or supersession
    6. Orchestration applies conclusion: updates KOs, creates Preservation Constraints
    7. Repeat until Tension queue empty or budget exhausted
```

### 5.3 Conclusion Types

| Type | Effect |
|------|--------|
| **Decision** | Creates a Decision KO in Conceptual view |
| **Validation** | Promotes a Hypothesis/Observation to Finding (VALIDATED) |
| **Refutation** | Invalidates a KO; creates new Tension |
| **Deferral** | Insufficient evidence; Thread → unresolved, Tension stays open |
| **Promotion** | Validated KO → Canonical (authoritative reference) |
| **Supersession** | Old canonical → SUPERSEDED; new KO becomes canonical; history preserved; warrant recomputed for impacted conclusions |

---

## 6. Knowledge Lifecycle

```
                                    ┌──────────┐
   External input ──▶ Proposal ──▶ │ Proposed │ ◀── Reasoner proposes
                                    └────┬─────┘
                                         │ evidence partial
                                         ▼
                                    ┌──────────┐
                                    │ Tentative│
                                    └────┬─────┘
                                         │ sufficient evidence
                                         ▼
                                    ┌──────────┐
                                    │ Validated│
                                    └────┬─────┘
                                         │ promote
                                         ▼
                                    ┌──────────┐
                                    │ Canonical│ ── authoritative reference
                                    └────┬─────┘
                                         │ new evidence contradicts
                                         ▼
                                    ┌──────────┐     ┌───────────┐
                                    │Superseded│────▶│ New KO    │
                                    │(history  │     │(validated │
                                    │ preserved)│    │ → canonical)│
                                    └──────────┘     └───────────┘

   ┌───────────┐
   │ Invalidated│  ← direct contradiction (not from canonical)
   │ (terminal) │
   └───────────┘
```

**Rules:**
- KOs transition only through valid transitions (section 4.1)
- Canonical KOs can only be superseded; never modified or invalidated in-place
- Supersession creates a linked pair: old (SUPERSEDED) + new (active); succession chain is queryable
- Terminal KOs (SUPERSEDED, INVALIDATED) remain in the graph permanently for auditability
- Promotion to canonical requires: (a) at least one verified evidence record, (b) confidence ≥ MEDIUM

---

## 7. Layer Contracts

### 7.1 Layer Separation

```
┌───────────────────────────────────────────────────┐
│  Consumer Layer (agents, humans)                  │
│  ── READ: query, explain, succession chain        │
│  ── WRITE: submit structured Proposals ONLY       │
│  ── NEVER: direct KO mutation                     │
└──────────────────────┬────────────────────────────┘
                       │ submit_proposal / query
┌──────────────────────▼────────────────────────────┐
│  Orchestration Layer                               │
│  ── Tension queue, Thread lifecycle               │
│  ── Proposal validation (deterministic rules)     │
│  ── Applies Thread conclusions to canonical state │
│  ── Enforces transition rules, succession         │
└──────────────────────┬────────────────────────────┘
                       │ creates Threads, produces Conclusions
┌──────────────────────▼────────────────────────────┐
│  Reasoning Layer                                   │
│  ── Traverses CAFCR viewpoints                    │
│  ── Examines KOs, asks questions, proposes        │
│  ── Collects evidence, evaluates claims           │
│  ── Produces Conclusions (never writes to storage)│
│  ── May be rule-based, statistical, or LLM        │
└──────────────────────┬────────────────────────────┘
                       │ read KO/evidence / submit Proposal
┌──────────────────────▼────────────────────────────┐
│  Storage Layer (Knowledge Graph)                   │
│  ── Persistent, versioned, provenanced            │
│  ── Validates proposals, enforces transitions     │
│  ── Maintains succession chains, temporal indexes │
└───────────────────────────────────────────────────┘
```

### 7.2 Contract: Consumer → Orchestration (Proposal Pipeline)

| Operation | Description | Guarantee |
|-----------|-------------|-----------|
| `propose_ko()` | Submit new KO | Orchestration validates type, viewpoints, scope |
| `propose_evidence()` | Submit evidence for a KO | Links to claim KO; status = pending until reviewed |
| `propose_transition()` | Request epistemic status change | Validated against transition rules; canonical can only → superseded |
| `propose_promote_canonical()` | Promote validated → canonical | Requires verified evidence + confidence ≥ MEDIUM |
| `propose_supersede(old, new)` | Replace canonical with successor | Creates bidirectional link; old → SUPERSEDED; history preserved |
| `propose_relation()` | Add typed relation between KOs | Both KOs must exist |
| `propose_tension()` | Create new tension | Orchestration adds to priority queue |

**All proposals are validated deterministically.** Rejected proposals return a reason. Accepted proposals mutate state.

### 7.3 Contract: Orchestration ←→ Reasoning

| Direction | Operation | Guarantee |
|-----------|-----------|-----------|
| Orchestration → Reasoning | `start_thread(Thread, ko_ids, canonical_ids)` | Provides bounded context; includes canonical Preservation Constraints |
| Reasoning → Orchestration | `continue_thread(Thread) → ThreadStep | Conclusion` | Structured step or conclusion; must cite evidence or mark speculative |
| Orchestration | `apply_conclusion(Thread, Tension, Conclusion)` | Updates KOs per conclusion type; enforces transition rules |

### 7.4 Contract: Storage ←→ Orchestration

| Direction | Operation | Guarantee |
|-----------|-----------|-----------|
| Orchestration → Storage | `create_ko`, `update_ko`, `create_relation` | Storage validates schema, assigns version, records provenance |
| Storage → Orchestration | `get_ko`, `query_by_viewpoint`, `list_canonical`, `get_succession_chain` | Returns typed, versioned results |
| Both | `lock_ko`, `unlock_ko` | Prevents concurrent modification of active Thread KOs |

---

## 8. Consumer Boundary Contract

### 8.1 Where the Consumer Layer Ends and Cognitive Harness Begins

```
┌─────────────────────┐     Proposals     ┌─────────────────────┐
│  Consumer / Agent   │ ──────────────▶   │ Cognitive Harness    │
│                     │  (structured)     │                     │
│  - Product specs    │                   │  Storage            │
│  - Requirements     │  ◀──────────────  │  Orchestration      │
│  - Validation tools │   Conclusions     │  Reasoning          │
│  - Human review     │   (read-only)     │  Analysis           │
└─────────────────────┘                   └─────────────────────┘
```

**The Consumer may:**
- Submit structured Proposals (create KOs, evidence, tensions) via ConsumerAPI
- Query conclusions and canonical KOs via ConsumerAPI
- Use external validation output as evidence for Specification KOs

**The Consumer may NOT:**
- Own reasoning semantics (Thread traversal, conclusion types)
- Create or close Threads directly
- Modify canonical state
- Override tension priority or thread conclusions

**Cognitive Harness may:**
- Read external artifacts as viewpoint input
- Create KOs derived from external validation results

**Cognitive Harness may NOT:**
- Act as a project manager or feature tracker
- Override external validation outcomes

The boundary is the ConsumerAPI. Both sides use it symmetrically: consumers
submit proposals and read conclusions; the harness reads external artifacts and
submits derived knowledge.

### 8.2 External Artifacts as Viewpoint Input (read-only)

An external system can provide structured input mapped to viewpoints:

| External Input | CogHarness Viewpoint | Mapping |
|----------------|---------------------|---------|
| Product vision | Customer | Value direction, success criteria |
| Requirements | Functional | Capabilities, requirement decomposition |
| Schedule | Application | Timeline, dependency context |
| Trade-off analysis | Customer + Conceptual | Trade-off space, prioritization |
| Implementation status | Realization | Implementation state, gaps |
| Validation output | Evidence | Validation results for Specification KOs |

---

## 9. Reference Implementation

### 9.1 Architecture

```
cognitive-harness/
├── model/
│   ├── ko.py               # KO, GateStatus, ScopeDeclaration, SimulationProvenance, FrozenBaseline, SimulationGateReport
│   ├── thread.py           # Thread, ThreadStep (transition metadata), Conclusion, CAFCR
│   ├── tension.py          # Tension types
│   └── proposal.py         # Proposal types (the mutation gateway)
├── analysis/
│   ├── warrant_analyzer.py # WarrantAnalyzer: structural graph analysis, independence analysis
│   └── simulation_gate_policy.py # SimulationGatePolicy: four-gate evaluation (v0.6)
├── storage/
│   ├── interface.py        # StorageInterface contract + dataset ops
│   └── inmemory.py         # InMemoryStorage with deterministic validation rules
├── reasoning/
│   ├── interface.py        # ReasonerInterface contract
│   └── rule_engine.py      # RuleEngineReasoner — CAFCR traversal, LLM-free
├── orchestration/
│   └── engine.py           # Tension queue, proposal pipeline, warrant integration
├── consumer/
│   └── api.py              # ConsumerAPI: read + proposal + warrant + simulation gate queries
├── main.py                 # Complete reasoning trace (9 phases)
├── test_bridge_trace.py    # Bridge cable: legacy v0.4 test (structural KOs needed)
├── test_adversarial_v05.py # Adversarial benchmark: 20 tests, 100% precision/recall
└── test_adversarial.py     # Legacy v0.4.1 keyword-based benchmark (deprecated)
```

### 9.2 Running the Traces

```bash
cd cognitive-harness
python3 main.py                          # Full lifecycle trace (9 phases)
python3 test_adversarial_v05.py          # Adversarial benchmark: 20 tests, 100% P/R
```

**main.py** demonstrates the full lifecycle (9 phases).

- 4 anti-patterns detected via graph structure (calibrated A_pole, tautological energy check, discontinuous inductance, unsupported transfer)
- Conclusion "machine meets performance target" correctly UNWARRANTED

**test_adversarial_v05.py** — adversarial benchmark with structural primitives:
- 20 tests: POS/SUBTLE/NEG for each anti-pattern + structural edge cases
- 15 TP, 5 TN, 0 FP, 0 FN. Precision 100%, Recall 100%.
- Provenance counterfactual test: identical KO text, different graph structure, different warrant

### 9.3 Key Design Properties Verified by Trace

| Property | Verification |
|----------|-------------|
| Knowledge revision, not permanent truth | Phase 7: supersession preserves history |
| LLMs cannot mutate canonical state | Phase 9: rejection with reason |
| Threads are first-class executable objects | Phase 4: CAFCR traversal with questions, evidence, conclusions |
| Knowledge type ≠ truth category ≠ epistemic status | KO has separate `type`, `truth_category`, `epistemic_status` fields |
| Warrant ≠ epistemic status | CANONICAL conclusion can be UNWARRANTED (engineering model example) |
| Anti-patterns are structural diagnoses | v0.5: 0 FP on valid controls, 100% recall on subtle positives |
| Derivation is explicit, not inferred from text | `DerivationRelation` with dataset references |
| Independence is structural, not textual | `Dataset` tracks observation populations; root tracing |
| Provenance counterfactual | Identical KO text, different graph → different warrant |
| Falsifiable validators | Every validation declares what would falsify it |
| Temporal/contextual validity | KOs carry `assumptions`, `scope`, `valid_from/to` |
| Deterministic validation | All transitions validated against `VALID_TRANSITIONS` |
| Succession chains | `get_succession_chain()` returns full history |
| Warrant is structural, not confidence-based | Low confidence + sound provenance = WARRANTED |
| SimulationGatePolicy: four gates | test_simulation_gates: 13 tests, all four gates |
| Provenance without chain -> BLOCK | N-PROV: orphaned result cannot carry design conclusion |
| Scope as warrant boundary | N-SCOPE: component model cannot support system claim |
| Invariant valid for boundary | N-INVARIANT: Cin=Cout invalid for recycle loop with reaction |
| All gates PASS -> design-bearing | N-GATE-ALL: combined verdict |
| Frozen baseline immutable | N-BASELINE-IMMUTABLE: silent mutation detected |
| Harness self-falsification | Self-falsification test: H1 and H2 falsified, correct root cause found |

---

## 10. Design Decisions

### 10.1 Tension-Driven, Not Schedule-Driven

CAFCR demonstrates that architectural reasoning is not phase-linear. Views are traversed iteratively based on where tensions exist.

### 10.2 Proposals, Not Direct Mutation

External agents and consumers submit Proposals. The Orchestration layer validates deterministically. This prevents hallucinated facts, maintains auditability, and ensures agents are consumers of the model, not owners.

### 10.3 Type and Epistemic Status Are Independent

A measurement can be proposed; a decision can be canonical. Collapsing these into a single lifecycle enum was the primary architecture review finding in v0.1.

### 10.4 Supersession Over Deletion

Canonical KOs become SUPERSEDED, not deleted. The succession chain is queryable. This is critical for engineering auditability: you must be able to trace why a previous value was replaced.

---

## 11. Warrant Analysis (v0.4)

### 11.1 The Warrant Problem

A graph can contain a conclusion without warranting it. The engineering model case demonstrated:
- A model can be internally consistent (energy balance holds) while containing calibrated parameters
- A validation can always pass by construction (P_in = P_out + P_loss) without testing anything
- A parameter can be present in monitoring but inert in the causal chain
- A property can be transferred from a different domain without justification

**Reality criterion:** A conclusion is warranted only if every knowledge object that materially carries it has an independently defensible provenance appropriate to its truth category.

### 11.2 Warrant Computation

```
Algorithm (backward traversal):
    1. Start at the Conclusion KO
    2. Collect all KOs that materially carry it (justification path)
    3. For each carrying KO:
        a. Check truth-category-appropriate grounding
        b. Detect anti-patterns
        c. Check independence (not derived from the conclusion being tested)
    4. Determine warrant status:
        - WARRANTED: all premises independently grounded
        - CONDITIONALLY_WARRANTED: warranted except for listed assumptions
        - UNWARRANTED: one or more premises lack independent grounding
        - UNRESOLVED: insufficient information
```

### 11.3 Anti-Patterns

| Pattern | Description | Detection |
|---------|-------------|-----------|
| `CALIBRATED_TO_CONCLUSION` | Parameter set to produce desired result | Parameter chosen to match target, not derived independently |
| `TAUTOLOGICAL_VALIDATION` | Validation always passes by construction | Checks identity (A = A+B-B) rather than independent measurement |
| `INERT_PARAMETER` | Present in monitoring but no causal effect | Not referenced in state equations or causal graph |
| `PHYSICALLY_UNREALIZABLE` | Violates continuity/causality/positivity | Named conservation law or continuity violated |
| `UNSUPPORTED_TRANSFER` | Property transferred from different domain | Sourced from another system, no domain-mapping evidence |
| `CIRCULAR_DEPENDENCY` | Evidence for A depends on B which depends on A | Cycle in justification graph |

### 11.4 Falsifiable Validators

Every validation must declare `what_would_falsify`: the observation that would make it fail. A check that cannot fail cannot increase epistemic confidence.

### 11.5 Warrant and Supersession

When a supporting KO is superseded, the OrchestrationEngine recomputes warrant for all impacted conclusions. If warrant downgrades to UNWARRANTED or CONDITIONALLY_WARRANTED, the conclusion is marked `REVIEW_REQUIRED`.

### 11.6 Consumer API (v0.4)

| Method | Description |
|--------|-------------|
| `api.check_warrant(ko_id)` | Returns warrant status, supporting KOs, anti-patterns, conditions |
| `api.scan_anti_patterns()` | Returns all detected anti-patterns across all KOs |
| `api.justification_path(ko_id)` | Returns all KOs in the justification path |
| `api.list_anti_pattern_hits(pattern)` | Returns KOs flagged with a specific anti-pattern |
| `api.check_simulation_gates(ko_id)` | Returns SimulationGateReport (v0.6). Four-gate evaluation for simulation-bearing claims. |

### 11.7 Adversarial Validation: v0.4.1 → v0.5 Results

**v0.4.1 (keyword-based):** `test_adversarial.py` — 24 tests. 10 TP, 5 TN, 2 FP, 7 FN. Precision 83%, Recall 59%.
**Diagnosis:** Pure keyword matching. Two vocabulary-driven false positives on valid controls.

**v0.5 (structural):** `test_adversarial_v05.py` — 20 tests. 15 TP, 5 TN, 0 FP, 0 FN. Precision 100%, Recall 100%.
**Diagnosis:** Detectors operate on graph structure. Zero vocabulary-driven false positives.

**New model primitives (v0.5):**
- `DerivationType`: explicit classification of HOW a KO was produced (measured, sourced, fitted, modeled, transferred, decided, validated, assumed, combined)
- `DerivationRelation`: typed derivation edge with `upstream_ko_ids`, `training_dataset_id`, `test_dataset_id`, `domain_source_ko_id`, `domain_mapping_ko_id`
- `Dataset`: observation population for independence analysis; tracks `source_ko_id` and `derived_from_dataset_ids`
- `AntiPatternDiagnosis`: structural output with `offending_ko_ids`, `justification_path`, `shared_roots`, `violated_condition`, `resolution_hint`

**New relation types:**
- `FITTED_ON`: KO was fitted/calibrated on this dataset
- `TESTED_AGAINST`: KO was validated against this dataset
- `TRANSFERRED_FROM`: KO is a property transferred from another domain
- `EQUIVALENT_TO`: Domain mapping equivalence claim

**Provenance counterfactual test:**
Identical KO content text across Graph A (three tests sharing one simulation source) and Graph B (three tests from three independent measurements). Graph A: CONDITIONALLY_WARRANTED. Graph B: WARRANTED. Classification differs solely from graph structure.

**Architecture decision (v0.5):** Keyword-based anti-pattern detectors are deprecated. Anti-patterns are now derived diagnoses from graph analysis. Each diagnosis includes the offending KO IDs, justification path, shared provenance roots, violated structural condition, and what additional evidence would resolve the defect.

**Remaining limitation:** `INERT_PARAMETER` detection requires a causal graph (which parameter affects which output). This is a domain-specific concern; the core warrant analyzer does not attempt to build causal graphs. Domain adapters must provide causal relations explicitly.

---

## 12. Integration patterns

### As an MCP server

Cognitive Harness can run as a standalone MCP server over JSON-RPC stdio:

```python
from transports.mcp.server import MCPServer
MCPServer().run()
```

An external agent or tool connects via MCP protocol and calls tools such as
`check_warrant`, `scan_anti_patterns`, `propose_ko`, etc. See the MCP server
in `transports/mcp/server.py` for the complete implementation.

### As a library

Import the package and use `InMemoryStorage` directly, or implement a custom
`StorageInterface` for persistent storage:

```python
from cognitive_harness.storage.inmemory import InMemoryStorage
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer
storage = InMemoryStorage()
wa = WarrantAnalyzer(storage)
```

### Custom storage backends

Implement `StorageInterface` to plug in any persistent graph store. The
reference implementation provides `InMemoryStorage` for testing and
demonstration.

---

## 13. Future Work

- **Tension/Thread persistence:** Serialize to external graph store
- **Domain-specific rule engines:** Thermal, structural, control-system reasoning
- **Causal graph integration:** Enable INERT_PARAMETER detection
- **Multi-agent tension federation:** Cross-agent tension identification
