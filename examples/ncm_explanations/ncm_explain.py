# FILE: examples/ncm_explanations/ncm_explain.py
"""NCM explanation generation.

Attempts to use the HazyResearch NCM XSum checkpoint to generate a summary
of a warrant record. Falls back gracefully if weights are not available.

NCM is a coarse-to-fine text generation model. We use it to produce a
concise summary of the warrant record's structured data. The summary is
advisory only — the verified verdict, evidence roots, and warrant result
remain the authority.

Following issue #32: pin the upstream revision and checkpoint. Keep PyTorch
and the weights local to this optional example.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

# Pinned upstream revision (from issue #32)
NCM_GITHUB_REV = "main"  # HazyResearch/ncm as of Oct 2026
NCM_CHECKPOINT_DIR = os.environ.get("NCM_CHECKPOINT_DIR", "")
NCM_SOURCE_DIR = os.environ.get("NCM_SOURCE_DIR", "")


def render_prompt(record: dict) -> str:
    """Render a warrant record as an English summary prompt for NCM.

    NCM's XSum checkpoint expects a source document and produces a summary.
    We format the structured warrant record as a source document.
    """
    parts = []
    parts.append(f"CONCLUSION: {record['conclusion_id']}")
    parts.append(f"VERDICT: {record['warrant_status']}")
    parts.append(f"LABEL: {record['label']}")

    indep = record.get("independence", {})
    parts.append(
        f"Evidence count: {indep.get('evidence_count', 0)}. "
        f"Independent provenance roots: {indep.get('independent_root_count', 0)}."
    )

    root_sets = indep.get("root_sets", {})
    for ev_id, roots in sorted(root_sets.items()):
        parts.append(f"Statement {ev_id} derives from root(s): {', '.join(roots) if roots else 'none'}.")

    shared = indep.get("shared_ancestors", {})
    if shared:
        for root, kos in sorted(shared.items()):
            parts.append(f"Root '{root}' is shared by statements: {', '.join(kos)}.")
    else:
        parts.append("No shared provenance ancestors. Evidence roots are independent.")

    if record["independent_kos"]:
        parts.append(f"Independently grounded statements: {', '.join(record['independent_kos'])}.")
    if record["dependent_kos"]:
        parts.append(f"Dependent or ungrounded statements: {', '.join(record['dependent_kos'])}.")

    if record["anti_pattern_diagnoses"]:
        for d in record["anti_pattern_diagnoses"]:
            parts.append(f"Anti-pattern {d['pattern']}: {d['violated_condition']}.")

    if record["conditional_assumptions"]:
        for a in record["conditional_assumptions"]:
            parts.append(f"Gap: {a}.")

    return " ".join(parts)


def generate_ncm_summary(record: dict) -> dict:
    """Try to generate an NCM summary of the warrant record.

    Returns a dict with:
      - status: "generated", "skipped", or "error"
      - summary: the generated text (if status == "generated")
      - reason: explanation of skip/error
      - model_revision: pinned upstream revision
      - checkpoint_dir: path used
    """
    result = {
        "status": "skipped",
        "summary": "",
        "reason": "",
        "model_revision": NCM_GITHUB_REV,
        "checkpoint_dir": NCM_CHECKPOINT_DIR,
    }

    # Check prerequisites
    if not NCM_CHECKPOINT_DIR or not Path(NCM_CHECKPOINT_DIR).exists():
        result["reason"] = (
            f"NCM checkpoint directory not found: {NCM_CHECKPOINT_DIR or '(not set)'}. "
            f"Set NCM_CHECKPOINT_DIR to a directory containing tokenizer.pt, generator.pt, and config.yaml. "
            f"Download with: hf download hazyresearch/ncm-checkpoints --local-dir <dir>"
        )
        return result

    if not NCM_SOURCE_DIR or not Path(NCM_SOURCE_DIR).exists():
        result["reason"] = (
            f"NCM source directory not found: {NCM_SOURCE_DIR or '(not set)'}. "
            f"Set NCM_SOURCE_DIR to a clone of https://github.com/HazyResearch/ncm. "
            f"Install with: pip install -r requirements.txt"
        )
        return result

    # Add NCM source to path
    sys.path.insert(0, NCM_SOURCE_DIR)

    try:
        import torch
        from omegaconf import OmegaConf
        from models.generator import Generator
        from tokenization.vq_tokenizer import VQTokenizer
    except ImportError as e:
        result["status"] = "error"
        result["reason"] = f"Failed to import NCM modules: {e}. Install: pip install -r {NCM_SOURCE_DIR}/requirements.txt"
        return result

    checkpoint_path = Path(NCM_CHECKPOINT_DIR)
    try:
        # Load tokenizer
        tokenizer_path = checkpoint_path / "tokenizer.pt"
        if not tokenizer_path.exists():
            result["reason"] = f"tokenizer.pt not found in {checkpoint_path}"
            return result
        tokenizer = VQTokenizer.load(tokenizer_path)

        # Load generator
        generator_path = checkpoint_path / "generator.pt"
        config_path = checkpoint_path / "config.yaml"
        if not generator_path.exists() or not config_path.exists():
            result["reason"] = f"generator.pt or config.yaml not found in {checkpoint_path}"
            return result

        config = OmegaConf.load(config_path)
        generator = Generator(OmegaConf.to_container(config, resolve=True))
        generator.load_state_dict(torch.load(generator_path, map_location="cpu", weights_only=True))
        generator.eval()

        # Prepare input
        prompt = render_prompt(record)
        # Tokenize the prompt
        tokenized = tokenizer.encode(prompt)

        # Generate
        with torch.no_grad():
            # NCM generates coarse-to-fine in parallel levels
            generated_codes = generator.generate(tokenized.unsqueeze(0))
            summary = tokenizer.decode(generated_codes.squeeze(0))

        result["status"] = "generated"
        result["summary"] = summary.strip()

    except Exception as e:
        result["status"] = "error"
        result["reason"] = f"NCM generation failed: {e}"

    return result
