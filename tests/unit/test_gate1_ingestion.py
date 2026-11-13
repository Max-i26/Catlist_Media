"""Gate 1 tests — dataset audit.

These tests MUST pass before proceeding to Milestone 2.
Run with: pytest tests/unit/test_gate1_ingestion.py -v

Gate 1 rule: a parser that runs without crashing does NOT pass this gate.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from meetingos.ingestion.parser import (
    ParsedMeeting,
    build_coverage_registry,
    discover_transcripts,
    ingest_all,
    parse_transcript,
    run_gate1_checks,
)
from meetingos.config import EXPECTED_FILE_COUNT, TRANSCRIPTS_DIR
from meetingos.models import CoverageStatus


# ---------------------------------------------------------------------------
# Fixtures: synthetic transcript text
# ---------------------------------------------------------------------------

MINIMAL_TRANSCRIPT = textwrap.dedent("""\
    Meeting: ES2008b
    Team: ES2008
    Meeting number: 2 (b) of the team's four meetings
    Speakers: Speaker A, Speaker B, Speaker C, Speaker D
    Times: turn start time from the start of the recording (HH:MM:SS)
    Source: AMI Meeting Corpus, CC BY 4.0

    00:00:49 Speaker A
    Good to see you all again.

    00:01:29 Speaker C
    Yep.

    00:01:31 Speaker B
    Right.
""")

LONG_TURN_TRANSCRIPT = textwrap.dedent("""\
    Meeting: ES2002a
    Team: ES2002
    Meeting number: 1 (a) of the team's four meetings
    Speakers: Speaker A, Speaker B
    Times: turn start time from the start of the recording (HH:MM:SS)
    Source: AMI Meeting Corpus, CC BY 4.0

    00:00:01 Speaker A
    """ + " ".join([f"word{i}" for i in range(800)]) + """

    00:10:00 Speaker B
    Short reply.
""")

MALFORMED_TRANSCRIPT = "This file has no meeting header or speaker turns."

MISSING_SPEAKER_TRANSCRIPT = textwrap.dedent("""\
    Meeting: TS3012a
    Team: TS3012
    Speakers: Speaker A, Speaker B, Speaker C, Speaker D
    Source: AMI Meeting Corpus, CC BY 4.0

    00:00:01 Speaker A
    Only speaker A appears.
""")


@pytest.fixture
def tmp_transcript_dir(tmp_path: Path) -> Path:
    return tmp_path


def write_transcript(directory: Path, filename: str, content: str) -> Path:
    path = directory / filename
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Unit: parse_transcript
# ---------------------------------------------------------------------------

class TestParseTranscript:

    def test_minimal_valid_transcript(self, tmp_path: Path) -> None:
        path = write_transcript(tmp_path, "ES2008b.txt", MINIMAL_TRANSCRIPT)
        meeting = parse_transcript(path)

        assert meeting.meeting_id == "ES2008b"
        assert meeting.team_id == "ES2008"
        assert meeting.meeting_sequence == "b"
        assert meeting.meeting_number == 2
        assert len(meeting.turns) == 3

    def test_speaker_ids_extracted(self, tmp_path: Path) -> None:
        path = write_transcript(tmp_path, "ES2008b.txt", MINIMAL_TRANSCRIPT)
        meeting = parse_transcript(path)
        speakers = {t.speaker_id for t in meeting.turns}
        assert speakers == {"A", "B", "C"}

    def test_text_preserved_exactly(self, tmp_path: Path) -> None:
        path = write_transcript(tmp_path, "ES2008b.txt", MINIMAL_TRANSCRIPT)
        meeting = parse_transcript(path)
        first_turn_text = meeting.turns[0].text
        assert "Good to see you all again" in first_turn_text

    def test_byte_offsets_nonzero(self, tmp_path: Path) -> None:
        path = write_transcript(tmp_path, "ES2008b.txt", MINIMAL_TRANSCRIPT)
        meeting = parse_transcript(path)
        for turn in meeting.turns:
            assert turn.byte_end > turn.byte_start

    def test_checksum_is_sha256(self, tmp_path: Path) -> None:
        path = write_transcript(tmp_path, "ES2008b.txt", MINIMAL_TRANSCRIPT)
        meeting = parse_transcript(path)
        assert len(meeting.source_checksum) == 64  # SHA-256 hex digest

    def test_malformed_transcript_raises(self, tmp_path: Path) -> None:
        path = write_transcript(tmp_path, "bad.txt", MALFORMED_TRANSCRIPT)
        with pytest.raises(ValueError):
            parse_transcript(path)

    def test_long_turn_preserved_fully(self, tmp_path: Path) -> None:
        """A 800-word turn must be stored completely in source memory."""
        path = write_transcript(tmp_path, "ES2002a.txt", LONG_TURN_TRANSCRIPT)
        meeting = parse_transcript(path)
        long_turn = max(meeting.turns, key=lambda t: t.word_count)
        assert long_turn.word_count >= 800

    def test_word_count_matches_text(self, tmp_path: Path) -> None:
        path = write_transcript(tmp_path, "ES2008b.txt", MINIMAL_TRANSCRIPT)
        meeting = parse_transcript(path)
        for turn in meeting.turns:
            expected = len(turn.text.split())
            assert turn.word_count == expected, \
                f"word_count {turn.word_count} != actual {expected}"

    def test_declared_speakers_vs_actual_speakers(self, tmp_path: Path) -> None:
        """Speaker A appears but C and D don't — declared vs actual mismatch."""
        path = write_transcript(tmp_path, "TS3012a.txt", MISSING_SPEAKER_TRANSCRIPT)
        meeting = parse_transcript(path)
        actual_speakers = {t.speaker_id for t in meeting.turns}
        assert "A" in actual_speakers
        assert "B" not in actual_speakers  # declared but absent

    def test_sequence_extracted_correctly(self, tmp_path: Path) -> None:
        for suffix, expected in [("a", "a"), ("b", "b"), ("c", "c"), ("d", "d")]:
            content = MINIMAL_TRANSCRIPT.replace("ES2008b", f"ES2008{suffix}")
            path = write_transcript(tmp_path, f"ES2008{suffix}.txt", content)
            m = parse_transcript(path)
            assert m.meeting_sequence == expected


