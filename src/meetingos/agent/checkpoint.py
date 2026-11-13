"""Agent execution state persistence and checkpointing.

Stores and resumes execution state in the `agent_runs` SQLite table.
Enforces auditability, idempotency, and crash recovery for long-running workflows.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from meetingos.models import AgentRun, AgentRunStatus


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CheckpointManager:
    """Manages agent execution state checkpoints in SQLite."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create_run(self, question_id: str, run_id: Optional[str] = None) -> AgentRun:
        """Create and persist a new agent run record."""
        rid = run_id or f"run_{uuid.uuid4().hex[:12]}"
        now = _now_iso()
        run = AgentRun(
            run_id=rid,
            question_id=question_id,
            status=AgentRunStatus.STARTED,
            current_iteration=0,
            sub_questions=[],
            retrieved_chunk_ids=[],
            tool_call_history=[],
            error_details=None,
            started_at=now,
            updated_at=now,
        )
        self.save_run(run)
        return run

    def save_run(self, run: AgentRun) -> None:
        """Upsert an agent run state into the database."""
        now = _now_iso()
        run.updated_at = now
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO agent_runs (
                    run_id, question_id, status, current_iteration,
                    sub_questions, retrieved_chunk_ids, tool_call_history,
                    error_details, started_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.question_id,
                    run.status.value,
                    run.current_iteration,
                    json.dumps(run.sub_questions),
                    json.dumps(run.retrieved_chunk_ids),
                    json.dumps(run.tool_call_history),
                    run.error_details,
                    run.started_at,
                    run.updated_at,
                ),
            )

    def get_run(self, run_id: str) -> Optional[AgentRun]:
        """Fetch an existing agent run by its run ID."""
        row = self.conn.execute(
            """
            SELECT run_id, question_id, status, current_iteration,
                   sub_questions, retrieved_chunk_ids, tool_call_history,
                   error_details, started_at, updated_at
            FROM agent_runs WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if not row:
            return None
        return AgentRun(
            run_id=row["run_id"],
            question_id=row["question_id"],
            status=AgentRunStatus(row["status"]),
            current_iteration=row["current_iteration"],
            sub_questions=json.loads(row["sub_questions"] or "[]"),
            retrieved_chunk_ids=json.loads(row["retrieved_chunk_ids"] or "[]"),
            tool_call_history=json.loads(row["tool_call_history"] or "[]"),
            error_details=row["error_details"],
            started_at=row["started_at"],
            updated_at=row["updated_at"],
        )

    def get_latest_run_for_question(self, question_id: str) -> Optional[AgentRun]:
        """Fetch the most recent run for a specific question."""
        row = self.conn.execute(
            """
            SELECT run_id, question_id, status, current_iteration,
                   sub_questions, retrieved_chunk_ids, tool_call_history,
                   error_details, started_at, updated_at
            FROM agent_runs WHERE question_id = ?
            ORDER BY updated_at DESC LIMIT 1
            """,
            (question_id,),
        ).fetchone()
        if not row:
            return None
        return AgentRun(
            run_id=row["run_id"],
            question_id=row["question_id"],
            status=AgentRunStatus(row["status"]),
            current_iteration=row["current_iteration"],
            sub_questions=json.loads(row["sub_questions"] or "[]"),
            retrieved_chunk_ids=json.loads(row["retrieved_chunk_ids"] or "[]"),
            tool_call_history=json.loads(row["tool_call_history"] or "[]"),
            error_details=row["error_details"],
            started_at=row["started_at"],
            updated_at=row["updated_at"],
        )

    def set_status(
        self,
        run_id: str,
        status: AgentRunStatus,
        error_details: Optional[str] = None,
        iteration: Optional[int] = None,
    ) -> None:
        """Update the lifecycle status and optional error/iteration for a run."""
        run = self.get_run(run_id)
        if not run:
            raise KeyError(f"Run {run_id} not found in agent_runs")
        run.status = status
        if error_details is not None:
            run.error_details = error_details
        if iteration is not None:
            run.current_iteration = iteration
        self.save_run(run)

    def record_tool_call(
        self,
        run_id: str,
        tool_name: str,
        args: dict[str, Any],
        result_summary: str,
    ) -> None:
        """Append an audited tool call invocation to the execution history."""
        run = self.get_run(run_id)
        if not run:
            raise KeyError(f"Run {run_id} not found in agent_runs")
        run.tool_call_history.append(
            {
                "timestamp": _now_iso(),
                "tool": tool_name,
                "args": args,
                "result": result_summary,
            }
        )
        self.save_run(run)

    def add_retrieved_chunks(self, run_id: str, chunk_ids: list[str]) -> None:
        """Add new chunk IDs to the run's retrieved evidence set (deduplicated)."""
        run = self.get_run(run_id)
        if not run:
            raise KeyError(f"Run {run_id} not found in agent_runs")
        existing_set = set(run.retrieved_chunk_ids)
        for cid in chunk_ids:
            if cid not in existing_set:
                run.retrieved_chunk_ids.append(cid)
                existing_set.add(cid)
        self.save_run(run)
