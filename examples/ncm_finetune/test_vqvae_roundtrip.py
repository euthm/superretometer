# FILE: examples/ncm_finetune/test_vqvae_roundtrip.py
"""Step 2 (Issue #34): Test XSum VQVAE tokenizer round-trip.

Round-trip 10 short reference answers through the released XSum
tokenizer and decoder. Check that polarity, quantities, signs and
conditions survive. If a decisive fact changes, the pair is flagged.

This test must pass (or be understood) before spending GPU time on
fine-tuning, because a decoder that cannot reconstruct the target
cannot be trained to produce it.

Usage:
    python examples/ncm_finetune/test_vqvae_roundtrip.py
"""
from __future__ import annotations
import json
import os
import re
import sys
from pathlib import Path

import torch
from omegaconf import OmegaConf

sys.path.insert(0, os.environ.get("NCM_SOURCE_DIR", "/tmp/ncm-source"))
os.environ["NCM_ROOT"] = os.environ.get("NCM_SOURCE_DIR", "/tmp/ncm-source")

from tokenization.vqvae_tokenizer import VQVAETokenizer
from transformers import AutoTokenizer

CHECKPOINT_DIR = os.environ.get("NCM_CHECKPOINT_DIR", "/tmp/ncm-checkpoints/xsum")


# Reference answers with decisive facts that must survive round-trip
ANSWERS = [
    ("positive_claim", "The evidence supports the claim within the stated assumptions and boundary conditions."),
    ("negative_claim", "The source does not establish the claim because no independent measurement is available."),
    ("quantitative", "The maximum deviation is 0.032 across 1344 compared points in steady state."),
    ("conditional", "The result holds only when the boundary condition is met and the parameter is within range."),
    ("not_established", "The mass gap is not established by this source; the construction proves existence only."),
    ("polarity_flip", "The measurement contradicts the hypothesis and points to the opposite conclusion."),
    ("missing_premise", "Independent validation of the yield model is required before the claim can be accepted."),
    ("sign_change", "The thermal gradient is negative, not positive, which changes the safety assessment."),
    ("scope_limited", "The construction proves existence of the solution but not uniqueness or stability."),
    ("two_conditions", "Both temperature control and pressure monitoring must be satisfied for the result to hold."),
]


def main():
    cfg = OmegaConf.load(os.path.join(CHECKPOINT_DIR, "config.yaml"))
    cfg.tokenizer.vqvae.checkpoint_path = os.path.join(CHECKPOINT_DIR, "tokenizer.pt")

    tk = VQVAETokenizer.from_config(cfg.tokenizer)
    tk.vqvae = tk.vqvae.cuda().eval()
    pre_tok = AutoTokenizer.from_pretrained("gpt2")

    ctx_len = cfg.tokenizer.vqvae.context_length
    PAD_ID = 50257

    results = []
    for label, text in ANSWERS:
        input_ids = pre_tok(text, return_tensors="pt")["input_ids"]
        padded = torch.nn.functional.pad(
            input_ids, (0, ctx_len - input_ids.shape[1]), value=PAD_ID
        ).cuda()

        with torch.no_grad():
            z_enc = tk.vqvae.encoder(padded)
            vq_out = tk.vqvae.vq(z_enc)
            z_q = vq_out[0]
            reconstructed = tk.vqvae.decoder(z_q)

        recon_ids = reconstructed.argmax(-1).squeeze(0).tolist()
        EOS = pre_tok.eos_token_id
        if EOS in recon_ids:
            recon_ids = recon_ids[:recon_ids.index(EOS)]
        recon_ids = [t for t in recon_ids if t != PAD_ID]
        recon_text = pre_tok.decode(recon_ids, skip_special_tokens=True)

        orig_words = set(text.lower().replace(".", "").replace(",", "").split())
        recon_words = set(recon_text.lower().replace(".", "").replace(",", "").split())
        overlap = len(orig_words & recon_words) / len(orig_words) if orig_words else 0

        # Check decisive facts
        errors = []
        if "not" in text.lower() and "not" not in recon_text.lower():
            errors.append("polarity_flip: 'not' lost")
        if "negative" in text.lower() and "negative" not in recon_text.lower():
            errors.append("sign_lost: 'negative' missing")
        if "contradict" in text.lower() and "contradict" not in recon_text.lower():
            errors.append("polarity_lost: 'contradict' missing")
        for n in re.findall(r"\d+\.?\d*", text):
            if n not in recon_text:
                errors.append(f"quantity_lost: '{n}'")

        results.append({
            "label": label,
            "original": text,
            "reconstructed": recon_text,
            "word_overlap": round(overlap, 3),
            "facts_ok": len(errors) == 0,
            "errors": errors,
        })

    # Summary
    avg_overlap = sum(r["word_overlap"] for r in results) / len(results)
    facts_ok = sum(1 for r in results if r["facts_ok"])
    failing = [r["label"] for r in results if not r["facts_ok"]]

    summary = {
        "test": "vqvae_roundtrip",
        "n_samples": len(results),
        "avg_word_overlap": round(avg_overlap, 3),
        "facts_preserved": f"{facts_ok}/{len(results)}",
        "failing_pairs": failing,
        "results": results,
    }

    output = Path("vqvae_roundtrip_results.json")
    output.write_text(json.dumps(summary, indent=2) + "\n")

    print(json.dumps(summary, indent=2))
    print(f"\nFailing pairs: {failing if failing else 'NONE'}")
    print(f"Result saved to: {output}")

    return 1 if failing else 0


if __name__ == "__main__":
    raise SystemExit(main())
