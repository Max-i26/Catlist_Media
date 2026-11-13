"""Unit tests for agent execution state persistence and checkpointing."""
from __future__ import annotations

import sqlite3
import pytest

from meetingos.agent.checkpoint import CheckpointManager
from meetingos.memory.schema import DDL
from meetingos.models import AgentRunStatus


@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    yield conn
    conn.close()


class TestCheckpointManager:

    def test_create_and_fetch_run(self, mem_db: sqlite3.Connection):
        mgr = CheckpointManager(mem_db)
        run = mgr.create_run("Q01", run_id="run_test_01")
        assert run.run_id == "run_test_01"
        assert run.question_id == "Q01"
        assert run.status == AgentRunStatus.STARTED
        assert run.current_iteration == 0

        fetched = mgr.get_run("run_test_01")
        assert fetched is not None
        assert fetched.question_id == "Q01"
        assert fetched.status == AgentRunStatus.STARTED

    def test_set_status_and_iteration(self, mem_db: sqlite3.Connection):
        mgr = CheckpointManager(mem_db)
        run = mgr.create_run("Q02")
        mgr.set_status(run.run_id, AgentRunStatus.RETRIEVING, iteration=2)

        fetched = mgr.get_run(run.run_id)
        assert fetched is not None
        assert fetched.status == AgentRunStatus.RETRIEVING
        assert fetched.current_iteration == 2

    def test_record_tool_call(self, mem_db: sqlite3.Connection):
        mgr = CheckpointManager(mem_db)
        run = mgr.create_run("Q03")
        mgr.record_tool_call(run.run_id, "search_hybrid", {"query": "screen"}, "found 5 chunks")

        fetched = mgr.get_run(run.run_id)
        assert len(fetched.tool_call_history) == 1
        assert fetched.tool_call_history[0]["tool"] == "search_hybrid"
        assert fetched.tool_call_history[0]["args"] == {"query": "screen"}

    def test_add_retrieved_chunks_deduplication(self, mem_db: sqlite3.Connection):
        mgr = CheckpointManager(mem_db)
        run = mgr.create_run("Q04")
        mgr.add_retrieved_chunks(run.run_id, ["c1", "c2", "c3"])
        mgr.add_retrieved_chunks(run.run_id, ["c2", "c3", "c4"])

        fetched = mgr.get_run(run.run_id)
        assert fetched.retrieved_chunk_ids == ["c1", "c2", "c3", "c4"]

    def test_latest_run_for_question(self, mem_db: sqlite3.Connection):
        mgr = CheckpointManager(mem_db)
        r1 = mgr.create_run("Q05", run_id="run_1")
        r2 = mgr.create_run("Q05", run_id="run_2")

        latest = mgr.get_latest_run_for_question("Q05")
        assert latest is not None
        assert latest.run_id == "run_2"
