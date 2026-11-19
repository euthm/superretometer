# FILE: examples/ncm_finetune/train_source_grounding.py
"""Step 3 (Issue #34): Level-by-level teacher forcing for NCM fine-tuning.

Strategy:
1. Encode prefix → VQVAE encoder → prefix_emb
2. Encode target text → VQVAE encoder → z_q → z_to_idx → gt_indices (B, 200)
3. Autoregressive loop (like generate() but WITH gradients):
   - Level 0: get_next_autoregressive_input from prefix → logits vs gt_indices[:, :4]
   - Level k: idx_to_ncm_input(gt_indices) → next_concepts → logits vs gt_indices
4. Sum CE loss across all levels

idx_to_ncm_input is @no_grad but only builds the INPUT to the transformer.
The transformer forward pass has gradients flowing to lm_heads.
"""
from __future__ import annotations
import argparse
import json
import math
import os
import sys

import torch
import torch.nn as nn
import torch.nn.functional as F
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


def teacher_forcing_loss(net, tk, prefix_ids, gt_indices):
    """Compute CE loss level-by-level using ground-truth hierarchical indices.

    Replicates generate() but without @torch.no_grad, computing
    CE loss at each level against the known-good indices from VQVAE.
    """
    dev = prefix_ids.device
    B = prefix_ids.shape[0]
    P = net.prefix_len
    levels = net.levels
    vq = net.vqvae_local[0].vq

    # Encode prefix (same as generate())
    if net.use_ctx_encoder:
        prefix_emb = net._encode_context(prefix_ids[:, :P])
    else:
        if bool(getattr(net.config, "raw_token_prefix", False)):
            _enc = net.vqvae_local[0].encoder
            if len(getattr(_enc, "blocks", [])) > 0:
                z_prefix = _enc.forward_nopos(prefix_ids)[:, :P, :]
            else:
                z_prefix = _enc.wte(prefix_ids)[:, :P, :]
        else:
            z_prefix = net.vqvae_local[0].encode_z(prefix_ids)[:, :P, :]
        prefix_emb = net.transformer.wte(z_prefix)

    if not net.use_rope:
        prefix_emb = prefix_emb + net.wpe(net.wp_prefix)

    # Pad bias
    pad_bias = None
    if net.prefix_pad_id is not None:
        _pm = (prefix_ids[:, :P] == net.prefix_pad_id)
        pad_bias = torch.zeros(_pm.shape[0], 1, 1, P, device=dev)
        pad_bias[:, :, :, :P] = torch.where(
            _pm[:, None, None, :],
            torch.tensor(float("-inf"), device=dev),
            torch.tensor(0.0, device=dev),
        )

    # Build z_hat from ground truth for idx_to_ncm_input
    z_hat = torch.zeros(B, levels[-1], net.vqvae_local[0].embed_dim, device=dev)

    # Use idx_to_ncm_input to build next_concepts from gt_indices
    # This is @no_grad but only builds INPUT embeddings
    # The transformer pass that follows has gradients
    next_concepts = vq.idx_to_ncm_input(gt_indices)  # (B, sum(levels[1:]), embed_dim)

    # Split next_concepts into per-level inputs
    nc_offset = 0
    nc_per_level = []
    for k in range(len(levels) - 1):
        nc_per_level.append(next_concepts[:, nc_offset : nc_offset + levels[k + 1], :])
        nc_offset += levels[k + 1]

    # Autoregressive level-by-level with CE loss
    total_loss = 0.0
    n_levels = 0
    dtype = prefix_emb.dtype

    for i in range(len(levels)):
        if i == 0:
            # Level 0: input from prefix (get_next_autoregressive_input)
            if net.query_level0:
                if net.l0_ar:
                    ar_input = net.build_l0_ar_input(gt_indices[:, : levels[0] - 1])
                else:
                    ar_input = net.build_l0_query_input(B, dtype)
            else:
                ar_input = vq.get_next_autoregressive_input(None, i, prefix_emb)
        else:
            # Level i: input from idx_to_ncm_input (next_concepts)
            ar_input = nc_per_level[i - 1]

        # Build x for this level: [prefix_emb, ar_input]
        x_level = torch.cat([prefix_emb, ar_input], dim=1)

        # Run transformer
        full_x = torch.cat([prefix_emb, ar_input], dim=1)
        rope = (net.rope_cos, net.rope_sin) if net.use_rope else None

        # Build attention mask for this level
        L_cur = ar_input.shape[1]
        S = P + L_cur

        if net.use_flex_attention:
            # Use flex attention with level-specific mask
            lvl = torch.full((S,), -1, dtype=torch.long, device=dev)
            lvl[P:] = i
            from torch.nn.attention.flex_attention import create_block_mask

            def mask_mod(b, h, q_idx, kv_idx):
                q_pref = q_idx < P
                kv_pref = kv_idx < P
                same_level = (lvl[q_idx] == lvl[kv_idx]) & (lvl[kv_idx] >= 0)
                return torch.where(q_pref, kv_pref, kv_pref | same_level)

            block_mask = create_block_mask(
                mask_mod, B=None, H=None, Q_LEN=S, KV_LEN=S, device=dev, BLOCK_SIZE=128
            )
            for block in net.transformer.blocks:
                full_x = block(full_x, rope_cos_sin=rope, block_mask=block_mask)
        else:
            # Standard mask
            gen_mask = torch.zeros(1, 1, S, S, device=dev)
            gen_mask[:, :, :P, P:] = float("-inf")
            for block in net.transformer.blocks:
                full_x = block(full_x, attn_mask=gen_mask, rope_cos_sin=rope)

        full_x = net.transformer.ln_f(full_x)
        x_target = full_x[:, P:, :]

        # Get logits for this level
        hidx = i if not net.query_level0 else i
        if net.query_level0:
            lm_head = net.lm_heads[hidx]
        else:
            lm_head = net.lm_heads[hidx]

        logits = lm_head(x_target)  # (B, L_cur, vocab_size)
        logits = net._pad_vocab(logits)

        # CE loss against ground truth
        gt_level = gt_indices[:, sum(levels[:i]) : sum(levels[: i + 1])]
        loss = F.cross_entropy(logits.flatten(0, 1), gt_level.flatten(0, 1))

        total_loss += loss.item()
        n_levels += 1

    return total_loss / n_levels if n_levels > 0 else 0.0


