# FILE: examples/ncm_finetune/evaluate_step4.py
"""Step 4 (Issue #34): Evaluate fine-tuned NCM vs frozen NCM vs Kvasir baseline.

For each held-out fixture:
1. Generate prediction from fine-tuned NCM
2. Generate prediction from frozen NCM (baseline)
3. Run Kvasir (via local LLM call or manual) — stored as reference

Metrics:
  - Label accuracy: established / not_established / beyond_scope
  - Unsupported claims accepted: model says 'established' when ground truth is not
  - Missing premise identified: model names the decisive condition
  - Invented assumption/source: model fabricates evidence

Usage:
    python examples/ncm_finetune/evaluate_step4.py \\
        --fixtures examples/ncm_finetune/ncm_training_fixtures.json \\
        --checkpoint-dir /tmp/ncm-checkpoints/xsum \\
        --finetuned-checkpoint examples/ncm_finetune/finetune_outputs/finetuned_generator.pt \\
        --config /tmp/ncm-source/config/eval/xsum.yaml \\
        --out examples/ncm_finetune/finetune_outputs/step4_results.json
"""
from __future__ import annotations
import argparse
import json
import os
import sys

import torch
from omegaconf import OmegaConf
from transformers import AutoTokenizer

sys.path.insert(0, os.environ.get("NCM_SOURCE_DIR", "/tmp/ncm-source"))
os.environ["NCM_ROOT"] = os.environ.get("NCM_SOURCE_DIR", "/tmp/ncm-source")

from models.next_concept import NextConceptTransformer
from tokenization.vqvae_tokenizer import VQVAETokenizer


def build_prompt(fixture):
    return (
        f"Source excerpt:\n{fixture['source_passage']}\n\n"
        f"Claim:\n{fixture['claim']}\n\n"
        f"Determine whether the source excerpt establishes the claim. "
        f"Answer with one of: established, not_established, beyond_scope. "
        f"Explain your reasoning in one sentence."
    )


def load_model(checkpoint_path, cfg, tk):
    net = NextConceptTransformer(vqvae_local=tk.vqvae, config=cfg.model).cuda()
    sd = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    net.load_state_dict(sd["model"], strict=True)
    net.eval()
    return net


def generate_text(net, tk, prefix_ids, pre_tok, pad_id, eos_id):
    with torch.no_grad():
        g = net.generate(None, prefix_ids, temperature=0.0, top_k=1)
        _, zl = tk.vqvae.vq.idx_to_zhats(g, return_zlevels=True)
        recon_ids = tk.vqvae.decoder(zl[-1]).argmax(-1).squeeze(0).tolist()
        if eos_id in recon_ids:
            recon_ids = recon_ids[: recon_ids.index(eos_id)]
        recon_ids = [t for t in recon_ids if t != pad_id]
    return pre_tok.decode(recon_ids, skip_special_tokens=True)


def extract_label(text, gt_label):
    """Extract label from generated text. Returns (label, matched)."""
    text_lower = text.lower()
    if "not_established" in text_lower or "not established" in text_lower:
        return "not_established", True
    if "beyond_scope" in text_lower:
        return "beyond_scope", True
    if "established" in text_lower:
        return "established", True
    # Partial match
    if text_lower.startswith("not"):
        return "not_established", False
    if text_lower.startswith("estab"):
        return "established", False
    return "unknown", False


def check_missing_preme(text, gt_label, fixture):
    """Check if the model identifies the missing premise or decisive condition."""
    text_lower = text.lower()
    gt_lower = fixture.get("reference_rationale", "").lower()

    signals = [
        "does not prove", "not establish", "not established",
        "missing", "required", "beyond", "not shown", "not proved",
        "uniqueness", "mass gap", "discrepancy", "tolerance",
    ]
    found = [s for s in signals if s in text_lower]
    return len(found) > 0, found


