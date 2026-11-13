# ADR-004: Retrieval Fusion — Reciprocal Rank Fusion (RRF)

**Date:** 2026-11-13
**Status:** Accepted (subject to baseline comparison)
**Decision made by:** Architecture review

## Context

MeetingOS uses two retrieval signals:
- **BM25 (FTS5):** exact keyword matching, effective for specific terminology, speaker labels, meeting IDs
- **Vector search (FAISS):** semantic similarity, effective for paraphrased questions

A fusion method is needed to combine the two ranked lists into one candidate set.

## Decision

**Reciprocal Rank Fusion (RRF)** with $k = 60$.

$$\text{RRF}(d) = \sum_{r \in \text{rankings}} \frac{1}{k + \text{rank}(d, r)}$$

Each document's score is the sum of `1 / (k + rank)` across both ranked lists. Documents appearing in only one list get `1 / (k + limit + 1)` as their score from the absent list.

## Why RRF

- Does not require BM25 and vector scores to be on the same scale
- Not sensitive to outliers in either ranking
- Simple, interpretable, no training required
- Consistently performs well in hybrid retrieval literature

> [!IMPORTANT]
> SQLite FTS5 BM25 returns **negative scores** (lower = better rank). We use **rank position** (1 = best), not raw score, in the RRF formula. This is verified in the retrieval unit tests.

## Validation

RRF will be compared against:
1. BM25-only baseline
2. Vector-only baseline
3. Simple score sum (requires normalization)

Metric: Recall@10 on 20 labelled (question, relevant_chunks) pairs.

If RRF does not outperform both baselines on Recall@10, the fusion strategy will be revisited.

## Alternatives Considered

| Alternative | Reason Not Selected Now |
|---|---|
| Learned fusion (cross-encoder reranker) | Requires training data; adds LLM call latency |
| Linear score combination | Requires score normalization; sensitive to scale differences |
| Cascade (BM25 → rerank with vector) | May miss semantically similar but lexically different evidence |
| CombMNZ | Similar to RRF; RRF is simpler and well-validated |
