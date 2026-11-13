# ADR-002: Embedding Model Selection

**Date:** 2026-11-13
**Status:** Provisional — requires benchmark confirmation
**Decision made by:** Architecture review

## Context

MeetingOS requires a sentence embedding model that:
- Runs locally (no per-token API cost for 48,148 turns × multiple chunks)
- Has a sufficient context window for the actual corpus (max turn = 736 words / ~980 tokens)
- Produces embeddings suitable for semantic retrieval of conversational text
- Has a known, stable `max_seq_length` we can verify at runtime

**Corpus-specific constraint discovered:** Max observed turn is **736 words (~980 tokens)**.  
`all-MiniLM-L6-v2` has `max_seq_length = 256` tokens — shorter than 64 turns in our corpus.  
The long-turn splitting strategy handles this, but a model with longer context would reduce the number of splits needed.

## Decision (Provisional Baseline)

**`sentence-transformers/all-MiniLM-L6-v2`** as the benchmark baseline.

This is chosen for benchmarking, not because it is assumed optimal. After running Recall@10 measurements on a labelled retrieval set, this decision will be updated.

## Candidates to Benchmark

| Model | Dim | Max Tokens | Notes |
|---|---|---|---|
| `all-MiniLM-L6-v2` | 384 | 256 | Baseline; fast; well-understood |
| `all-mpnet-base-v2` | 768 | 514 | Better quality; slower; covers more turns natively |
| `multi-qa-MiniLM-L6-cos-v1` | 384 | 512 | Trained on Q&A pairs; potentially better for retrieval |
| `all-MiniLM-L12-v2` | 384 | 256 | Deeper than L6; same context limit |

## Measurement Protocol

For each candidate:
1. Measure `model.max_seq_length` at runtime — do not trust advertised values
2. Embed all 138 meetings' chunks
3. Measure: Recall@10, Recall@5, MRR on 20 manually labelled (question, relevant_chunks) pairs
4. Measure: embedding throughput (turns/second), index size, search latency p50/p95
5. Record results in `outputs/embedding_benchmark.json`

## Decision Rule

Select the model with highest Recall@10 that also meets the latency target (<500ms p95 for vector retrieval). If two models are within 2% on Recall@10, prefer the faster one.

## Consequences

- Final decision will update `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `EMBEDDING_MAX_SEQ_LENGTH` in `config.py`
- All existing FAISS indexes must be rebuilt when model changes — `embedding_configs` table tracks this
- Mixing embeddings from different models in one FAISS index is **not permitted**

## Review Trigger

Revisit if Recall@10 is below 90% with best candidate — consider fine-tuned models on conversational AMI data.
