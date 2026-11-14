# ADR-005: LLM Selection for Extraction and Synthesis

**Date:** 2026-11-13
**Status:** Provisional — requires benchmark confirmation
**Decision made by:** Architecture review

## Context

MeetingOS uses an LLM for three distinct tasks:
1. **Stage 1 extraction:** per-meeting candidate event identification (decisions, proposals, commitments, numeric figures)
2. **Stage 2 reconciliation:** cross-meeting temporal reasoning (supersession, contradiction, state derivation)
3. **Answer synthesis:** evidence-grounded answer generation with citation discipline

Each task has different requirements:
- Extraction: reliable structured output (JSON), consistent classification, low hallucination
- Reconciliation: temporal reasoning across 3–4 meetings per team
- Synthesis: factual accuracy, citation precision, controlled answer length

## Decision (Provisional)

**To be determined by benchmark.** No model is assumed.

Candidates to evaluate:
- `gemini-2.0-flash` / `gemini-1.5-pro`
- `claude-haiku-4-5` / `claude-sonnet-4-6`
- `gpt-4o-mini` / `gpt-4o`
- Local: `llama-3.1-8b` via Ollama (for cost comparison)

## Measurement Protocol

For each candidate, measure on a 20-question labelled sample:

| Metric | What It Measures |
|---|---|
| Extraction precision | % of extracted events with valid source evidence |
| Extraction recall | % of ground-truth events found |
| Structured output reliability | % of calls producing valid JSON on first attempt |
| Citation discipline | % of citations that pass deterministic validation |
| Answer factual accuracy | Manual evaluation vs. transcript |
| Tokens per meeting (Stage 1) | Input + output tokens for cost modelling |
| Latency p50 / p95 | Per call |

## Decision Rule

Select the model with highest citation discipline (must be ≥ 95% first-pass validity) and factual accuracy, within acceptable cost per 138-meeting run.

Do not select a model because it is the newest or scores well on generic benchmarks.

## Cost Modelling

Using measured 7,783 tokens/meeting average:
- Stage 1: 138 calls × ~8K input tokens + ~1K output tokens
- Stage 2: 35 calls × ~25K input tokens + ~2K output tokens (larger context per team)
- Synthesis: 25 calls × ~15K input + ~0.5K output

Actual costs will be measured and recorded in `outputs/cost_model.json`.

## Consequences

- Final model is pinned by version in `config.py` to ensure reproducibility
- If the model version is updated, a regression test must pass before switching
- For local models: no per-token API fee but compute time counted in cost model