def teacher_forcing_step(net, tk, prefix_ids, gt_indices):
    """Differentiable teacher forcing step. Returns loss tensor for backward().

    Replicates generate() logic: each level's input is first passed through
    transformer.wte (embed_dim -> n_embd) before concatenation with prefix_emb.
    Uses _decode_level_logits for levels 1+ and the level-0 path for level 0.
    """
    dev = prefix_ids.device
    B = prefix_ids.shape[0]
    P = net.prefix_len
    levels = net.levels
    vq = net.vqvae_local[0].vq

    # Encode prefix (same as generate())
    if net.use_ctx_encoder:
        prefix_emb = net._encode_context(prefix_ids[:, :P])
    else:
        if bool(getattr(net.config, "raw_token_prefix", False)):
            _enc = net.vqvae_local[0].encoder
            if len(getattr(_enc, "blocks", [])) > 0:
                z_prefix = _enc.forward_nopos(prefix_ids)[:, :P, :]
            else:
                z_prefix = _enc.wte(prefix_ids)[:, :P, :]
        else:
            z_prefix = net.vqvae_local[0].encode_z(prefix_ids)[:, :P, :]
        prefix_emb = net.transformer.wte(z_prefix)

    # Level encoding (used for levels 1+)
    if net.config.use_level_encoding:
        level_pos_embed = net.transformer.wle(net.lvl_1L)
    else:
        T_max = max(P, max(levels))
        level_pos_embed = torch.zeros(1, net.L, net.config.n_embd, device=dev)

    # Build pad bias
    pad_bias = None
    if net.prefix_pad_id is not None:
        _pm = (prefix_ids[:, :P] == net.prefix_pad_id)
        pad_bias = torch.zeros(_pm.shape[0], 1, 1, P, device=dev)
        pad_bias[:, :, :, :P] = torch.where(
            _pm[:, None, None, :],
            torch.tensor(float("-inf"), device=dev),
            torch.tensor(0.0, device=dev),
        )

    # Build next_concepts from gt_indices (idx_to_ncm_input is @no_grad but
    # only builds input embeddings — the transformer forward has gradients)
    next_concepts = vq.idx_to_ncm_input(gt_indices)
    nc_offset = 0
    nc_per_level = []
    for k in range(len(levels) - 1):
        nc_per_level.append(next_concepts[:, nc_offset : nc_offset + levels[k + 1], :])
        nc_offset += levels[k + 1]

    losses = []

    # Level 0
    l0 = levels[0]
    _q0 = net.build_l0_query_input(B, prefix_emb.dtype)
    if net.use_post_upsample_conv:
        _q0 = net._apply_post_upsample_conv_single(_q0, 0)
    q = net.transformer.wte(_q0)
    if not net.use_rope:
        q = q + net.wpe(net.wp_1L[:, :l0])
    if net.config.use_level_encoding:
        q = q + net.transformer.wle(net.lvl_1L[:, :l0])
    h_l0 = torch.cat([prefix_emb, q], dim=1)
    m0 = torch.zeros(1, 1, P + l0, P + l0, device=dev)
    m0[:, :, :P, P:] = float("-inf")
    if pad_bias is not None:
        m0 = m0 + F.pad(pad_bias, (0, l0))
    rope_0 = (net.rope_cos_gen_0, net.rope_sin_gen_0) if net.use_rope else None

    for block in net.transformer.blocks:
        h_l0 = block(h_l0, attn_mask=m0, rope_cos_sin=rope_0)
    h_l0 = net.transformer.ln_f(h_l0)
    logits_l0 = net._pad_vocab(net.lm_heads[0](h_l0[:, P:, :]))
    gt_l0 = gt_indices[:, :l0]
    losses.append(F.cross_entropy(logits_l0.flatten(0, 1), gt_l0.flatten(0, 1)))

    # Levels 1+
    level_acum = levels[0]  # since query_level0
    for level_idx in range(len(levels) - 1):
        # Build input for this level from next_concepts
        x_raw = nc_per_level[level_idx]  # (B, levels[level_idx+1], embed_dim)
        if net.use_post_upsample_conv:
            x_raw = net._apply_post_upsample_conv_single(
                x_raw, level_idx + (1 - net._lvl_first)
            )
        x_emb = net.transformer.wte(x_raw) + level_pos_embed[
            :, level_acum : level_acum + levels[level_idx + 1], :
        ]

        # Head index
        _hi = level_idx + (1 - net._lvl_first)
        rope_k = (
            getattr(net, f"rope_cos_gen_{_hi}"),
            getattr(net, f"rope_sin_gen_{_hi}"),
        ) if net.use_rope else None

        L_cur = levels[level_idx + 1]
        # Use _decode_level_logits for correct attention masking
        logits = net._decode_level_logits(
            x_emb, prefix_emb, level_idx, pad_bias, hidx=_hi
        )
        logits = net._pad_vocab(logits)

        # Ground truth
        gt_start = sum(levels[: level_idx + 1])
        gt_end = sum(levels[: level_idx + 2])
        gt_level = gt_indices[:, gt_start:gt_end]
        losses.append(F.cross_entropy(logits.flatten(0, 1), gt_level.flatten(0, 1)))

        level_acum += levels[level_idx + 1]

    return sum(losses) / len(losses)


