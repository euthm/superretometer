# FILE: examples/ncm_explanations/ncm_explain.py
"""NCM explanation generation via ncm_run.py.

Attempts to use the HazyResearch NCM XSum checkpoint to generate a summary
of a warrant record. Falls back gracefully if weights are not available.

Following issue #32: pin the upstream revision and checkpoint. Keep PyTorch
and the weights local to this optional example.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

# Pinned upstream revision (from issue #32)
NCM_GITHUB_REV = "main"  # HazyResearch/ncm as of Oct 2026


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

    return "\n".join(parts)


def generate_ncm_summary(record: dict, checkpoint_dir: str, source_dir: str) -> dict:
    """Generate an NCM summary using ncm_run.py.

    Returns a dict with status, summary, error, model_revision, checkpoint_dir.
    """
    result = {
        "status": "skipped",
        "summary": "",
        "reason": "",
        "model_revision": NCM_GITHUB_REV,
        "checkpoint_dir": checkpoint_dir,
    }

    # Check prerequisites
    if not checkpoint_dir or not Path(checkpoint_dir).exists():
        result["reason"] = f"NCM checkpoint directory not found: {checkpoint_dir or '(not set)'}"
        return result

    if not source_dir or not Path(source_dir).exists():
        result["reason"] = f"NCM source directory not found: {source_dir or '(not set)'}"
        return result

    # Use ncm_run.py as subprocess to isolate GPU/NCM imports
    import json
    import subprocess
    import tempfile

    here = Path(__file__).resolve().parent
    ncm_run = here / "ncm_run.py"
    if not ncm_run.exists():
        result["status"] = "error"
        result["reason"] = f"ncm_run.py not found at {ncm_run}"
        return result

    prompt = render_prompt(record)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fin:
        json.dump([prompt], fin)
        input_path = fin.name
    output_path = input_path + ".out"

    try:
        env = os.environ.copy()
        proc = subprocess.run(
            [sys.executable, str(ncm_run),
             "--checkpoint-dir", checkpoint_dir,
             "--source-dir", source_dir,
             "--input-file", input_path,
             "--output-file", output_path],
            capture_output=True, text=True, timeout=120, env=env,
        )
        if proc.returncode == 0 and Path(output_path).exists():
            out = json.load(open(output_path))
            if out and out[0].get("status") == "generated":
                result["status"] = "generated"
                result["summary"] = out[0]["summary"]
            else:
                result["status"] = out[0].get("status", "error")
                result["reason"] = out[0].get("error", "Unknown NCM error")
        else:
            result["status"] = "error"
            result["reason"] = proc.stderr.strip() or proc.stdout.strip() or "ncm_run.py failed"
    except subprocess.TimeoutExpired:
        result["status"] = "error"
        result["reason"] = "NCM generation timed out (120s)"
    except Exception as e:
        result["status"] = "error"
        result["reason"] = str(e)
    finally:
        for p in (input_path, output_path):
            try:
                os.unlink(p)
            except OSError:
                pass

    return result
