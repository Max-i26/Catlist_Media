"""Retrieval evaluation and metrics computation.

Measures:
- Recall@5 and Recall@10
- Mean Reciprocal Rank (MRR)
- Cross-team contamination (leakage) rate
- Multi-meeting coverage rate
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from meetingos.models import RetrievalResult
from meetingos.retrieval.hybrid import HybridRetriever


@dataclass
class RetrievalBenchmarkResult:
    query_id: str
    target_team: str
    target_meeting: str
    gold_keywords: list[str]
    retrieved_count: int
    hit_at_5: bool
    hit_at_10: bool
    reciprocal_rank: float
    cross_team_leakage: bool
    multi_meeting_found: bool


class RetrievalEvaluator:
    """Evaluates hybrid retrieval against ground-truth meeting targets."""

    def __init__(self, retriever: HybridRetriever, conn: sqlite3.Connection):
        self.retriever = retriever
        self.conn = conn

    def evaluate_query(
        self,
        query_id: str,
        query_text: str,
        target_team: str,
        target_meeting: str,
        gold_keywords: list[str],
        limit: int = 10,
    ) -> RetrievalBenchmarkResult:
        """Run hybrid retrieval and evaluate ranking and team isolation."""
        results = self.retriever.retrieve(
            query=query_text,
            team_id=target_team,
            limit=limit,
        )

        hit_at_5 = False
        hit_at_10 = False
        reciprocal_rank = 0.0
        cross_team_leakage = False
        retrieved_meetings = set()

        for rank, r in enumerate(results, start=1):
            if r.team_id != target_team:
                cross_team_leakage = True
            retrieved_meetings.add(r.meeting_id)

            # Check if this chunk is from the target meeting and contains gold keywords
            if r.meeting_id == target_meeting:
                row = self.conn.execute(
                    "SELECT text FROM chunks WHERE chunk_id = ?",
                    (r.chunk_id,),
                ).fetchone()
                if row:
                    text_lower = row["text"].lower()
                    if any(kw.lower() in text_lower for kw in gold_keywords):
                        if reciprocal_rank == 0.0:
                            reciprocal_rank = 1.0 / rank
                        if rank <= 5:
                            hit_at_5 = True
                        if rank <= 10:
                            hit_at_10 = True

        return RetrievalBenchmarkResult(
            query_id=query_id,
            target_team=target_team,
            target_meeting=target_meeting,
            gold_keywords=gold_keywords,
            retrieved_count=len(results),
            hit_at_5=hit_at_5,
            hit_at_10=hit_at_10,
            reciprocal_rank=reciprocal_rank,
            cross_team_leakage=cross_team_leakage,
            multi_meeting_found=len(retrieved_meetings) >= 2,
        )
