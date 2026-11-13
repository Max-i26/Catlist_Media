"""Deterministic tool interface for the MeetingOS agent.

Provides structured, reproducible access to:
- Hybrid lexical/semantic retrieval with team isolation
- Conversational context expansion
- Source transcript turns and metadata
- Coverage registry
- Decision and action event memory
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from meetingos.memory.actions import ActionMemory
from meetingos.memory.decisions import DecisionMemory
from meetingos.memory.source import SourceMemory
from meetingos.models import (
    ActionEvent,
    DecisionEvent,
    ExpandedEvidence,
    RetrievalResult,
    TeamCoverage,
    Turn,
)
from meetingos.retrieval.hybrid import HybridRetriever


class AgentTools:
    """Registry of deterministic tools accessible to agent planning and orchestration."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        retriever: HybridRetriever,
        source_memory: Optional[SourceMemory] = None,
        decision_memory: Optional[DecisionMemory] = None,
        action_memory: Optional[ActionMemory] = None,
    ):
        self.conn = conn
        self.retriever = retriever
        self.source_memory = source_memory or SourceMemory(conn)
        self.decision_memory = decision_memory or DecisionMemory(conn)
        self.action_memory = action_memory or ActionMemory(conn)

    def search_hybrid(
        self,
        team_id: str,
        query: str,
        limit: int = 10,
        meeting_id: Optional[str] = None,
    ) -> list[RetrievalResult]:
        """
        Execute pre-retrieval team-isolated hybrid search (BM25 + FAISS via RRF).

        If meeting_id is specified, filters results to that specific meeting.
        """
        results = self.retriever.retrieve(
            query=query,
            team_id=team_id,
            limit=limit if not meeting_id else limit * 3,
        )
        if meeting_id:
            results = [r for r in results if r.meeting_id == meeting_id][:limit]
        return results

    def expand_chunks(
        self,
        chunk_ids: list[str],
        context_window: int = 2,
    ) -> list[ExpandedEvidence]:
        """Expand retrieved chunk IDs to core turns and surrounding context."""
        retrieval_results = []
        for i, cid in enumerate(chunk_ids):
            row = self.conn.execute(
                "SELECT meeting_id, team_id FROM chunks WHERE chunk_id = ?",
                (cid,),
            ).fetchone()
            if row:
                retrieval_results.append(
                    RetrievalResult(
                        chunk_id=cid,
                        meeting_id=row["meeting_id"],
                        team_id=row["team_id"],
                        score=1.0,
                        source="tool",
                        rank=i + 1,
                    )
                )
        return self.retriever.expand_evidence(
            retrieval_results,
            context_window=context_window,
        )

    def get_turn(self, turn_id: str) -> Optional[Turn]:
        """Fetch a single turn by its unique ID."""
        return self.source_memory.get_turn(turn_id)

    def get_turns_for_meeting(self, meeting_id: str) -> list[Turn]:
        """Retrieve all turns for a meeting in chronological order."""
        return self.source_memory.get_turns_for_meeting(meeting_id)

    def get_all_meetings_for_team(self, team_id: str) -> list[str]:
        """Return all distinct meeting IDs for a team in chronological order."""
        rows = self.conn.execute(
            """
            SELECT DISTINCT meeting_id
            FROM turns
            WHERE team_id = ?
            ORDER BY meeting_sequence ASC
            """,
            (team_id,),
        ).fetchall()
        return [r["meeting_id"] for r in rows]

    def get_team_coverage(self, team_id: str) -> Optional[TeamCoverage]:
        """Retrieve coverage registry status for a team."""
        return self.source_memory.get_team_coverage(team_id)

    def get_decision_history(
        self,
        team_id: str,
        topic: Optional[str] = None,
    ) -> list[DecisionEvent]:
        """Retrieve chronological decision events for a team/topic."""
        return self.decision_memory.get_events_for_team(team_id, topic=topic)

    def get_action_history(
        self,
        team_id: str,
    ) -> list[ActionEvent]:
        """Retrieve chronological action events for a team."""
        return self.action_memory.get_events_for_team(team_id)
