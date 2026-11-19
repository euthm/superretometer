# FILE: examples/ncm_explanations/ncm_run.py
"""NCM generation using the upstream eval_shard.py directly.

Instead of reimplementing the decoder (which requires frequency_allowance,
frequency_deficit, adjacency_penalty, cfg_scale etc.), we call the upstream
eval_shard.py as a subprocess with custom input data.

The upstream evaluator expects:
  - config: config/eval/xsum.yaml
  - checkpoint-dir: directory with tokenizer.pt, generator.pt, config.yaml
  - data-dir: directory with passages.pickle (list of input strings)

We create a minimal passages.pickle with our prompts and run the evaluator.
"""
from __future__ import annotations
import argparse
import json
import os
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path


def generate_with_ncm(prompts: list[str], checkpoint_dir: str, source_dir: str) -> list[dict]:
    """Generate NCM summaries using the upstream eval_shard.py.

    Creates a temporary passages.pickle, runs the upstream shard evaluator,
    and returns the generated summaries.
    """
    results = []
    cfg_path = Path(checkpoint_dir) / "config.yaml"

    if not cfg_path.exists():
        return [{"input": p, "summary": "", "status": "error",
                 "error": f"config.yaml not found in {checkpoint_dir}"} for p in prompts]

    if not prompts:
        return []

    tmpdir = tempfile.mkdtemp(prefix="ncm_eval_")
    try:
        # Create data directory with passages.pickle
        data_dir = Path(tmpdir) / "data"
        data_dir.mkdir()

        # XSum expects two pickle files:
        #   passages.pickle — list of input strings
        #   reference_summaries.pickle — list of reference strings (empty for us)
        with open(data_dir / "passages.pickle", "wb") as f:
            pickle.dump(prompts, f)
        with open(data_dir / "reference_summaries.pickle", "wb") as f:
            pickle.dump([""] * len(prompts), f)

        out_path = Path(tmpdir) / "output.pkl"

        # Run upstream eval_shard.py
        shard_script = Path(source_dir) / "scripts" / "eval_shard.py"
        if not shard_script.exists():
            return [{"input": p, "summary": "", "status": "error",
                     "error": f"eval_shard.py not found at {shard_script}"} for p in prompts]

        env = os.environ.copy()
        env["NCM_ROOT"] = source_dir
        env["TOKENIZERS_PARALLELISM"] = "false"

        proc = subprocess.run(
            [sys.executable, str(shard_script),
             "--config", str(cfg_path),
             "--checkpoint-dir", checkpoint_dir,
             "--data-dir", str(data_dir),
             "--n", str(len(prompts)),
             "--bs", str(len(prompts)),  # process all in one batch
             "--shard", "0",
             "--nshards", "1",
             "--out", str(out_path)],
            capture_output=True, text=True, timeout=300, env=env,
            cwd=source_dir,
        )

        if proc.returncode != 0 or not out_path.exists():
            error_msg = proc.stderr.strip() or proc.stdout.strip() or "eval_shard.py failed"
            return [{"input": p, "summary": "", "status": "error", "error": error_msg} for p in prompts]

        # Load results
        with open(out_path, "rb") as f:
            out_data = pickle.load(f)

        hyps = out_data.get("hyps", [])
        if len(hyps) != len(prompts):
            return [{"input": p, "summary": "", "status": "error",
                     "error": f"Expected {len(prompts)} outputs, got {len(hyps)}"} for p in prompts]

        for i, prompt in enumerate(prompts):
            results.append({
                "input": prompt,
                "summary": hyps[i],
                "status": "generated",
                "error": "",
            })

    except subprocess.TimeoutExpired:
        return [{"input": p, "summary": "", "status": "error",
                 "error": "NCM generation timed out (300s)"} for p in prompts]
    except Exception as e:
        return [{"input": p, "summary": "", "status": "error", "error": str(e)} for p in prompts]
    finally:
        # Cleanup
        import shutil
        try:
            shutil.rmtree(tmpdir)
        except OSError:
            pass

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-dir", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--input-file", required=True, help="JSON file with list of prompts")
    parser.add_argument("--output-file", required=True, help="JSON output file")
    args = parser.parse_args()

    prompts = json.load(open(args.input_file))
    results = generate_with_ncm(prompts, args.checkpoint_dir, args.source_dir)
    json.dump(results, open(args.output_file, "w"), indent=2)
    print(json.dumps(results, indent=2))
