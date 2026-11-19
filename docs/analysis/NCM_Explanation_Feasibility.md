# NCM Explanation Feasibility Assessment

## Date
2026-11-19

## Subject
Can Next-Concept Modeling (NCM) generate executive, engineering, and audit explanations from frozen CH reports?

## NCM Repository Analysis

| Property | Finding |
|----------|---------|
| **Repository** | https://github.com/HazyResearch/ncm |
| **License** | MIT (permissive, no restrictions on commercial use) |
| **Architecture** | 12-layer transformer + VQ-VAE (9-level multiscale residual vector quantizer) |
| **Model size** | 768-dim embedding, 12 heads; ~120M params (typical for released models) |
| **GPU requirement** | CUDA required. Multi-GPU shard evaluation. No CPU inference path. |
| **Inference model** | Coarse-to-fine parallel generation: one forward pass per VQ level (9 levels), positions within level generated in parallel |
| **Training data** | Summarization (XSum), translation (WMT14 De→En), language modeling (LM1B, OpenWebText), story generation (TinyStories), Sudoku |
| **Python deps** | torch, numpy, omegaconf, hydra-core, transformers≥4.51, huggingface_hub[cli], rouge_score, sacrebleu |
| **Weights** | Hosted on HuggingFace; separate tokenizer.pt and generator.pt per task |

## Fundamental Mismatch

**NCM is a text generation acceleration framework, not a structured explanation system.**

NCM's purpose: generate natural language text faster than autoregressive models by predicting a hierarchy of discrete VQ codes from coarse to fine. It excels at summarization, translation, and language modeling.

What Superretometer needs: deterministic, data-bound explanations where every statement traces to a field in the CH report. No hallucination. No invented evidence. No upgraded warrant status.

These goals are incompatible:

1. **NCM generates free-form text** — it cannot guarantee that output statements correspond to input data fields. There is no mechanism to bind generated text to specific KO attributes.

2. **NCM has no structured output format** — it produces token sequences scored by ROUGE/BLEU. There is no schema to enforce "this sentence = this evidence item."

3. **NCM is probabilistic** — even with `top_k=1`, the VQ-VAE quantization introduces stochasticity at each level. The same frozen CH report could produce different explanations across runs.

4. **NCM requires GPU** — the evaluation script requires `CUDA_VISIBLE_DEVICES`. No CPU fallback. This makes it impractical for local CH analysis on machines without GPUs.

5. **Fine-tuning NCM for CH explanations would require** a dataset of (CH report → explanation) pairs, trained with the VQ-VAE tokenizer. This is a significant engineering effort with no guarantee of factual fidelity.

## Deterministic Template Baseline

The template-based approach (`explanation/templates.py`) produces:
- **Executive**: 1-page summary with warrant status, gate results, evidence count
- **Engineering**: Technical derivation chain, provenance, gate mechanics
- **Audit**: Provenance chain, independence analysis, contradiction detection

**Properties:**
- 100% deterministic: same input → same output
- Zero hallucination: every statement is a field access or count
- No GPU requirement: runs on CPU, pure Python
- Tested: 12/12 tests pass across 5 CH scenarios
- Latency: <1ms per explanation (pure string formatting)

## Comparison Matrix

| Criterion | Deterministic Template | NCM |
|-----------|----------------------|-----|
| Factual fidelity | 100% — every statement traces to input field | Unknown — LLM may invent facts |
| Unsupported claims | Impossible — no generation, only formatting | Likely — LLM fills gaps |
| Missing evidence | Explicitly reported as "0 item(s)" | May be glossed over |
| Reproducibility | Guaranteed — pure function of input | Stochastic across runs |
| Latency | <1ms | Seconds per explanation (GPU) |
| Resource use | Pure Python, no GPU | CUDA GPU required |
| Maintenance | Simple Python templates | Model weights, tokenizer, training pipeline |
| Anti-pattern detection | Built into template logic | Not understood by model |
| CH gate compliance | Templates encode gate semantics | Model has no concept of CH gates |

## Test Cases — Template Results

All 5 cases tested against the template baseline:

1. **CP-010 style (warranted, all gates pass)**: ✅ Correct warrant status, 3 evidence items, all gates PASS
2. **Unwarranted claim**: ✅ Shows incomplete gates, single evidence item
3. **Contradictory evidence**: ✅ Contradiction section identifies conflicting evidence
4. **Shared/non-independent roots**: ✅ Independence warning triggered
5. **Missing provenance**: ✅ No provenance section rendered, explanation still produced

## Recommendation: NO-GO

**Do not integrate NCM for CH explanation generation.**

Reasons:
1. **Fundamental mismatch**: NCM is for accelerating free-form text generation, not for structured, data-bound explanation production.
2. **No factual guarantee**: NCM cannot ensure that generated text corresponds to CH report fields. This violates the core Superretometer principle of traceable provenance.
3. **Resource cost**: Requires GPU, model weights, tokenizer training — significant infrastructure for no advantage.
4. **Deterministic baseline is superior**: The template approach is faster, more reliable, and produces verifiably correct output.

If the goal is richer natural language explanations, the correct path is:
- Extend the template system with configurable format options
- Add a post-processing step that renders templates as Markdown/HTML
- Keep all statement-to-field bindings explicit and testable

NCM does not improve upon this baseline for the Superretometer use case.
