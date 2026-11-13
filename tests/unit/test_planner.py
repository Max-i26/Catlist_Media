"""Unit tests for agent planning and coverage-aware question decomposition."""
from __future__ import annotations

import sqlite3
import pytest

from meetingos.agent.planner import AgentPlanner
from meetingos.agent.tools import AgentTools
from meetingos.config import DB_PATH, FAISS_DIR
from meetingos.memory.schema import get_connection
from meetingos.memory.source import SourceMemory
from meetingos.processing.embedder import TextEmbedder
from meetingos.processing.indexer import LexicalIndexer, TeamVectorIndexer
from meetingos.retrieval.hybrid import HybridRetriever


@pytest.fixture(scope="module")
def planner_fixture():
    if not DB_PATH.exists() or not FAISS_DIR.exists():
        pytest.skip("Gate 1/2 artifacts not present")

    conn = get_connection(DB_PATH, readonly=True)
    memory = SourceMemory(conn)
    lexical = LexicalIndexer(conn)
    embedder = TextEmbedder(lazy_load=False, use_mock=True)
    vector = TeamVectorIndexer(conn, embedder, index_dir=FAISS_DIR)
    retriever = HybridRetriever(lexical, vector, memory)
    tools = AgentTools(conn, retriever, source_memory=memory)
    planner = AgentPlanner(tools)

    yield planner, conn
    conn.close()


class TestAgentPlanner:

    def test_extract_team_id(self, planner_fixture):
        planner, _ = planner_fixture
        assert planner.extract_team_id("What did Team TS3006 decide?") == "TS3006"
        assert planner.extract_team_id("In team ES2003 meetings", explicit_team="ES2003") == "ES2003"
        assert planner.extract_team_id("Regarding IS1002 pricing") == "IS1002"

        with pytest.raises(ValueError, match="Could not determine team ID"):
            planner.extract_team_id("What was the overall budget?")

    def test_coverage_awareness_for_complete_team(self, planner_fixture):
        planner, _ = planner_fixture
        plan = planner.create_plan(
            question_id="Q01",
            question_text="Team TS3006 planned both an LCD screen and speech recognition.",
        )
        assert plan.team_id == "TS3006"
        assert plan.coverage.is_complete is True
        assert plan.coverage_warning is None
        assert len(plan.sub_questions) <= 6

    def test_coverage_awareness_for_partial_team_is1002(self, planner_fixture):
        planner, _ = planner_fixture
        plan = planner.create_plan(
            question_id="Q09",
            question_text="What selling price was Team IS1002 working with at first?",
        )
        assert plan.team_id == "IS1002"
        assert plan.coverage.is_complete is False
        assert "missing meeting a" in plan.coverage_warning
        assert plan.coverage.earliest_available == "b"

    def test_sub_question_decomposition_bounded(self, planner_fixture):
        planner, _ = planner_fixture
        plan = planner.create_plan(
            question_id="Q06",
            question_text="Team ES2008 wanted a feature to stop the remote getting lost. What happened to that feature, who raised the main objection to it, and what was the objection?",
        )
        assert 1 <= len(plan.sub_questions) <= 6
        aspects = [sq.aspect for sq in plan.sub_questions]
        assert "initial_proposal" in aspects
        assert "final_decision" in aspects