# ---------------------------------------------------------------------------
# Unit: build_coverage_registry
# ---------------------------------------------------------------------------

class TestCoverageRegistry:

    def _make_meeting(self, meeting_id: str) -> ParsedMeeting:
        return ParsedMeeting(
            meeting_id=meeting_id,
            team_id=meeting_id[:-1],
            meeting_sequence=meeting_id[-1],
            meeting_number=None,
            declared_speakers=["A", "B"],
            source_file=f"{meeting_id}.txt",
            source_checksum="abc",
            turns=[],
        )

    def test_complete_team(self) -> None:
        meetings = [self._make_meeting(f"ES2002{s}") for s in "abcd"]
        registry = build_coverage_registry(meetings)
        cov = registry["ES2002"]
        assert cov.coverage_status == CoverageStatus.COMPLETE
        assert cov.missing_sequences == []

    def test_is1002_missing_a(self) -> None:
        """IS1002 has only b, c, d — mirrors actual corpus."""
        meetings = [self._make_meeting(f"IS1002{s}") for s in "bcd"]
        registry = build_coverage_registry(meetings)
        cov = registry["IS1002"]
        assert cov.coverage_status == CoverageStatus.PARTIAL
        assert "a" in cov.missing_sequences
        assert cov.has_missing_earliest()

    def test_is1005_missing_d(self) -> None:
        """IS1005 has only a, b, c — mirrors actual corpus."""
        meetings = [self._make_meeting(f"IS1005{s}") for s in "abc"]
        registry = build_coverage_registry(meetings)
        cov = registry["IS1005"]
        assert cov.coverage_status == CoverageStatus.PARTIAL
        assert "d" in cov.missing_sequences
        assert cov.has_missing_latest()

    def test_earliest_and_latest(self) -> None:
        meetings = [self._make_meeting(f"TS3012{s}") for s in "abcd"]
        registry = build_coverage_registry(meetings)
        cov = registry["TS3012"]
        assert cov.earliest_available == "a"
        assert cov.latest_available == "d"


# ---------------------------------------------------------------------------
# Unit: run_gate1_checks
# ---------------------------------------------------------------------------

class TestGate1Checks:

    def _make_minimal_state(
        self, tmp_path: Path, file_count: int = EXPECTED_FILE_COUNT
    ):
        """Build a minimal but valid gate1 state."""
        # Create dummy files to satisfy file count check
        files = []
        meetings = []
        for i in range(file_count):
            team = f"ES{2000 + i // 4}"
            seq = "abcd"[i % 4]
            mid = f"{team}{seq}"
            path = tmp_path / f"{mid}.txt"
            path.write_text(MINIMAL_TRANSCRIPT.replace("ES2008b", mid)
                            .replace("ES2008", team), encoding="utf-8")
            files.append(path)
            meetings.append(ParsedMeeting(
                meeting_id=mid,
                team_id=team,
                meeting_sequence=seq,
                meeting_number=None,
                declared_speakers=["A"],
                source_file=str(path),
                source_checksum="abc" * 20 + "abcd",  # 64 hex chars
                turns=[],
            ))
        from meetingos.ingestion.parser import build_coverage_registry
        coverage = build_coverage_registry(meetings)
        return files, meetings, coverage

    def test_wrong_file_count_fails(self, tmp_path: Path) -> None:
        files, meetings, coverage = self._make_minimal_state(tmp_path, file_count=100)
        failures = run_gate1_checks(files, meetings, coverage)
        assert any("Expected" in f and "found" in f for f in failures)

    def test_duplicate_meeting_id_fails(self, tmp_path: Path) -> None:
        files, meetings, coverage = self._make_minimal_state(tmp_path)
        meetings[0].meeting_id = meetings[1].meeting_id  # introduce duplicate
        failures = run_gate1_checks(files, meetings, coverage)
        assert any("Duplicate" in f for f in failures)

    def test_invalid_speaker_fails(self, tmp_path: Path) -> None:
        from meetingos.ingestion.parser import ParsedTurn
        path = write_transcript(tmp_path, "ES9999a.txt", MINIMAL_TRANSCRIPT.replace("ES2008b", "ES9999a"))
        meeting = ParsedMeeting(
            meeting_id="ES9999a",
            team_id="ES9999",
            meeting_sequence="a",
            meeting_number=None,
            declared_speakers=["Z"],  # invalid
            source_file=str(path),
            source_checksum="x" * 64,
            turns=[ParsedTurn(speaker_id="Z", timestamp=None, text="hi", byte_start=0, byte_end=10)],
        )
        failures = run_gate1_checks([path], [meeting], {})
        assert any("invalid speaker_id" in f or "declared speaker" in f for f in failures)


