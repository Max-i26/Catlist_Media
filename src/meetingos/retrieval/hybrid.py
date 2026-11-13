"""Hybrid retrieval engine combining FTS5 BM25 and FAISS vector search with RRF.

Applies Reciprocal Rank Fusion (RRF) with k=60 to fuse lexical and semantic candidate sets.
Expands core chunks to full conversational turn context without losing source traceability.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Optional

from meetingos.config import MIN_MEETING_COVERAGE, RETRIEVAL_LIMIT, RRF_K
from meetingos.memory.source import SourceMemory
from meetingos.models import ExpandedEvidence, RetrievalResult
from meetingos.processing.indexer import LexicalIndexer, TeamVectorIndexer


class HybridRetriever:
    """Combines BM25 and vector search using Reciprocal Rank Fusion."""

    def __init__(
        self,
        lexical_indexer: LexicalIndexer,
        vector_indexer: TeamVectorIndexer,
        source_memory: SourceMemory,
        rrf_k: int = RRF_K,
    ):
        self.lexical = lexical_indexer
        self.vector = vector_indexer
        self.memory = source_memory
        self.rrf_k = rrf_k

    def retrieve(
        self,
        query: str,
        team_id: Optional[str] = None,
        limit: int = RETRIEVAL_LIMIT,
        min_meetings: int = MIN_MEETING_COVERAGE,
    ) -> list[RetrievalResult]:
        """
        Execute hybrid search with pre-retrieval team isolation and RRF fusion.

        Steps:
        1. Query BM25 via FTS5 (scoped to team_id if provided) -> rank 1..N
        2. Query Vector via FAISS (scoped to team_id if provided) -> rank 1..N
        3. Compute RRF score for all candidate chunk_ids:
           score(c) = sum(1 / (k + rank))
        4. Sort descending by RRF score
        5. Return top `limit` results
        """
        # 1. Lexical retrieval
        bm25_results = self.lexical.search(query, team_id=team_id, limit=limit * 2)

        # 2. Semantic retrieval (requires team_id for pre-retrieval isolation)
        vector_results = []
        if team_id:
            vector_results = self.vector.search_team(query, team_id=team_id, limit=limit * 2)

        # 3. RRF Fusion
        rrf_scores: dict[str, float] = defaultdict(float)
        chunk_metadata: dict[str, dict] = {}
        sources: dict[str, list[str]] = defaultdict(list)

        for item in bm25_results:
            cid = item["chunk_id"]
            rank = item["rank"]
            rrf_scores[cid] += 1.0 / (self.rrf_k + rank)
            sources[cid].append("bm25")
            if cid not in chunk_metadata:
                chunk_metadata[cid] = item

        for item in vector_results:
            cid = item["chunk_id"]
            rank = item["rank"]
            rrf_scores[cid] += 1.0 / (self.rrf_k + rank)
            sources[cid].append("vector")
            if cid not in chunk_metadata:
                chunk_metadata[cid] = item

        if not rrf_scores:
            return []

        # Sort descending by fused score
        sorted_cids = sorted(rrf_scores.keys(), key=lambda cid: rrf_scores[cid], reverse=True)

        results: list[RetrievalResult] = []
        for rank, cid in enumerate(sorted_cids[:limit], start=1):
            meta = chunk_metadata[cid]
            src_label = "+".join(sorted(set(sources[cid])))
            results.append(RetrievalResult(
                chunk_id=cid,
                meeting_id=meta["meeting_id"],
                team_id=meta["team_id"],
                score=rrf_scores[cid],
                source=src_label,
                rank=rank,
            ))

        return results

    def expand_evidence(
        self,
        retrieval_results: list[RetrievalResult],
        context_window: int = 2,
    ) -> list[ExpandedEvidence]:
        """
        Expand retrieval units into full conversational evidence.

        Resolves chunk_id to its core Turn objects and retrieves surrounding
        turns in the meeting for broader context.
        """
        expanded: list[ExpandedEvidence] = []

        for res in retrieval_results:
            # Fetch chunk from DB
            row = self.memory.conn.execute(
                "SELECT * FROM chunks WHERE chunk_id = ?",
                (res.chunk_id,),
            ).fetchone()
            if not row:
                continue

            import json
            turn_ids = json.loads(row["turn_ids"])
            core_turns = []
            for tid in turn_ids:
                t = self.memory.get_turn(tid)
                if t:
                    core_turns.append(t)

            if not core_turns:
                continue

            # Fetch context window
            first_turn_idx = core_turns[0].turn_index
            last_turn_idx = core_turns[-1].turn_index

            context_rows = self.memory.conn.execute(
                """
                SELECT * FROM turns
                WHERE meeting_id = ?
                  AND turn_index >= ? - ?
                  AND turn_index <= ? + ?
                ORDER BY turn_index ASC
                """,
                (res.meeting_id, first_turn_idx, context_window, last_turn_idx, context_window),
            ).fetchall()

            context_turns = [self.memory._row_to_turn(r) for r in context_rows]

            expanded.append(ExpandedEvidence(
                chunk_id=res.chunk_id,
                meeting_id=res.meeting_id,
                team_id=res.team_id,
                core_turns=core_turns,
                context_turns=context_turns,
            ))

        return expanded
