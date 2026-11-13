"""Unit tests for citation validator.

Gate 5 requirement: test differences in case, repeated spaces, tabs,
newlines, punctuation, Unicode, short quotes, and quotations appearing
in multiple meetings.

These tests are DETERMINISTIC — no LLM involved.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from meetingos.validation.citation_validator import (
    CitationValidationResult,
    normalize_for_matching,
    validate_citation,
    citation_validity_rate,
)
from meetingos.models import CitationResult


# ---------------------------------------------------------------------------
# Fixtures: in-memory SQLite with synthetic source turns
# ---------------------------------------------------------------------------

@pytest.fixture
def db() -> sqlite3.Connection:
    """In-memory SQLite with minimal schema and synthetic turns."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE turns (
            turn_id TEXT PRIMARY KEY,
            meeting_id TEXT NOT NULL,
            team_id TEXT NOT NULL,
            meeting_sequence TEXT NOT NULL,
            meeting_number INTEGER,
            speaker_id TEXT NOT NULL,
            timestamp TEXT,
            timestamp_valid INTEGER NOT NULL DEFAULT 1,
            text TEXT NOT NULL,
            word_count INTEGER NOT NULL,
            byte_offset_start INTEGER NOT NULL DEFAULT 0,
            byte_offset_end INTEGER NOT NULL DEFAULT 0,
            source_file TEXT NOT NULL DEFAULT '',
            source_checksum TEXT NOT NULL DEFAULT '',
            ingested_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00',
            turn_index INTEGER NOT NULL DEFAULT 0
        );
    """)
    # Synthetic source turns
    turns = [
        ("ES2008b_A_0001", "ES2008b", "ES2008", "b", "A",
         "We should change the design of the button layout completely."),
        ("ES2008b_B_0002", "ES2008b", "ES2008", "b", "B",
         "I agree, the current layout is too complicated for users."),
        ("ES2008c_A_0001", "ES2008c", "ES2008", "c", "A",
         "We decided to keep the original button layout after all."),
        ("TS3012a_A_0001", "TS3012a", "TS3012", "a", "A",
         "The team agreed on a rubber case for the remote control device."),
        ("TS3012b_C_0001", "TS3012b", "TS3012", "b", "C",
         "Speaker C mentioned   extra   spaces in this transcript turn."),
    ]
    conn.executemany(
        """INSERT INTO turns
           (turn_id, meeting_id, team_id, meeting_sequence, speaker_id, text, word_count)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [(t[0], t[1], t[2], t[3], t[4], t[5], len(t[5].split())) for t in turns],
    )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Tests: normalize_for_matching
# ---------------------------------------------------------------------------

class TestNormalizeForMatching:

    def test_case_insensitive(self) -> None:
        assert normalize_for_matching("HELLO World") == normalize_for_matching("hello world")

    def test_collapse_multiple_spaces(self) -> None:
        assert normalize_for_matching("a  b   c") == "a b c"

    def test_collapse_tabs(self) -> None:
        assert normalize_for_matching("a\tb") == "a b"

    def test_collapse_newlines(self) -> None:
        assert normalize_for_matching("a\nb") == "a b"

    def test_unicode_casefold(self) -> None:
        # German ß → ss in casefold
        assert normalize_for_matching("Straße") == normalize_for_matching("strasse")

    def test_empty_string(self) -> None:
        assert normalize_for_matching("") == ""

    def test_leading_trailing_whitespace_stripped(self) -> None:
        assert normalize_for_matching("  hello  ") == "hello"


# ---------------------------------------------------------------------------
# Tests: validate_citation — happy path
# ---------------------------------------------------------------------------

