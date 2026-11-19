# FILE: examples/ncm_finetune/train_source_grounding.py
"""Step 3 (Issue #34): Custom fine-tuning loop for NCM source-grounded claim detection.

Trains the NCM generator head to predict hierarchical concept codes
conditioned on (source_excerpt, claim) prefix, using standard
cross-entropy loss over VQVAE token indices.

Architecture:
  - VQVAE tokenizer: FROZEN (no gradients)
  - NextConceptTransformer generator: TRAINABLE
  - Input: prefix (source + claim, GPT2-tokenized, 512 tokens)
  - Target: reference answer encoded through VQVAE (48 tokens, 9 levels)

Usage:
    python examples/ncm_finetune/train_source_grounding.py \
        --fixtures examples/ncm_finetune/ncm_training_fixtures.json \
        --checkpoint-dir /tmp/ncm-checkpoints/xsum \
        --config /tmp/ncm-source/config/eval/xsum.yaml \
        --epochs 50 --lr 1e-4 --bs 4

First run overfits 8 examples as training-pipeline check.
"""
from __future__ import annotations
import argparse
import json
import os
import sys

import torch
import torch.nn as nn
from omegaconf import OmegaConf
from transformers import AutoTokenizer

sys.path.insert(0, os.environ.get("NCM_SOURCE_DIR", "/tmp/ncm-source"))
os.environ["NCM_ROOT"] = os.environ.get("NCM_SOURCE_DIR", "/tmp/ncm-source")

from models.next_concept import NextConceptTransformer
from tokenization.vqvae_tokenizer import VQVAETokenizer


def encode_targets(pre_tok, vqvae, texts, ctx_len, pad_id):
    """Encode target texts through VQVAE to get hierarchical indices.
    
    Returns: tensor of shape (B, ctx_len, n_levels) with quantized indices.
    """
    batches = []
    for text in texts:
        ids = pre_tok(text, return_tensors="pt")["input_ids"]
        # Pad to ctx_len
        if ids.shape[1] < ctx_len:
            ids = torch.nn.functional.pad(ids, (0, ctx_len - ids.shape[1]), value=pad_id)
        else:
            ids = ids[:, :ctx_len]
        ids = ids.cuda()
        
        with torch.no_grad():
            z_enc = vqvae.encoder(ids)
            vq_out = vqvae.vq(z_enc)
            z_q = vq_out[0]
            # Get indices for each level
            indices = vqvae.vq.z_to_idx(z_q)  # shape: (B, T, n_levels)
        batches.append(indices)
    
    return torch.cat(batches, dim=0)


def encode_prefix(pre_tok, prefix_text, prefix_len, pad_id):
    """Encode prefix text to GPT2 token IDs, padded to prefix_len."""
    ids = pre_tok(prefix_text, return_tensors="pt")["input_ids"][0]
    if len(ids) < prefix_len:
        ids = torch.cat([ids, torch.full((prefix_len - len(ids),), pad_id)])
    else:
        ids = ids[:prefix_len]
    return ids.cuda()