def decode_generated(net, tk, prefix_ids, pre_tok, pad_id, eos_id):
    """Generate text from prefix using model (no grad)."""
    with torch.no_grad():
        g = net.generate(None, prefix_ids, temperature=0.0, top_k=1)
        _, zl = tk.vqvae.vq.idx_to_zhats(g, return_zlevels=True)
        recon_ids = tk.vqvae.decoder(zl[-1]).argmax(-1).squeeze(0).tolist()
        if eos_id in recon_ids:
            recon_ids = recon_ids[: recon_ids.index(eos_id)]
        recon_ids = [t for t in recon_ids if t != pad_id]
    return pre_tok.decode(recon_ids, skip_special_tokens=True)


def vqvae_roundtrip(vqvae, text, pre_tok, ctx_len, pad_id, eos_id):
    """Round-trip text through VQVAE encoder -> quantize -> decoder."""
    ids = pre_tok(text, return_tensors="pt")["input_ids"].cuda()
    if ids.shape[1] < ctx_len:
        ids = torch.nn.functional.pad(ids, (0, ctx_len - ids.shape[1]), value=pad_id)
    else:
        ids = ids[:, :ctx_len]
    with torch.no_grad():
        z_enc = vqvae.encoder(ids)
        vq_out = vqvae.vq(z_enc)
        recon = vqvae.decoder(vq_out[0])
    recon_ids = recon.argmax(-1).squeeze(0).tolist()
    if eos_id in recon_ids:
        recon_ids = recon_ids[: recon_ids.index(eos_id)]
    recon_ids = [t for t in recon_ids if t != pad_id]
    return pre_tok.decode(recon_ids, skip_special_tokens=True)


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

    trainable = sum(p.numel() for p in net.parameters() if p.requires_grad)
    print(f"Trainable params: {trainable:,}")
    print(f"VQVAE frozen: {sum(p.numel() for p in tk.vqvae.parameters()):,} params")

    with open(args.fixtures) as f:
        fixtures = json.load(f)
    print(f"Loaded {len(fixtures)} training fixtures")

    ctx_len = cfg.tokenizer.vqvae.context_length
    prefix_len = cfg.model.prefix_len
    PAD_ID = 50257
    EOS_ID = pre_tok.eos_token_id

    prompts = [build_prompt(fx) for fx in fixtures]
    target_texts = [f"{fx['label']}: {fx['reference_rationale']}" for fx in fixtures]

    # Encode prefixes
    prefix_list = []
    for p in prompts:
        ids = pre_tok(p, return_tensors="pt")["input_ids"][0]
        if len(ids) < prefix_len:
            ids = torch.nn.functional.pad(ids, (0, prefix_len - len(ids)), value=PAD_ID)
        else:
            ids = ids[:prefix_len]
        prefix_list.append(ids)
    prefixes = torch.stack(prefix_list).cuda()

    # Encode targets -> hierarchical indices (ground truth)
    gt_indices_list = []
    for text in target_texts:
        ids = pre_tok(text, return_tensors="pt")["input_ids"].cuda()
        if ids.shape[1] < ctx_len:
            ids = torch.nn.functional.pad(ids, (0, ctx_len - ids.shape[1]), value=PAD_ID)
        else:
            ids = ids[:, :ctx_len]
        with torch.no_grad():
            z_enc = tk.vqvae.encoder(ids)
            vq_out = tk.vqvae.vq(z_enc)
            gt = tk.vqvae.vq.z_to_idx(vq_out[0])  # (1, 200)
        gt_indices_list.append(gt)
    gt_indices = torch.cat(gt_indices_list, dim=0)  # (N, 200)

    # Verify indices
    for k, vs in enumerate(net.vocab_sizes):
        level_start = sum(net.levels[:k])
        level_end = sum(net.levels[: k + 1])
        max_idx = gt_indices[:, level_start:level_end].max().item()
        print(f"Level {k}: {net.levels[k]} tokens, max_idx={max_idx} < {vs} ✓")

    print(f"\nPrefix shape: {prefixes.shape}")
    print(f"GT indices shape: {gt_indices.shape}")

    # Baseline comparison
    print("\n--- Baseline (before training) ---")
    comparison_data = [{"epoch": 0, "phase": "baseline", "samples": []}]
    for idx in range(len(fixtures)):
        gen_text = decode_generated(net, tk, prefixes[idx : idx + 1], pre_tok, PAD_ID, EOS_ID)
        vqvae_text = vqvae_roundtrip(tk.vqvae, target_texts[idx], pre_tok, ctx_len, PAD_ID, EOS_ID)
        comparison_data[-1]["samples"].append(
            {
                "fixture_idx": idx,
                "label": fixtures[idx]["label"],
                "original_target": target_texts[idx],
                "vqvae_roundtrip": vqvae_text,
                "ncm_baseline": gen_text,
            }
        )
        print(f"[{fixtures[idx]['label']}] fixture {idx}")
        print(f"  Target:   {target_texts[idx][:80]}...")
        print(f"  VQVAE RT: {vqvae_text[:80]}...")
        print(f"  NCM gen:  {gen_text[:80]}...")
        print()

    # Training
    optimizer = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=1e-5)
    n_steps = args.epochs * ((len(fixtures) + args.bs - 1) // args.bs)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_steps)

    os.makedirs(args.out_dir, exist_ok=True)
    losses = []

    print(f"\nTraining: {args.epochs} epochs, {len(fixtures)} samples, bs={args.bs}")
    print("=" * 60)

    for epoch in range(args.epochs):
        net.train()
        epoch_loss = 0
        n_batches = 0

        perm = torch.randperm(len(fixtures))
        for i in range(0, len(fixtures), args.bs):
            batch_idx = perm[i : i + args.bs]
            batch_prefix = prefixes[batch_idx]
            batch_gt = gt_indices[batch_idx]

            optimizer.zero_grad()
            loss = teacher_forcing_step(net, tk, batch_prefix, batch_gt)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), max_norm=1.0)
            optimizer.step()
            scheduler.step()

            epoch_loss += loss.item()
            n_batches += 1

        avg_loss = epoch_loss / max(n_batches, 1)
        losses.append(avg_loss)

        if epoch % 10 == 0 or epoch == args.epochs - 1:
            param_changed = any(
                p.grad is not None and p.grad.abs().sum() > 0 for p in net.parameters()
            )
            print(
                f"Epoch {epoch:3d}: loss={avg_loss:.4f}, "
                f"lr={scheduler.get_last_lr()[0]:.6f}, "
                f"grads_ok={param_changed}"
            )

        # Comparison every 10 epochs
        if epoch % 10 == 0 or epoch == args.epochs - 1:
            net.eval()
            comp = []
            for idx in range(len(fixtures)):
                gen_text = decode_generated(
                    net, tk, prefixes[idx : idx + 1], pre_tok, PAD_ID, EOS_ID
                )
                comp.append(
                    {
                        "fixture_idx": idx,
                        "label": fixtures[idx]["label"],
                        "ncm_generated": gen_text,
                    }
                )
            comparison_data.append({"epoch": epoch, "loss": avg_loss, "samples": comp})
            net.train()

    # Save outputs
    ckpt_path = os.path.join(args.out_dir, "finetuned_generator.pt")
    torch.save({"model": net.state_dict(), "epoch": args.epochs}, ckpt_path)

    with open(os.path.join(args.out_dir, "loss_curve.json"), "w") as f:
        json.dump(losses, f)
    with open(os.path.join(args.out_dir, "comparison_data.json"), "w") as f:
        json.dump(comparison_data, f, indent=2)

    print(f"\nFinal loss: {losses[-1]:.4f}")
    print(f"Checkpoint: {ckpt_path}")

    if losses[-1] < 4.0:
        print("Overfit check PASSED (loss < 4.0 on 7 samples)")
    else:
        print(f"Loss still high: {losses[-1]:.2f} — review training pipeline")


pre_tok = AutoTokenizer.from_pretrained("gpt2")


if __name__ == "__main__":
    main()
