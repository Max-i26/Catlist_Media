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

    def test_coverage_guard_abstention_on_missing_kickoff(self, orchestrator_fixture):
        orchestrator, _ = orchestrator_fixture
        answer = orchestrator.run_question(
            question_id="TEST_IS1002_KICKOFF",
            question_text="What was decided during the kickoff meeting of Team IS1002?",
            team_id="IS1002",
        )
        assert answer.abstained is True
        assert len(answer.citations) == 0
        assert "IS1002a" in answer.answer
        assert "missing" in answer.answer.lower()
        assert orchestrator.synthesizer.validate_answer_sentence_count(answer.answer) is True

    def test_ts3006_dropped_feature_identified(self, orchestrator_fixture):
        orchestrator, conn = orchestrator_fixture
        answer = orchestrator.run_question(
            question_id="TEST_TS3006_DROP",
            question_text="What feature did Team TS3006 drop when budget constraints hit?",
            team_id="TS3006",
        )
        assert answer.abstained is False
        assert "speech recognition" in answer.answer.lower()
        assert "TS3006d" in answer.answer
        assert len(answer.citations) >= 1
        for c in answer.citations:
            assert c.meeting_id == "TS3006d"
            res = validate_citation(c.meeting_id, c.quote, conn)
            assert res.result == CitationResult.VALID
            assert len(c.quote.split()) >= 6
        assert orchestrator.synthesizer.validate_answer_sentence_count(answer.answer) is True

    def test_es2003_final_casing_material_identified(self, orchestrator_fixture):
        orchestrator, conn = orchestrator_fixture
        answer = orchestrator.run_question(
            question_id="TEST_ES2003_CASING",
            question_text="what remote casing material did Team ES2003 decide on in their final meeting?",
            team_id="ES2003",
        )
        assert answer.abstained is False
        assert "plastic" in answer.answer.lower()
        assert "ES2003d" in answer.answer
        assert len(answer.citations) >= 1
        for c in answer.citations:
            assert c.meeting_id == "ES2003d"
            res = validate_citation(c.meeting_id, c.quote, conn)
            assert res.result == CitationResult.VALID
            assert len(c.quote.split()) >= 6
        assert orchestrator.synthesizer.validate_answer_sentence_count(answer.answer) is True

    def test_rejected_proposal_never_overrides_later_accepted_decision(self, orchestrator_fixture):
        orchestrator, conn = orchestrator_fixture
        # Verify in decision memory that TS3006 speech_recognition ended in rejected state in TS3006d
        events = orchestrator.tools.get_decision_history("TS3006", topic="speech_recognition")
        assert len(events) >= 1
        latest_event = events[-1]
        assert latest_event["meeting_id"] == "TS3006d"
        assert latest_event["event_type"] == "rejected"
        assert "speech" in latest_event["description"].lower() or "speech" in str(latest_event["evidence_quotes"]).lower()
