"""Integration test for Gate 4 / Gate 5 Agent pipeline and Brief generation."""
from __future__ import annotations

import sqlite3
import pytest

from meetingos.agent.brief_generator import TS3012BriefGenerator
from meetingos.agent.checkpoint import CheckpointManager
from meetingos.agent.orchestrator import AgentOrchestrator
from meetingos.agent.planner import AgentPlanner
from meetingos.agent.synthesizer import EvidenceSynthesizer
from meetingos.agent.tools import AgentTools
from meetingos.config import DB_PATH, FAISS_DIR
from meetingos.memory.schema import get_connection
from meetingos.memory.source import SourceMemory
from meetingos.models import CitationResult
from meetingos.processing.embedder import TextEmbedder
from meetingos.processing.indexer import LexicalIndexer, TeamVectorIndexer
from meetingos.retrieval.hybrid import HybridRetriever
from meetingos.validation.citation_validator import validate_citation


@pytest.fixture(scope="module")
def agent_pipeline():
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

    brief_gen = TS3012BriefGenerator(conn, tools)

    yield orchestrator, brief_gen, conn
    conn.close()


class TestGate4AgentPipeline:

    def test_run_q01_ts3006(self, agent_pipeline):
        orchestrator, _, conn = agent_pipeline
        answer = orchestrator.run_question(
            question_id="Q01",
            question_text="Team TS3006 planned both an LCD screen and speech recognition. When the costs forced a cut, which of the two did they drop, which did they keep, and what reason was given for keeping it?",
            team_id="TS3006",
        )

        assert answer.question_id == "Q01"
        assert not answer.abstained
        assert 1 <= len(answer.citations) <= 3

        # Validate all citations
        for c in answer.citations:
            assert c.meeting_id.startswith("TS3006")
            val = validate_citation(c.meeting_id, c.quote, conn)
            assert val.result == CitationResult.VALID

    def test_run_q09_is1002_coverage_aware(self, agent_pipeline):
        orchestrator, _, conn = agent_pipeline
        answer = orchestrator.run_question(
            question_id="Q09",
            question_text="What selling price was Team IS1002 working with at first, what price range did they settle on later, and which speaker pushed hardest for a higher, more exclusive price?",
            team_id="IS1002",
        )

        assert answer.question_id == "Q09"
        # Must not fabricate citations for meeting IS1002a (which is known missing)
        for c in answer.citations:
            assert c.meeting_id != "IS1002a"
            val = validate_citation(c.meeting_id, c.quote, conn)
            assert val.result == CitationResult.VALID

    def test_ts3012_brief_generation(self, agent_pipeline):
        _, brief_gen, _ = agent_pipeline
        brief_text = brief_gen.generate_brief()

        assert len(brief_text) > 500
        assert "TS3012" in brief_text
        assert "TS3012d" in brief_text
        assert "25 Euro" in brief_text or "25 euro" in brief_text.lower()
        assert "titanium" in brief_text.lower()
        assert "battery" in brief_text.lower()
