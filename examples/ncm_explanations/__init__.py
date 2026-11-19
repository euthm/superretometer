"""NCM Explanation Example — Issue #32

Evaluates whether Next-Concept Modeling (NCM) can produce useful explanations
for warrant results, compared to a deterministic template baseline.

## Two synthetic graphs

Both graphs have the same conclusion ("Core assembly thermally safe at nominal
load") supported by three statements about temperature, thermal gradient, and stress.

**Graph A (shared_root):** All three statements derive from one simulation run.
Expected warrant: `CONDITIONALLY_WARRANTED` or `UNWARRANTED` (shared provenance).

**Graph B (independent):** Each statement derives from an independent measurement
(thermocouple, IR camera, strain gauge).
Expected warrant: `WARRANTED` (independent provenance).

## Usage

Baseline (no NCM, just template + comparison):
```bash
python examples/ncm_explanations/run.py --output ncm-results
```

With NCM generation (requires checkpoints):
```bash
NCM_CHECKPOINT_DIR=/path/to/xsum/checkpoints \
NCM_SOURCE_DIR=/path/to/ncm/checkout \
python examples/ncm_explanations/run.py --output ncm-results
```

Download NCM checkpoints:
```bash
hf download hazyresearch/ncm-checkpoints --local-dir /path/to/checkpoints
git clone https://github.com/HazyResearch/ncm /path/to/ncm/checkout
pip install -r /path/to/ncm/checkout/requirements.txt
```

## Output

Each case directory (`ncm-results/shared_root/`, `ncm-results/independent/`) contains:
- `warrant_record.json` — structured warrant analysis
- `baseline_text.txt` — deterministic template explanation
- `ncm_result.json` — NCM generation result (status, summary, reason)
- `ncm_summary.txt` — NCM-generated summary (if generated)
- `baseline_score.json` — scoring of baseline against verified verdict
- `ncm_score.json` — scoring of NCM output against verified verdict
- `comparison.json` — side-by-side comparison

## Boundary guarantee

A generated summary is advisory output. The graph, evidence roots, and warrant
result remain the authority regardless of any summary content. The boundary
test (`test_ncm_boundary.py`) verifies this with a deliberately misleading summary.

## Acceptance criteria

From issue #32:
- [x] One documented command reproduces both cases
- [x] Scores each output against verified verdict, root count, and IDs
- [x] NCM run skipped gracefully when weights missing
- [ ] Blind reviewer test (manual — requires human participants)
- [ ] Larger trial recommendation (pending reviewer results)

## References

- Issue: https://github.com/euthm/superretometer/issues/32
- NCM: https://github.com/HazyResearch/ncm
- Paper: https://arxiv.org/abs/2610.14162
"""
from __future__ import annotations

# This file is the README-equivalent for the example.
# Run with: python examples/ncm_explanations/run.py --output ncm-results