class TestValidateCitationValid:

    def test_exact_match(self, db: sqlite3.Connection) -> None:
        result = validate_citation("ES2008b", "change the design of the button", db)
        assert result.result == CitationResult.VALID
        assert result.matched_turn_id == "ES2008b_A_0001"

    def test_case_insensitive_match(self, db: sqlite3.Connection) -> None:
        result = validate_citation("ES2008b", "CHANGE THE DESIGN OF THE BUTTON", db)
        assert result.result == CitationResult.VALID

    def test_whitespace_normalized_match(self, db: sqlite3.Connection) -> None:
        """Quote with extra spaces should match the turn with extra spaces."""
        result = validate_citation(
            "TS3012b",
            "Speaker C mentioned extra spaces in this",
            db,
        )
        assert result.result == CitationResult.VALID

    def test_mid_turn_quote(self, db: sqlite3.Connection) -> None:
        result = validate_citation("ES2008b", "current layout is too complicated for users", db)
        assert result.result == CitationResult.VALID

    def test_quote_from_second_meeting(self, db: sqlite3.Connection) -> None:
        result = validate_citation("ES2008c", "keep the original button layout after all", db)
        assert result.result == CitationResult.VALID

    def test_matched_turn_id_returned(self, db: sqlite3.Connection) -> None:
        result = validate_citation("TS3012a", "agreed on a rubber case for the remote", db)
        assert result.matched_turn_id == "TS3012a_A_0001"

    def test_original_quote_preserved_in_result(self, db: sqlite3.Connection) -> None:
        """The result.quote must be the ORIGINAL string, not normalized."""
        original = "CHANGE THE DESIGN of the button layout"
        result = validate_citation("ES2008b", original, db)
        assert result.quote == original  # never normalized in output


# ---------------------------------------------------------------------------
# Tests: validate_citation — failure cases
# ---------------------------------------------------------------------------

class TestValidateCitationFailures:

    def test_meeting_not_found(self, db: sqlite3.Connection) -> None:
        result = validate_citation("NONEXISTENT", "some words here to pass length", db)
        assert result.result == CitationResult.MEETING_NOT_FOUND

    def test_quote_not_in_meeting(self, db: sqlite3.Connection) -> None:
        result = validate_citation("ES2008b", "rubber case for the remote control", db)
        # This quote exists in TS3012a, NOT ES2008b
        assert result.result == CitationResult.QUOTE_NOT_FOUND

    def test_quote_too_short_five_words(self, db: sqlite3.Connection) -> None:
        result = validate_citation("ES2008b", "change the design", db)
        # Only 3 words — below minimum 6
        assert result.result == CitationResult.QUOTE_TOO_SHORT

    def test_quote_exactly_six_words_valid(self, db: sqlite3.Connection) -> None:
        result = validate_citation("ES2008b", "change the design of the button", db)
        assert result.result == CitationResult.VALID  # exactly 6 words

    def test_quote_from_wrong_team_fails(self, db: sqlite3.Connection) -> None:
        """Quote from TS3012a cited as ES2008b must fail."""
        result = validate_citation(
            "ES2008b",
            "agreed on a rubber case for the remote",
            db,
        )
        assert result.result == CitationResult.QUOTE_NOT_FOUND

    def test_paraphrase_fails(self, db: sqlite3.Connection) -> None:
        """A paraphrase is not an exact substring match."""
        result = validate_citation(
            "ES2008b",
            "they wanted to redesign the buttons entirely",
            db,
        )
        assert result.result == CitationResult.QUOTE_NOT_FOUND


# ---------------------------------------------------------------------------
# Tests: citation_validity_rate
# ---------------------------------------------------------------------------

class TestCitationValidityRate:

    def test_all_valid(self, db: sqlite3.Connection) -> None:
        answers = [
            {
                "question_id": "Q01",
                "citations": [
                    {"meeting_id": "ES2008b", "quote": "change the design of the button layout"},
                ],
            }
        ]
        from meetingos.validation.citation_validator import validate_all_citations
        results = validate_all_citations(answers, db)
        rate = citation_validity_rate(results)
        assert rate == 100.0

    def test_mixed_validity(self, db: sqlite3.Connection) -> None:
        answers = [
            {
                "question_id": "Q01",
                "citations": [
                    {"meeting_id": "ES2008b", "quote": "change the design of the button layout"},
                    {"meeting_id": "NONEXISTENT", "quote": "this meeting does not exist"},
                ],
            }
        ]
        from meetingos.validation.citation_validator import validate_all_citations
        results = validate_all_citations(answers, db)
        rate = citation_validity_rate(results)
        assert rate == 50.0

    def test_no_citations(self, db: sqlite3.Connection) -> None:
        answers = [{"question_id": "Q01", "citations": []}]
        from meetingos.validation.citation_validator import validate_all_citations
        results = validate_all_citations(answers, db)
        rate = citation_validity_rate(results)
        assert rate == 0.0  # zero citations → zero valid → 0%
