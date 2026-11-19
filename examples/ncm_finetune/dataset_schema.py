# FILE: examples/ncm_finetune/dataset_schema.py
"""Step 1 (Issue #34): Dataset schema and public fixtures for NCM fine-tuning.

Each training example is a (source_excerpt, claim, label, rationale) tuple.
Labels: 'established', 'not_established', 'beyond_scope'.

Split by whole source family before producing variants.
Reserve separate public families for evaluation.
Keep private evaluations and their outputs outside the public repository.
"""
from __future__ import annotations

DATA_SCHEMA = {
    "source_url": "str — URL to published source",
    "source_revision": "str — revision/date/hash",
    "source_passage": "str — precise passage (truncated if too long)",
    "source_license": "str — reuse license",
    "source_family": "str — family identifier for split isolation",
    "theorem_family": "str — theorem/article family (optional)",
    "claim": "str — proposed claim about the passage",
    "label": "str — 'established', 'not_established', or 'beyond_scope'",
    "reference_rationale": "str — short rationale for label, checked against passage",
    "reviewed_by": "str — who reviewed; mark 'pending' if awaiting human review",
}


# =============================================================================
# PUBLIC FIXTURES — Yang-Mills Committee Assessment 1
# Source: https://github.com/yang-mills-group/YM (docs/assessment-1.pdf)
# Licensed: Apache-2.0
# =============================================================================

YANG_MILLS_ASSESSMENT_1 = {
    "source_url": "https://github.com/yang-mills-group/YM/blob/main/docs/assessment-1.pdf",
    "source_revision": "2026-11-10",
    "source_passage": (
        "In our opinion, this submission proves that a relativistic quantum field "
        "theory satisfying the Wightman axioms can be constructed as a scaling limit "
        "of four-dimensional Wilson lattice gauge theory for any simple compact gauge "
        "group. It does not prove that the infinite-volume limit is unique or that "
        "there is a mass gap."
    ),
    "source_license": "Apache-2.0",
    "source_family": "yang-mills-committee",
    "theorem_family": "YM-4D-existence",
}

# Claim pairs about the same passage: one supported, one beyond scope
YANG_MILLS_FIXTURES = [
    {
        **YANG_MILLS_ASSESSMENT_1,
        "claim": (
            "The October 2026 submission proves that a relativistic QFT satisfying "
            "the Wightman axioms can be constructed as a scaling limit of 4D Wilson "
            "lattice gauge theory for any simple compact gauge group."
        ),
        "label": "established",
        "reference_rationale": (
            "Directly matches the assessment's first sentence: 'this submission proves "
            "that a relativistic quantum field theory satisfying the Wightman axioms "
            "can be constructed as a scaling limit of four-dimensional Wilson lattice "
            "gauge theory for any simple compact gauge group.'"
        ),
        "reviewed_by": "Kvasir (AI1)",
    },
    {
        **YANG_MILLS_ASSESSMENT_1,
        "claim": (
            "The October 2026 submission proves that the infinite-volume limit is "
            "unique for the constructed Yang-Mills theory."
        ),
        "label": "not_established",
        "reference_rationale": (
            "Assessment explicitly states: 'It does not prove that the infinite-volume "
            "limit is unique.' The claim goes beyond what the source establishes."
        ),
        "reviewed_by": "Kvasir (AI1)",
    },
    {
        **YANG_MILLS_ASSESSMENT_1,
        "claim": (
            "The October 2026 submission proves the existence of a mass gap in the "
            "constructed Yang-Mills theory."
        ),
        "label": "not_established",
        "reference_rationale": (
            "Assessment explicitly states: 'It does not prove ... that there is a "
            "mass gap.' Mass gap remains an open question per this source."
        ),
        "reviewed_by": "Kvasir (AI1)",
    },
    {
        **YANG_MILLS_ASSESSMENT_1,
        "claim": (
            "The October 2026 submission establishes existence of a QFT for SU(2) "
            "lattice gauge theory via scaling limit construction."
        ),
        "label": "established",
        "reference_rationale": (
            "SU(2) is a simple compact gauge group. The assessment covers 'any simple "
            "compact gauge group', which includes SU(2). The claim is within scope."
        ),
        "reviewed_by": "Kvasir (AI1)",
    },
    {
        **YANG_MILLS_ASSESSMENT_1,
        "claim": (
            "The October 2026 submission proves that Yang-Mills theory is the unique "
            "QFT satisfying the Wightman axioms in 4D."
        ),
        "label": "beyond_scope",
        "reference_rationale": (
            "The assessment addresses construction of one QFT, not uniqueness among "
            "all possible QFTs. The source says nothing about uniqueness of the theory "
            "itself, only about the infinite-volume limit."
        ),
        "reviewed_by": "Kvasir (AI1)",
    },
]


# =============================================================================
# PUBLIC FIXTURES — Modelica/IO vault loss coefficients (from superretometer graph)
# Source: cognitive_harness/examples/vault_loss_coefficients.md
# =============================================================================

IO_VAULT_FIXTURES = [
    {
        "source_url": "file:///home/egiuth/euthm/superretometer/cognitive_harness/examples/vault_loss_coefficients.md",
        "source_revision": "2026-10-03",
        "source_passage": (
            "At 900 °C, the vault-side calculation gives 0.551 W/K, while "
            "io.vault_loss gives 0.497 W/K. The discrepancy is 9.6%, not the "
            "3% residual tolerance used elsewhere."
        ),
        "source_license": "project-local",
        "source_family": "io-vault-loss",
        "claim": (
            "At 900 °C, the vault-side loss coefficient exceeds the io.vault_loss "
            "value by approximately 10%."
        ),
        "label": "established",
        "reference_rationale": (
            "Source states 9.6% discrepancy, which is 'approximately 10%'. "
            "0.551 > 0.497 confirms vault-side exceeds io value."
        ),
        "reviewed_by": "Kvasir (AI1)",
    },
    {
        "source_url": "file:///home/egiuth/euthm/superretometer/cognitive_harness/examples/vault_loss_coefficients.md",
        "source_revision": "2026-10-03",
        "source_passage": (
            "At 900 °C, the vault-side calculation gives 0.551 W/K, while "
            "io.vault_loss gives 0.497 W/K. The discrepancy is 9.6%, not the "
            "3% residual tolerance used elsewhere."
        ),
        "source_license": "project-local",
        "source_family": "io-vault-loss",
        "claim": (
            "At 900 °C, the vault-side and io.vault_loss calculations agree "
            "within the 3% residual tolerance."
        ),
        "label": "not_established",
        "reference_rationale": (
            "Source explicitly states the discrepancy is 9.6%, 'not the 3% "
            "residual tolerance used elsewhere.' The claim contradicts the source."
        ),
        "reviewed_by": "Kvasir (AI1)",
    },
]

ALL_PUBLIC_FIXTURES = YANG_MILLS_FIXTURES + IO_VAULT_FIXTURES


def save_fixtures(path: str = "ncm_training_fixtures.json"):
    import json
    with open(path, "w") as f:
        json.dump(ALL_PUBLIC_FIXTURES, f, indent=2)
    print(f"Saved {len(ALL_PUBLIC_FIXTURES)} fixtures to {path}")


if __name__ == "__main__":
    save_fixtures()