# ---------------------------------------------------------------------------
# Integration: ingest_all against real data
# ---------------------------------------------------------------------------

class TestIngestAllIntegration:
    """
    Integration tests against the real corpus.
    These only run when TRANSCRIPTS_DIR exists (CI can skip).
    """

    @pytest.mark.skipif(
        not TRANSCRIPTS_DIR.exists(),
        reason="Real corpus not present"
    )
    def test_gate1_passes_on_real_data(self) -> None:
        meetings, coverage, failures = ingest_all()
        assert failures == [], f"Gate 1 failures:\n" + "\n".join(failures)

    @pytest.mark.skipif(
        not TRANSCRIPTS_DIR.exists(),
        reason="Real corpus not present"
    )
    def test_correct_file_count(self) -> None:
        meetings, _, _ = ingest_all()
        assert len(meetings) == EXPECTED_FILE_COUNT

    @pytest.mark.skipif(
        not TRANSCRIPTS_DIR.exists(),
        reason="Real corpus not present"
    )
    def test_is1002_documented_as_partial(self) -> None:
        _, coverage, _ = ingest_all()
        assert "IS1002" in coverage
        assert coverage["IS1002"].coverage_status == CoverageStatus.PARTIAL
        assert "a" in coverage["IS1002"].missing_sequences

    @pytest.mark.skipif(
        not TRANSCRIPTS_DIR.exists(),
        reason="Real corpus not present"
    )
    def test_is1005_documented_as_partial(self) -> None:
        _, coverage, _ = ingest_all()
        assert "IS1005" in coverage
        assert coverage["IS1005"].coverage_status == CoverageStatus.PARTIAL
        assert "d" in coverage["IS1005"].missing_sequences

    @pytest.mark.skipif(
        not TRANSCRIPTS_DIR.exists(),
        reason="Real corpus not present"
    )
    def test_no_duplicate_meeting_ids(self) -> None:
        meetings, _, _ = ingest_all()
        ids = [m.meeting_id for m in meetings]
        assert len(ids) == len(set(ids)), "Duplicate meeting IDs found"

    @pytest.mark.skipif(
        not TRANSCRIPTS_DIR.exists(),
        reason="Real corpus not present"
    )
    def test_all_speakers_valid(self) -> None:
        meetings, _, _ = ingest_all()
        valid = {"A", "B", "C", "D"}
        for m in meetings:
            for t in m.turns:
                assert t.speaker_id in valid, \
                    f"{m.meeting_id}: invalid speaker '{t.speaker_id}'"

    @pytest.mark.skipif(
        not TRANSCRIPTS_DIR.exists(),
        reason="Real corpus not present"
    )
    def test_idempotent_ingestion(self) -> None:
        """Running ingest_all twice should produce the same meetings."""
        m1, _, _ = ingest_all()
        m2, _, _ = ingest_all()
        assert [m.meeting_id for m in m1] == [m.meeting_id for m in m2]
        assert [len(m.turns) for m in m1] == [len(m.turns) for m in m2]

    @pytest.mark.skipif(
        not TRANSCRIPTS_DIR.exists(),
        reason="Real corpus not present"
    )
    def test_max_turn_word_count_matches_known_distribution(self) -> None:
        """Max turn ≥ 700 words (we measured 736 in the real corpus)."""
        meetings, _, _ = ingest_all()
        all_turns = [t for m in meetings for t in m.turns]
        max_words = max(t.word_count for t in all_turns)
        assert max_words >= 700, \
            f"Expected max turn ≥ 700 words, got {max_words}"

    @pytest.mark.skipif(
        not TRANSCRIPTS_DIR.exists(),
        reason="Real corpus not present"
    )
    def test_long_turns_above_miniLM_limit(self) -> None:
        """At least 15 turns exceed 500 words (embedding truncation risk)."""
        meetings, _, _ = ingest_all()
        all_turns = [t for m in meetings for t in m.turns]
        over_500 = [t for t in all_turns if t.word_count > 500]
        assert len(over_500) >= 15, \
            f"Expected ≥15 turns > 500 words, found {len(over_500)}"