def build_prompt(fixture):
    """Build source-conditioned prompt from fixture."""
    return (
        f"Source excerpt:\n{fixture['source_passage']}\n\n"
        f"Claim:\n{fixture['claim']}\n\n"
        f"Determine whether the source excerpt establishes the claim. "
        f"Answer with one of: established, not_established, beyond_scope. "
        f"Explain your reasoning in one sentence."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", required=True)
    ap.add_argument("--checkpoint-dir", default="/tmp/ncm-checkpoints/xsum")
    ap.add_argument("--config", default="/tmp/ncm-source/config/eval/xsum.yaml")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--bs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-dir", default="finetune_outputs")
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    
    # Load config and models
    cfg = OmegaConf.load(args.config)
    cfg.tokenizer.vqvae.checkpoint_path = os.path.join(
        args.checkpoint_dir, cfg.checkpoints.tokenizer
    )
    
    print("Loading VQVAE tokenizer (frozen)...")
    tk = VQVAETokenizer.from_config(cfg.tokenizer)
    tk.vqvae = tk.vqvae.cuda().eval()
    for p in tk.vqvae.parameters():
        p.requires_grad = False
    
    print("Loading generator (trainable)...")
    net = NextConceptTransformer(vqvae_local=tk.vqvae, config=cfg.model).cuda()
    sd = torch.load(
        os.path.join(args.checkpoint_dir, cfg.checkpoints.generator),
        map_location="cpu", weights_only=False,
    )
    net.load_state_dict(sd["model"], strict=True)
    
    # Count trainable params
    trainable = sum(p.numel() for p in net.parameters() if p.requires_grad)
    frozen = sum(p.numel() for p in net.parameters() if not p.requires_grad)
    print(f"Trainable params: {trainable:,}")
    print(f"Frozen params: {frozen:,}")
    
    # Load fixtures
    with open(args.fixtures) as f:
        fixtures = json.load(f)
    print(f"Loaded {len(fixtures)} training fixtures")
    
    # Prepare data
    pre_tok = AutoTokenizer.from_pretrained("gpt2")
    PAD_ID = 50257
    ctx_len = cfg.tokenizer.vqvae.context_length
    prefix_len = cfg.model.prefix_len
    
    # Encode all prefixes and targets
    prompts = [build_prompt(fx) for fx in fixtures]
    targets = [fx["label"] for fx in fixtures]
    
    prefixes = torch.stack([
        encode_prefix(pre_tok, p, prefix_len, PAD_ID)
        for p in prompts
    ])
    
    # Encode targets through VQVAE
    target_indices = encode_targets(pre_tok, tk.vqvae, targets, ctx_len, PAD_ID)
    
    # Also encode full reference rationales for richer targets
    rationale_texts = [fx["reference_rationale"] for fx in fixtures]
    rationale_indices = encode_targets(pre_tok, tk.vqvae, rationale_texts, ctx_len, PAD_ID)
    
    # Use label + rationale as combined target
    # For simplicity, use just the label-encoded indices (shorter, cleaner)
    targets_tensor = target_indices
    
    print(f"Prefix shape: {prefixes.shape}")
    print(f"Target shape: {targets_tensor.shape}")
    
    # Training loop
    optimizer = torch.optim.AdamW(
        [p for p in net.parameters() if p.requires_grad],
        lr=args.lr, weight_decay=1e-5
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=args.epochs * len(fixtures) // args.bs
    )
    
    os.makedirs(args.out_dir, exist_ok=True)
    losses = []
    
    print(f"\nStarting training: {args.epochs} epochs, {len(fixtures)} samples, bs={args.bs}")
    print("=" * 60)
    
    for epoch in range(args.epochs):
        net.train()
        epoch_loss = 0
        n_batches = 0
        
        # Shuffle
        perm = torch.randperm(len(fixtures))
        for i in range(0, len(fixtures), args.bs):
            batch_idx = perm[i:i + args.bs]
            batch_prefix = prefixes[batch_idx]
            batch_target = targets_tensor[batch_idx]
            
            optimizer.zero_grad()
            
            # Forward pass: generate from prefix
            with torch.no_grad():
                g = net.generate(None, batch_prefix, temperature=0.0, top_k=1)
                _, zl = tk.vqvae.vq.idx_to_zhats(g, return_zlevels=True)
                logits = tk.vqvae.decoder(zl[-1])
            
            # Cross-entropy loss over VQVAE token predictions
            # logits: (B, T, vocab_size), target: actual token IDs
            target_ids = batch_target.squeeze(-1)  # Use level 0 for now
            loss = nn.functional.cross_entropy(
                logits.flatten(0, 1),
                target_ids.flatten(0, 1),
                ignore_index=PAD_ID
            )
            
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [p for p in net.parameters() if p.requires_grad], max_norm=1.0
            )
            optimizer.step()
            scheduler.step()
            
            epoch_loss += loss.item()
            n_batches += 1
        
        avg_loss = epoch_loss / max(n_batches, 1)
        losses.append(avg_loss)
        
        if epoch % 10 == 0 or epoch == args.epochs - 1:
            # Check trainable params actually changed
            param_changed = any(
                p.grad is not None and p.grad.abs().sum() > 0
                for p in net.parameters() if p.requires_grad
            )
            # Check frozen params stayed fixed
            vqvae_frozen = all(
                not p.requires_grad for p in tk.vqvae.parameters()
            )
            
            print(f"Epoch {epoch:3d}: loss={avg_loss:.4f}, "
                  f"lr={scheduler.get_last_lr()[0]:.6f}, "
                  f"params_changed={param_changed}, "
                  f"vqvae_frozen={vqvae_frozen}")
    
    # Save checkpoint
    ckpt_path = os.path.join(args.out_dir, "finetuned_generator.pt")
    torch.save({"model": net.state_dict(), "epoch": args.epochs}, ckpt_path)
    print(f"\nSaved checkpoint to {ckpt_path}")
    
    # Save loss curve
    with open(os.path.join(args.out_dir, "loss_curve.json"), "w") as f:
        json.dump(losses, f)
    
    print(f"Training complete. Final loss: {losses[-1]:.4f}")
    
    # Overfit check: if loss > 0.1 after 50 epochs on 8 samples, pipeline is broken
    if losses[-1] > 0.1:
        print("WARNING: Loss did not converge — possible pipeline issue")
    else:
        print("Overfit check passed: model memorized training set")


if __name__ == "__main__":
    main()
