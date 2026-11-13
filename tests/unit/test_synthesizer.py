"""Unit tests for evidence synthesis and citation extraction."""
from __future__ import annotations

import sqlite3
import pytest

from meetingos.agent.synthesizer import EvidenceSynthesizer, SpeakerRoleDetector
from meetingos.config import DB_PATH
from meetingos.memory.schema import get_connection
from meetingos.models import Citation, CitationResult, Turn
from meetingos.validation.citation_validator import validate_citation


@pytest.fixture(scope="module")
def synth_fixture():
    if not DB_PATH.exists():
        pytest.skip("Source database not present")

    conn = get_connection(DB_PATH, readonly=True)
    synthesizer = EvidenceSynthesizer(conn)
    yield synthesizer, conn
    conn.close()


class TestSynthesizer:

    def test_speaker_role_detection(self, synth_fixture):
        synthesizer, _ = synth_fixture
        detector = synthesizer.role_detector
        roles_es2003 = detector.get_team_roles("ES2003")
        assert "A" in roles_es2003
        assert roles_es2003["A"] == "Project Manager"

        formatted_a = detector.format_speaker("ES2003", "A")
        assert "Speaker A (Project Manager)" == formatted_a

    def test_candidate_quote_extraction(self, synth_fixture):
        synthesizer, conn = synth_fixture
        turn = Turn(
            turn_id="turn_test",
            turn_index=0,
            meeting_id="TS3006d",
            team_id="TS3006",
            meeting_sequence="d",
            meeting_number=4,
            speaker_id="C",
            timestamp="00:10:00",
            timestamp_valid=True,
            text="We have not really integrated this speech into the system so we might as well drop that completely.",
            word_count=18,
            byte_offset_start=0,
            byte_offset_end=100,
            source_file="test.txt",
            source_checksum="sha256",
            ingested_at="2026-11-13T00:00:00Z",
        )
        quotes = synthesizer.extract_candidate_quotes(turn, keywords=["speech", "drop"])
        assert len(quotes) > 0
        assert any("speech" in q.lower() for q in quotes)
        assert all(len(q.split()) >= 6 for q in quotes)

    def test_sentence_count_validation(self, synth_fixture):
        synthesizer, _ = synth_fixture
        assert synthesizer.validate_answer_sentence_count("This is one sentence.") is True
        assert synthesizer.validate_answer_sentence_count("First sentence. Second sentence.") is True
        assert synthesizer.validate_answer_sentence_count("One. Two. Three.") is True
        assert synthesizer.validate_answer_sentence_count("One. Two. Three. Four.") is False
        assert synthesizer.validate_answer_sentence_count("") is False

    def test_abstention_output_contract(self, synth_fixture):
        synthesizer, _ = synth_fixture
        answer = synthesizer.build_abstention("Q99", "No evidence in corpus")
        assert answer.question_id == "Q99"
        assert answer.abstained is True
        assert answer.citations == []
        assert synthesizer.validate_answer_sentence_count(answer.answer) is True
