# FILE: examples/ncm_finetune/train_source_grounding.py
"""Step 3 (Issue #34): Custom fine-tuning loop for NCM source-grounded claim detection.

Uses the generator's internal forward pass with teacher forcing:
1. Encode (prefix + target) through VQVAE encoder -> z
2. Pass z through transformer -> logits over hierarchical concept indices
3. Cross-entropy loss between predicted indices and actual VQVAE indices

VQVAE is frozen. Only the NextConceptTransformer is trained.

After training, comparison report shows:
  - Original target text
  - VQVAE round-trip (encoder -> quantize -> decoder)
  - Fine-tuned generator output
This reveals where facts are lost at each stage.
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


def build_prompt(fixture):
    return (
        f"Source excerpt:\n{fixture['source_passage']}\n\n"
        f"Claim:\n{fixture['claim']}\n\n"
        f"Determine whether the source excerpt establishes the claim. "
        f"Answer with one of: established, not_established, beyond_scope. "
        f"Explain your reasoning in one sentence."
    )


def generate_with_grad(net, tk, prefix_tokens, l0=None):
    """Replicate generate() logic but WITH gradients.
    
    Copied from NextConceptTransformer.generate() but without @torch.no_grad().
    Returns: g (hierarchical indices), zl (z-hat levels)
    """
    dev = prefix_tokens.device
    vq = net.vqvae_local[0].vq
    B = prefix_tokens.shape[0]
    P = net.prefix_len
    levels = net.levels
    L_total = net.L

    # Prefix encoding
    if net.use_ctx_encoder:
        prefix_emb = net._encode_context(prefix_tokens[:, :P])
    else:
        if bool(getattr(net.config, "raw_token_prefix", False)):
            _enc = net.vqvae_local[0].encoder
            if bool(getattr(_enc, "blocks", [])):
                z_prefix = _enc.forward_nopos(prefix_tokens)[:, :P, :]
            else:
                z_prefix = _enc.wte(prefix_tokens)[:, :P, :]
        else:
            z_prefix = net.vqvae_local[0].encode_z(prefix_tokens)[:, :P, :]
        prefix_emb = net.transformer.wte(z_prefix)

    if not net.use_rope:
        prefix_emb = prefix_emb + net.wpe(net.wp_prefix)

    if net.config.use_level_encoding:
        level_pos_embed = net.transformer.wle(net.lvl_1L)
    else:
        level_pos_embed = torch.zeros(
            1, L_total - levels[0], net.config.n_embd, device=dev
        )
    if not net.use_rope:
        level_pos_embed = level_pos_embed + net.wpe(net.wp_1L)

    # Pad mask
    _pbias = None
    if net.prefix_pad_id is not None:
        _pm = (prefix_tokens[:, :P] == net.prefix_pad_id)
        _pbias = torch.zeros(_pm.shape[0], 1, 1, P, device=dev)
        _pbias[:, :, :, :P] = torch.where(
            _pm[:, None, None, :],
            torch.tensor(float("-inf"), device=dev),
            torch.tensor(0.0, device=dev),
        )

    # Autoregressive generation level by level
    g = torch.zeros(B, L_total, dtype=torch.long, device=dev)
    prev_emb = prefix_emb
    prev_kv = None
    pos_offset = P
    z_hat = torch.zeros(
        B, levels[-1], net.vqvae_local[0].embed_dim, device=dev
    )

    for i, n in enumerate(levels):
        n_prev = levels[i - 1] if i > 0 else P

        # Get autoregressive input for this level
        if i == 0 and l0 is not None:
            ar_input = l0
        elif i == 0:
            ar_input = vq.get_next_autoregressive_input(None, i, prev_emb)
        else:
            ar_input = vq.get_next_autoregressive_input(g, i, prev_emb)

        # Run transformer
        x = torch.cat([prev_emb, ar_input], dim=1)
        if net.use_post_upsample_conv:
            x[:, n_prev:, :] = net._apply_post_upsample_conv(x[:, n_prev:, :], i)

        logits = net._run_stack(prefix_emb, x, _pbias)
        logits = logits[:, n_prev - P:, :]

        # Sample next token (greedy for training)
        p = logits.argmax(-1)
        g[:, n_prev:n] = p

        # Build z-hat for next level
        z_hat[:, :n, :] = vq.idx_to_z_q(g[:, :n], i)
        z_resi = vq.quant_resi(z_hat[:, :n, :]) if vq.quant_resi_enabled else z_hat[:, :n, :]
        prev_emb = net.transformer.wte(z_resi)
        if not net.use_rope:
            prev_emb = prev_emb + net.wpe(
                torch.arange(n_prev, n, device=dev).unsqueeze(0)
            )
        if net.config.use_level_encoding:
            prev_emb = prev_emb + net.transformer.wle(
                net.lvl_1L[n_prev - P : n - P : 1, :]
            )

    # Build z-hat levels
    zl = []
    cum = 0
    for n in levels:
        cum += n
        zl.append(z_hat[:, :cum, :])

    return g, zl


def decode_output(net, tk, g, pre_tok, pad_id, eos_id):
    """Decode hierarchical indices to text."""
    _, zl = tk.vqvae.vq.idx_to_zhats(g, return_zlevels=True)
    logits = tk.vqvae.decoder(zl[-1])
    recon_ids = logits.argmax(-1).squeeze(0).tolist()
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

    # Load fixtures
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

    # Encode targets through VQVAE to get hierarchical indices
    # For teacher forcing, we need the target as z-latents for forward()
    # But for loss computation, we decode and compare to original tokens
    # Strategy: use generate_with_grad() -> decode -> CE loss vs target tokens

    optimizer = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=1e-5)
    n_steps = args.epochs * ((len(fixtures) + args.bs - 1) // args.bs)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_steps)

    os.makedirs(args.out_dir, exist_ok=True)
    losses = []
    comparison_data = []

    print(f"\nTraining: {args.epochs} epochs, {len(fixtures)} samples, bs={args.bs}")
    print("=" * 60)

    # Baseline comparison (epoch 0, before training)
    net.eval()
    baseline = []
    for idx in range(len(fixtures)):
        with torch.no_grad():
            g = net.generate(None, prefixes[idx : idx + 1], temperature=0.0, top_k=1)
        gen_text = decode_output(net, tk, g, pre_tok, PAD_ID, EOS_ID)

        # VQVAE round-trip
        orig_ids = pre_tok(target_texts[idx], return_tensors="pt")["input_ids"].cuda()
        if orig_ids.shape[1] < ctx_len:
            orig_ids = torch.nn.functional.pad(
                orig_ids, (0, ctx_len - orig_ids.shape[1]), value=PAD_ID
            )
        with torch.no_grad():
            z_enc = tk.vqvae.encoder(orig_ids)
            vq_out = tk.vqvae.vq(z_enc)
            vqvae_recon = tk.vqvae.decoder(vq_out[0])
        vqvae_ids = vqvae_recon.argmax(-1).squeeze(0).tolist()
        if EOS_ID in vqvae_ids:
            vqvae_ids = vqvae_ids[: vqvae_ids.index(EOS_ID)]
        vqvae_ids = [t for t in vqvae_ids if t != PAD_ID]
        vqvae_text = pre_tok.decode(vqvae_ids, skip_special_tokens=True)

        baseline.append(
            {
                "fixture_idx": idx,
                "label": fixtures[idx]["label"],
                "original_target": target_texts[idx],
                "vqvae_roundtrip": vqvae_text,
                "ncm_baseline": gen_text,
            }
        )
    comparison_data.append({"epoch": 0, "phase": "baseline", "samples": baseline})
    net.train()

    # Print baseline for comparison
    print("\n--- Baseline (before training) ---")
    for b in baseline[:3]:
        print(f"[{b['label']}] fixture {b['fixture_idx']}")
        print(f"  Target:    {b['original_target'][:80]}...")
        print(f"  VQVAE RT:  {b['vqvae_roundtrip'][:80]}...")
        print(f"  NCM gen:   {b['ncm_baseline'][:80]}...")
        print()

    for epoch in range(args.epochs):
        net.train()
        epoch_loss = 0
        n_batches = 0

        perm = torch.randperm(len(fixtures))
        for i in range(0, len(fixtures), args.bs):
            batch_idx = perm[i : i + args.bs]
            batch_prefix = prefixes[batch_idx]

            optimizer.zero_grad()

            # Generate with gradients
            g = generate_with_grad(net, tk, batch_prefix)
            # g: (B, L_total) hierarchical indices

            # Decode to get logits over GPT2 tokens
            _, zl = tk.vqvae.vq.idx_to_zhats(g, return_zlevels=True)
            logits = tk.vqvae.decoder(zl[-1])  # (B, ctx_len, 50304)

            # Target token IDs
            target_id_list = []
            for idx in batch_idx.tolist():
                ids = pre_tok(target_texts[idx], return_tensors="pt")["input_ids"][0]
                if len(ids) < ctx_len:
                    ids = torch.nn.functional.pad(
                        ids, (0, ctx_len - len(ids)), value=PAD_ID
                    )
                else:
                    ids = ids[:ctx_len]
                target_id_list.append(ids)
            target_token_ids = torch.stack(target_id_list).cuda()

            loss = nn.functional.cross_entropy(
                logits.flatten(0, 1),
                target_token_ids.flatten(0, 1),
                ignore_index=PAD_ID,
            )

            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), max_norm=1.0)
            optimizer.step()
            scheduler.step()

            epoch_loss += loss.item()
            n_batches += 1

        avg_loss = epoch_loss / max(n_batches, 1)
        losses.append(avg_loss)

        if epoch % 10 == 0 or epoch == args.epochs - 1:
            print(
                f"Epoch {epoch:3d}: loss={avg_loss:.4f}, "
                f"lr={scheduler.get_last_lr()[0]:.6f}"
            )

        # Save comparison every 10 epochs
        if epoch % 10 == 0 or epoch == args.epochs - 1:
            net.eval()
            comp = []
            for idx in range(len(fixtures)):
                with torch.no_grad():
                    g = net.generate(
                        None, prefixes[idx : idx + 1], temperature=0.0, top_k=1
                    )
                gen_text = decode_output(net, tk, g, pre_tok, PAD_ID, EOS_ID)
                comp.append(
                    {
                        "fixture_idx": idx,
                        "label": fixtures[idx]["label"],
                        "ncm_generated": gen_text,
                    }
                )
            comparison_data.append(
                {"epoch": epoch, "loss": avg_loss, "samples": comp}
            )
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
    print(f"Comparison: {os.path.join(args.out_dir, 'comparison_data.json')}")


pre_tok = AutoTokenizer.from_pretrained("gpt2")


if __name__ == "__main__":
    main()
