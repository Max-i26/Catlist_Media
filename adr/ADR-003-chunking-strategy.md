# ADR-003: Chunking Strategy

**Date:** 2026-11-13
**Status:** Provisional — requires benchmark confirmation (Recall@10 measurement)
**Decision made by:** Architecture review

## Context

MeetingOS needs to convert speaker turns into retrieval units (chunks) that:
- Provide sufficient context for semantic retrieval (a single one-word reply "Yep." is not useful alone)
- Don't dilute semantic content by being too large
- Never split a speaker turn across two chunks
- Handle the longest turn in the corpus (736 words, ~980 tokens) without truncation

## Decision (Provisional Baseline)

**Sliding window over consecutive turns**, stride-based, with per-team meeting isolation.

- Chunk unit: N consecutive turns (N ∈ {3, 5, 8} for benchmarking)
- Stride: `window - 2` turns (2-turn overlap between adjacent chunks)
- Atomic unit: one speaker turn — never split
- Boundaries: never cross meeting boundaries

**Default after benchmarking (to be updated):** 5 turns, stride 3

## Corpus-Specific Findings

| Stat | Value |
|---|---|
| Total turns | 48,148 |
| Avg turn length | ~14 words |
| Max turn length | 736 words (~980 tokens) |
| Turns > 256 tokens (MiniLM limit) | ~64 turns |

The average turn is very short (~14 words). Window sizes of 3–5 turns are likely needed to provide meaningful context. An 8-turn window was included as a candidate in case the retrieval signals are too diluted at smaller windows.

## Long-Turn Handling

A turn exceeding `EMBEDDING_MAX_SEQ_LENGTH` gets split into overlapping segments for embedding, with each segment referencing the parent `turn_id`. Retrieval on any segment resolves back to the full original turn. This is non-negotiable: 64+ turns in the real corpus exceed MiniLM's 256-token limit.

## Alternatives Considered

| Alternative | Reason Rejected |
|---|---|
| Fixed-token chunks | Splits speaker turns mid-sentence; loses speaker attribution |
| Full meetings as chunks | Exceeds embedding context; loses precision |
| Sentence-level chunks | Too granular for conversational context; "Yep." is not retrievable |
| Semantic topic segmentation | Requires LLM per meeting; adds latency and cost to indexing |

## Measurement Protocol

For each window size (3, 5, 8):
1. Build FAISS index with that configuration
2. Run Recall@10 on 20 labelled (question, relevant_turns) pairs
3. Measure index size and retrieval latency (p50, p95)
4. Update `DEFAULT_CHUNK_WINDOW` and `CHUNK_STRIDE` in `config.py`
5. Record results in `outputs/chunking_benchmark.json`

## Review Trigger

Revisit if Recall@10 is below 90% with best candidate — consider topic-aware segmentation.
