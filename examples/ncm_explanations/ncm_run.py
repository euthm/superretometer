# FILE: examples/ncm_explanations/ncm_run.py
"""Direct NCM generation call using the upstream code paths.

Loads the XSum tokenizer and generator, then generates a summary for
each warrant record. Uses the same code path as eval_shard.py.
"""
from __future__ import annotations
import os
import sys
import argparse
from pathlib import Path

def generate_with_ncm(prompts: list[str], checkpoint_dir: str, source_dir: str) -> list[dict]:
    """Generate NCM summaries for the given prompts.

    Args:
        prompts: list of text strings to summarize
        checkpoint_dir: path to xsum checkpoint (tokenizer.pt, generator.pt)
        source_dir: path to HazyResearch/ncm checkout

    Returns:
        List of dicts with 'input', 'summary', 'status', 'error'
    """
    sys.path.insert(0, source_dir)
    os.environ["NCM_ROOT"] = source_dir

    import torch
    from omegaconf import OmegaConf
    from models.next_concept import NextConceptTransformer
    from tokenization.vqvae_tokenizer import VQVAETokenizer
    from transformers import AutoTokenizer

    cfg_path = Path(checkpoint_dir) / "config.yaml"
    if not cfg_path.exists():
        return [{"input": p, "summary": "", "status": "error",
                 "error": f"config.yaml not found in {checkpoint_dir}"} for p in prompts]

    CFG = OmegaConf.load(cfg_path)

    # Set checkpoint paths
    CFG.tokenizer.vqvae.checkpoint_path = os.path.join(checkpoint_dir, CFG.checkpoints.tokenizer)
    for key, name in (('vocab_file_path', 'bpe_vocab'), ('merges_file_path', 'bpe_merges')):
        if CFG.checkpoints.get(name):
            CFG.tokenizer.pre_tokenizer[key] = os.path.join(checkpoint_dir, CFG.checkpoints[name])

    try:
        tk = VQVAETokenizer.from_config(CFG.tokenizer)
        tk.vqvae = tk.vqvae.cuda().eval()
        net = NextConceptTransformer(vqvae_local=tk.vqvae, config=CFG.model).cuda()
        sd = torch.load(os.path.join(checkpoint_dir, CFG.checkpoints.generator),
                        map_location="cpu", weights_only=False)
        net.load_state_dict(sd["model"], strict=True)
        net.eval()
    except Exception as e:
        return [{"input": p, "summary": "", "status": "error", "error": str(e)} for p in prompts]

    P = int(CFG.model.prefix_len)
    EOS = tk.pre_tokenizer.eos_token_id
    PAD = tk.pre_tokenizer.pad_token_id

    src_tok = AutoTokenizer.from_pretrained(str(CFG.tokenizer.pre_tokenizer.model_id))

    G = CFG.generation
    temp = G.get("temperature", 1.0)
    top_k = G.get("top_k", 1)
    top_p = G.get("top_p", 0.0)
    cfg_scale = G.get("cfg_scale", 0.0)

    def prefix(item):
        ids = src_tok(item)["input_ids"]
        return (ids[:P] + [PAD] * P)[:P]

    def pick_tokens(logits):
        freq = G.get("frequency_penalty", 2.0)
        adj_str = G.get("adjacency_penalty", "5,4,0.5")
        adj = [float(v) for v in adj_str.split(",")] if adj_str else []
        allow_path = G.get("frequency_allowance", "generator.pt:inference.token_unigram")
        V = logits.shape[-1]
        T = logits.shape[1]
        lg = logits.double()
        if allow_path:
            try:
                ALLOW = sd[allow_path.split(":")[1].split(".")[0] if ":" not in allow_path else allow_path.split(":")[1]]
                # frequency_allowance format: "generator.pt:inference.token_unigram"
                # sd is the state dict, need to navigate
                parts = allow_path.split(":")
                if len(parts) == 2:
                    ref_key = parts[1]
                    obj = sd["model"] if ref_key.startswith("inference") else sd
                    for k in ref_key.split("."):
                        if k in obj:
                            obj = obj[k]
                    ALLOW = obj[:V].double()
                else:
                    ALLOW = None
            except:
                ALLOW = None
        else:
            ALLOW = None
        allow = (ALLOW[:V] * T)[None, :] if ALLOW is not None else None
        al = adj[0] if adj else 0.0
        aw = int(adj[1]) if adj and len(adj) > 1 else 1
        ad = adj[2] if adj and len(adj) > 2 else 1.0
        B = logits.shape[0]
        cnt = torch.zeros(B, V, dtype=torch.float64, device=lg.device)
        out = torch.empty(B, T, dtype=torch.long, device=lg.device)
        hist = []
        for t in range(T):
            step = lg[:, t, :].clone()
            if freq > 0:
                excess = (cnt - allow).clamp_min(0.0) if allow is not None else cnt
                step -= freq * excess
            for j, h in enumerate(reversed(hist[-aw:])):
                step.scatter_add_(1, h[:, None],
                    torch.full((B, 1), -al * ad ** j, dtype=torch.float64, device=lg.device))
            p = step.argmax(-1)
            out[:, t] = p
            hist.append(p)
            cnt.scatter_add_(1, p[:, None], torch.ones(B, 1, dtype=torch.float64, device=lg.device))
        return out

    CUT_AT_EOS = True

    def dec(ids):
        ids = list(ids)
        if CUT_AT_EOS and EOS in ids:
            ids = ids[:ids.index(EOS)]
        return tk.pre_tokenizer.decode([t for t in ids if t not in (EOS, PAD)], skip_special_tokens=True)

    def run(x):
        with torch.no_grad():
            g = net.generate(None, x, temperature=temp, top_k=top_k, top_p=top_p,
                            cfg_scale=cfg_scale, cfg_null_eos=EOS)
            _, zl = tk.vqvae.vq.idx_to_zhats(g, return_zlevels=True)
            ids = pick_tokens(tk.vqvae.decoder(zl[-1])).tolist()
            return [dec(r) for r in ids]

    results = []
    for prompt in prompts:
        try:
            x = torch.tensor([prefix(prompt)], device="cuda")
            summaries = run(x)
            results.append({
                "input": prompt,
                "summary": summaries[0] if summaries else "",
                "status": "generated",
                "error": "",
            })
        except Exception as e:
            results.append({
                "input": prompt,
                "summary": "",
                "status": "error",
                "error": str(e),
            })

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-dir", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--input-file", required=True, help="JSON file with list of prompts")
    parser.add_argument("--output-file", required=True, help="JSON output file")
    args = parser.parse_args()

    import json
    prompts = json.load(open(args.input_file))
    results = generate_with_ncm(prompts, args.checkpoint_dir, args.source_dir)
    json.dump(results, open(args.output_file, "w"), indent=2)
    print(json.dumps(results, indent=2))
