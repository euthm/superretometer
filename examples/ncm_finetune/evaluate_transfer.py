# FILE: examples/ncm_finetune/evaluate_transfer.py
"""Step 4 continued: Transfer evaluation on held-out fixtures.

New fixtures from the same source family (yang-mills-committee) but with
claims NOT seen during training. Plus the private NIBIO case.
"""
import json
import os

# Held-out Yang-Mills fixtures (same source, new claims)
YANG_MILLS_HELD_OUT = [
    {
        "source_url": "https://github.com/yang-mills-group/YM",
        "source_passage": (
            "In our opinion, this submission proves that a relativistic quantum field "
            "theory satisfying the Wightman axioms can be constructed as a scaling limit "
            "of four-dimensional Wilson lattice gauge theory for any simple compact gauge "
            "group. It does not prove that the infinite-volume limit is unique or that "
            "there is a mass gap."
        ),
        "source_family": "yang-mills-committee",
        "claim": (
            "The October 2026 submission proves that Yang-Mills theory exists for SO(8) "
            "lattice gauge theory via scaling limit construction."
        ),
        "label": "established",
        "reference_rationale": (
            "SO(8) is a simple compact gauge group, covered by 'any simple compact "
            "gauge group' in the assessment."
        ),
    },
    {
        "source_url": "https://github.com/yang-mills-group/YM",
        "source_passage": (
            "In our opinion, this submission proves that a relativistic quantum field "
            "theory satisfying the Wightman axioms can be constructed as a scaling limit "
            "of four-dimensional Wilson lattice gauge theory for any simple compact gauge "
            "group. It does not prove that the infinite-volume limit is unique or that "
            "there is a mass gap."
        ),
        "source_family": "yang-mills-committee",
        "claim": (
            "The October 2026 submission proves the theory satisfies cluster "
            "factorization and asymptotic completeness."
        ),
        "label": "beyond_scope",
        "reference_rationale": (
            "The assessment mentions Wightman axioms generally but does not specifically "
            "address cluster factorization or asymptotic completeness as verified properties."
        ),
    },
    {
        "source_url": "https://github.com/yang-mills-group/YM",
        "source_passage": (
            "In our opinion, this submission proves that a relativistic quantum field "
            "theory satisfying the Wightman axioms can be constructed as a scaling limit "
            "of four-dimensional Wilson lattice gauge theory for any simple compact gauge "
            "group. It does not prove that the infinite-volume limit is unique or that "
            "there is a mass gap."
        ),
        "source_family": "yang-mills-committee",
        "claim": (
            "The October 2026 submission proves that no mass gap exists in the "
            "constructed Yang-Mills theory."
        ),
        "label": "not_established",
        "reference_rationale": (
            "The assessment says it does not prove there IS a mass gap — this is different "
            "from proving there is NO mass gap. Absence of proof is not proof of absence."
        ),
    },
    {
        "source_url": "https://github.com/yang-mills-group/YM",
        "source_passage": (
            "In our opinion, this submission proves that a relativistic quantum field "
            "theory satisfying the Wightman axioms can be constructed as a scaling limit "
            "of four-dimensional Wilson lattice gauge theory for any simple compact gauge "
            "group. It does not prove that the infinite-volume limit is unique or that "
            "there is a mass gap."
        ),
        "source_family": "yang-mills-committee",
        "claim": (
            "The October 2026 submission is applicable to U(1) electromagnetism."
        ),
        "label": "beyond_scope",
        "reference_rationale": (
            "U(1) is abelian, not a simple compact gauge group. The assessment specifically "
            "covers simple compact groups like SU(N), not abelian U(1)."
        ),
    },
]

# NIBIO case — kept private, evaluated locally only
NIBIO_FIXTURE = {
    "source_url": "private",
    "source_passage": (
        "Simuleringsrapport V9 p.8: The numerical model reproduces measured yields "
        "with a mean deviation of 0.032 t/ha over 1344 data points. "
        "The deviation is within acceptable tolerances for "
        "the calibration period 2019–2023."
    ),
    "source_family": "nibio-yield",
    "claim": (
        "The numerical model reliably predicts crop yields outside the "
        "2019–2023 calibration period."
    ),
    "label": "beyond_scope",
    "reference_rationale": (
        "The source only covers the calibration period 2019–2023. Extrapolation "
        "beyond this period is not supported by the evidence."
    ),
}


def main():
    fixtures = YANG_MILLS_HELD_OUT + [NIBIO_FIXTURE]

    out_dir = "examples/ncm_finetune/finetune_outputs"
    out_path = os.path.join(out_dir, "held_out_fixtures.json")
    os.makedirs(out_dir, exist_ok=True)

    with open(out_path, "w") as f:
        json.dump(fixtures, f, indent=2)

    print(f"Saved {len(fixtures)} held-out fixtures to {out_path}")
    for i, fx in enumerate(fixtures):
        print(f"  [{i}] {fx['label']}: {fx['claim'][:60]}...")


if __name__ == "__main__":
    main()
