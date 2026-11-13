"""Unit tests for bounded agent orchestration loop."""
from __future__ import annotations

import sqlite3
import pytest

from meetingos.agent.checkpoint import CheckpointManager
from meetingos.agent.orchestrator import AgentOrchestrator
from meetingos.agent.planner import AgentPlanner
from meetingos.agent.synthesizer import EvidenceSynthesizer
from meetingos.agent.tools import AgentTools
from meetingos.config import DB_PATH, FAISS_DIR
from meetingos.memory.schema import get_connection
from meetingos.memory.source import SourceMemory
from meetingos.models import AgentRunStatus, CitationResult
from meetingos.processing.embedder import TextEmbedder
from meetingos.processing.indexer import LexicalIndexer, TeamVectorIndexer
from meetingos.retrieval.hybrid import HybridRetriever
from meetingos.validation.citation_validator import validate_citation


@pytest.fixture(scope="module")
def orchestrator_fixture():
    if not DB_PATH.exists() or not FAISS_DIR.exists():
        pytest.skip("Gate 1/2 artifacts not present")

    conn = get_connection(DB_PATH, readonly=False)
    memory = SourceMemory(conn)
    lexical = LexicalIndexer(conn)
    embedder = TextEmbedder(lazy_load=False, use_mock=True)
    vector = TeamVectorIndexer(conn, embedder, index_dir=FAISS_DIR)
    retriever = HybridRetriever(lexical, vector, memory)
    tools = AgentTools(conn, retriever, source_memory=memory)
    planner = AgentPlanner(tools)
    synthesizer = EvidenceSynthesizer(conn)
    checkpoint_mgr = CheckpointManager(conn)

    orchestrator = AgentOrchestrator(
        conn=conn,
        tools=tools,
        planner=planner,
        synthesizer=synthesizer,
        checkpoint_mgr=checkpoint_mgr,
        max_iterations=4,
    )

    yield orchestrator, conn
    conn.close()


class TestAgentOrchestrator:

    def test_bounded_execution_and_checkpoint(self, orchestrator_fixture):
        orchestrator, conn = orchestrator_fixture
        answer = orchestrator.run_question(
            question_id="Q01",
            question_text="Team TS3006 planned both an LCD screen and speech recognition. When the costs forced a cut, which of the two did they drop?",
            team_id="TS3006",
        )

        assert answer.question_id == "Q01"
        assert len(answer.citations) <= 3

        # Check checkpoint status in DB
        checkpoint_mgr = CheckpointManager(conn)
        latest_run = checkpoint_mgr.get_latest_run_for_question("Q01")
        assert latest_run is not None
        assert latest_run.status in (AgentRunStatus.COMPLETE, AgentRunStatus.VALIDATING)
        assert latest_run.current_iteration <= 4
        assert len(latest_run.tool_call_history) > 0

    def test_citation_verifiability_guarantee(self, orchestrator_fixture):
        orchestrator, conn = orchestrator_fixture
        answer = orchestrator.run_question(
            question_id="Q02",
            question_text="Team ES2003 leaned towards one material for the case and then switched to another. What did they lean towards first, what did they end with, and why did they switch?",
            team_id="ES2003",
        )

        assert answer.question_id == "Q02"
        if not answer.abstained:
            assert len(answer.citations) >= 1
            for c in answer.citations:
                res = validate_citation(c.meeting_id, c.quote, conn)
                assert res.result == CitationResult.VALID, f"Citation failed validation: {c}"
                assert len(c.quote.split()) >= 6
