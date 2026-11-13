# ADR-001: Storage Backend — SQLite + FAISS

**Date:** 2026-11-13
**Status:** Accepted
**Decision made by:** Architecture review

## Context

MeetingOS requires:
- Persistent structured storage for turns, chunks, decisions, actions
- Exact full-text retrieval (BM25) with metadata filtering
- Approximate nearest-neighbour vector search with team-level isolation
- Zero external service dependencies for prototype deployment
- Testability (in-memory SQLite for unit tests)

## Decision

**SQLite (with FTS5)** for all structured and lexical storage.  
**FAISS (flat or IVF, one index per team)** for vector storage.

## Alternatives Considered

| Alternative | Reason Rejected |
|---|---|
| PostgreSQL + pgvector | External service, operational overhead for a prototype |
| Chroma / Qdrant | External service or added dependency; FTS5 already covers BM25 |
| DuckDB | Excellent for analytics but no native FTS; FAISS still needed alongside |
| Weaviate / Pinecone | Hosted service, network dependency, cost for 10K meetings at scale |

## Consequences

- **Good:** Zero-dependency deployment. SQLite in-memory mode makes unit tests fast and isolated.
- **Good:** FTS5 BM25 is built-in — no additional indexing service.
- **Good:** Per-team FAISS indexes enforce retrieval isolation pre-retrieval (not post).
- **Watch:** SQLite FTS5 external-content tables require trigger maintenance — implemented with explicit triggers in schema.
- **Watch:** FAISS does not support incremental index updates natively. For 10K meetings, evaluate switching to a metadata-aware vector engine (e.g. Qdrant with payload filters). The `vector_index_map` table is designed to make this migration possible without rewriting retrieval logic.
- **Watch:** At 10K meetings, SQLite WAL mode and proper indexing must be verified against latency targets.

## Review Trigger

Revisit this decision if: retrieval latency at 1,000 meetings exceeds the p95 targets in `config.py`, or if concurrent ingestion requirements emerge.