def check_invented_assumption(text, fixture):
    """Check if model invents assumptions or sources not in the source passage."""
    text_lower = text.lower()
    source_lower = fixture.get("source_passage", "").lower()

    # Simple heuristic: check for entities/claims not in source
    # This is approximate — full check needs NER
    invented = False
    reasons = []
    # Check for fabricated numbers
    import re
    text_nums = re.findall(r"\d+\.?\d*", text_lower)
    source_nums = re.findall(r"\d+\.?\d*", source_lower)
    for n in text_nums:
        if n not in source_lower and len(n) > 1:
            invented = True
            reasons.append(f"number '{n}' not in source")
    return invented, reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", required=True)
    ap.add_argument("--checkpoint-dir", default="/tmp/ncm-checkpoints/xsum")
    ap.add_argument("--finetuned-checkpoint", required=True)
    ap.add_argument("--config", default="/tmp/ncm-source/config/eval/xsum.yaml")
    ap.add_argument("--out", default="step4_results.json")
    args = ap.parse_args()

    cfg = OmegaConf.load(args.config)
    cfg.tokenizer.vqvae.checkpoint_path = os.path.join(
        args.checkpoint_dir, cfg.checkpoints.tokenizer
    )

    tk = VQVAETokenizer.from_config(cfg.tokenizer)
    tk.vqvae = tk.vqvae.cuda().eval()
    for p in tk.vqvae.parameters():
        p.requires_grad = False

    # Load both models
    frozen_path = os.path.join(args.checkpoint_dir, cfg.checkpoints.generator)
    frozen_net = load_model(frozen_path, cfg, tk)
    finetuned_net = load_model(args.finetuned_checkpoint, cfg, tk)

    pre_tok = AutoTokenizer.from_pretrained("gpt2")
    PAD_ID = 50257
    EOS_ID = pre_tok.eos_token_id
    prefix_len = cfg.model.prefix_len

    with open(args.fixtures) as f:
        fixtures = json.load(f)

    print(f"Evaluating {len(fixtures)} fixtures")
    print("=" * 70)

    results = []
    n_unsupported_accepted = {"frozen": 0, "finetuned": 0, "kvasir": 0}
    n_missing_preme_found = {"frozen": 0, "finetuned": 0, "kvasir": 0}
    n_invented = {"frozen": 0, "finetuned": 0, "kvasir": 0}
    n_label_correct = {"frozen": 0, "finetuned": 0, "kvasir": 0}

    for idx, fx in enumerate(fixtures):
        gt_label = fx["label"]
        prompt = build_prompt(fx)

        # Encode prefix
        prefix_ids = pre_tok(prompt, return_tensors="pt")["input_ids"].cuda()
        if prefix_ids.shape[1] < prefix_len:
            prefix_ids = torch.nn.functional.pad(
                prefix_ids, (0, prefix_len - prefix_ids.shape[1]), value=PAD_ID
            )
        else:
            prefix_ids = prefix_ids[:, :prefix_len]

        # Generate from both models
        frozen_text = generate_text(frozen_net, tk, prefix_ids, pre_tok, PAD_ID, EOS_ID)
        finetuned_text = generate_text(finetuned_net, tk, prefix_ids, pre_tok, PAD_ID, EOS_ID)

        # Extract labels
        frozen_label, frozen_match = extract_label(frozen_text, gt_label)
        finetuned_label, finetuned_match = extract_label(finetuned_text, gt_label)

        # Check metrics
        frozen_invented, frozen_inv_reasons = check_invented_assumption(frozen_text, fx)
        finetuned_invented, finetuned_inv_reasons = check_invented_assumption(
            finetuned_text, fx
        )

        frozen_preme, frozen_preme_signals = check_missing_preme(
            frozen_text, gt_label, fx
        )
        finetuned_preme, finetuned_preme_signals = check_missing_preme(
            finetuned_text, gt_label, fx
        )

        # Count metrics
        if gt_label in ("not_established", "beyond_scope") and frozen_label == "established":
            n_unsupported_accepted["frozen"] += 1
        if gt_label in ("not_established", "beyond_scope") and finetuned_label == "established":
            n_unsupported_accepted["finetuned"] += 1

        if gt_label in ("not_established", "beyond_scope"):
            if frozen_preme:
                n_missing_preme_found["frozen"] += 1
            if finetuned_preme:
                n_missing_preme_found["finetuned"] += 1

        if frozen_invented:
            n_invented["frozen"] += 1
        if finetuned_invented:
            n_invented["finetuned"] += 1

        if frozen_label == gt_label:
            n_label_correct["frozen"] += 1
        if finetuned_label == gt_label:
            n_label_correct["finetuned"] += 1

        results.append(
            {
                "fixture_idx": idx,
                "gt_label": gt_label,
                "frozen": {
                    "text": frozen_text,
                    "label": frozen_label,
                    "label_matched": frozen_match,
                    "missing_preme_found": frozen_preme,
                    "preme_signals": frozen_preme_signals,
                    "invented_assumption": frozen_invented,
                    "invented_reasons": frozen_inv_reasons,
                },
                "finetuned": {
                    "text": finetuned_text,
                    "label": finetuned_label,
                    "label_matched": finetuned_match,
                    "missing_preme_found": finetuned_preme,
                    "preme_signals": finetuned_preme_signals,
                    "invented_assumption": finetuned_invented,
                    "invented_reasons": finetuned_inv_reasons,
                },
            }
        )

        print(f"\nFixture {idx} (gt={gt_label}):")
        print(f"  Frozen    → [{frozen_label}] {frozen_text[:80]}...")
        print(f"  Finetuned → [{finetuned_label}] {finetuned_text[:80]}...")

    # Summary
    total = len(fixtures)
    summary = {
        "total_fixtures": total,
        "label_accuracy": {
            "frozen": f"{n_label_correct['frozen']}/{total}",
            "finetuned": f"{n_label_correct['finetuned']}/{total}",
        },
        "unsupported_claims_accepted": {
            "frozen": n_unsupported_accepted["frozen"],
            "finetuned": n_unsupported_accepted["finetuned"],
        },
        "missing_preme_identified": {
            "frozen": n_missing_preme_found["frozen"],
            "finetuned": n_missing_preme_found["finetuned"],
        },
        "invented_assumptions": {
            "frozen": n_invented["frozen"],
            "finetuned": n_invented["finetuned"],
        },
    }

    output = {"summary": summary, "per_fixture": results}
    with open(args.out, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n{'=' * 70}")
    print(f"SUMMARY ({total} fixtures):")
    print(f"  Label accuracy:     frozen={summary['label_accuracy']['frozen']}, "
          f"finetuned={summary['label_accuracy']['finetuned']}")
    print(f"  Unsupported claims: frozen={summary['unsupported_claims_accepted']['frozen']}, "
          f"finetuned={summary['unsupported_claims_accepted']['finetuned']}")
    print(f"  Missing premise:    frozen={summary['missing_preme_identified']['frozen']}, "
          f"finetuned={summary['missing_preme_identified']['finetuned']}")
    print(f"  Invented:           frozen={summary['invented_assumptions']['frozen']}, "
          f"finetuned={summary['invented_assumptions']['finetuned']}")
    print(f"\nResults → {args.out}")


if __name__ == "__main__":
    main()
