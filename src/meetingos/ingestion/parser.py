"""Gate 1 validation — dataset audit.

Run this before any other milestone. This module answers the question:
"Do we have all the data we expect, and can we trace every turn to its source?"

Pass condition: all assertions below exit cleanly.
Fail condition: any assertion raises AssertionError or any exception is raised.
A parser that runs without crashing does NOT pass this gate.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from meetingos.config import (
    EXPECTED_FILE_COUNT,
    EXPECTED_SEQUENCES,
    INCOMPLETE_TEAMS,
    TRANSCRIPTS_DIR,
)
from meetingos.models import TeamCoverage, CoverageStatus, Turn

# Regex patterns compiled once
_HEADER_MEETING    = re.compile(r"^Meeting:\s+(\S+)")
_HEADER_TEAM       = re.compile(r"^Team:\s+(\S+)")
_HEADER_MEETING_NO = re.compile(r"^Meeting number:\s+(\d+)")
_HEADER_SPEAKERS   = re.compile(r"^Speakers:\s+(.+)")
_TURN_LINE         = re.compile(r"^(\d{2}:\d{2}:\d{2}) (Speaker ([A-D]))$")


@dataclass
class ParsedTurn:
    """Intermediate structure — not yet assigned a turn_index."""
    speaker_id: str
    timestamp:  str | None
    text:       str
    byte_start: int
    byte_end:   int

    @property
    def word_count(self) -> int:
        return len(self.text.split())


@dataclass
class ParsedMeeting:
    """Everything extracted from one transcript file."""
    meeting_id:      str
    team_id:         str
    meeting_sequence: str
    meeting_number:  int | None
    declared_speakers: list[str]
    source_file:     str
    source_checksum: str
    turns:           list[ParsedTurn] = field(default_factory=list)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _extract_sequence(meeting_id: str) -> str:
    """'ES2008b' → 'b'"""
    return meeting_id[-1].lower()


def _extract_team(meeting_id: str) -> str:
    """'ES2008b' → 'ES2008'"""
    return meeting_id[:-1]


def parse_transcript(path: Path) -> ParsedMeeting:
    """
    Parse one transcript file into a ParsedMeeting.

    Raises:
        ValueError: if the file cannot be parsed into a valid meeting structure.
    """
    checksum = _sha256(path)
    raw_bytes = path.read_bytes()
    text_content = raw_bytes.decode("utf-8")
    lines = text_content.splitlines(keepends=True)

    meeting_id: str | None = None
    team_id: str | None = None
    meeting_number: int | None = None
    declared_speakers: list[str] = []
    turns: list[ParsedTurn] = []

    # Compute exact cumulative byte offsets per line from raw bytes
    byte_positions: list[int] = [0]
    for line in lines:
        byte_positions.append(byte_positions[-1] + len(line.encode("utf-8")))

    # Parse header block (lines before the first blank line following headers)
    in_header = True
    i = 0
    while i < len(lines) and in_header:
        line_clean = lines[i].strip()
        if m := _HEADER_MEETING.match(line_clean):
            meeting_id = m.group(1)
        elif m := _HEADER_TEAM.match(line_clean):
            team_id = m.group(1)
        elif m := _HEADER_MEETING_NO.match(line_clean):
            meeting_number = int(m.group(1))
        elif m := _HEADER_SPEAKERS.match(line_clean):
            raw = m.group(1)
            declared_speakers = [
                s.strip().split()[-1]
                for s in raw.split(",")
                if s.strip()
            ]
        elif line_clean == "" and meeting_id:
            in_header = False
        i += 1

    if not meeting_id:
        raise ValueError(f"No meeting_id found in {path.name}")
    if not team_id:
        team_id = _extract_team(meeting_id)

    # Parse turn blocks
    current_speaker: str | None = None
    current_timestamp: str | None = None
    current_text_lines: list[str] = []
    current_byte_start: int = 0

    def _flush_turn(end_byte: int) -> None:
        nonlocal current_speaker, current_timestamp, current_text_lines, current_byte_start
        if current_speaker is None:
            return
        text = " ".join(current_text_lines).strip()
        if not text:
            return
        turns.append(ParsedTurn(
            speaker_id=current_speaker,
            timestamp=current_timestamp,
            text=text,
            byte_start=current_byte_start,
            byte_end=end_byte,
        ))

    for idx, line in enumerate(lines):
        raw_line = line.rstrip("\r\n")
        if m := _TURN_LINE.match(raw_line):
            _flush_turn(byte_positions[idx])
            current_speaker = m.group(3)        # 'A', 'B', 'C', or 'D'
            current_timestamp = m.group(1)
            current_text_lines = []
            current_byte_start = byte_positions[idx]
        elif current_speaker is not None:
            stripped = raw_line.strip()
            if stripped:
                current_text_lines.append(stripped)

    _flush_turn(byte_positions[-1])

    if not turns:
        raise ValueError(f"No turns parsed from {path.name}")

    return ParsedMeeting(
        meeting_id=meeting_id,
        team_id=team_id,
        meeting_sequence=_extract_sequence(meeting_id),
        meeting_number=meeting_number,
        declared_speakers=declared_speakers,
        source_file=str(path),
        source_checksum=checksum,
        turns=turns,
    )


def discover_transcripts(directory: Path) -> list[Path]:
    """Return sorted list of .txt transcript files."""
    return sorted(directory.glob("*.txt"))


def build_coverage_registry(
    meetings: list[ParsedMeeting],
) -> dict[str, TeamCoverage]:
    """
    Build coverage registry from parsed meetings.

    IS1002 (missing 'a') and IS1005 (missing 'd') will appear as PARTIAL.
    """
    from collections import defaultdict
    team_sequences: dict[str, list[str]] = defaultdict(list)
    team_turns: dict[str, int] = defaultdict(int)

    for m in meetings:
        team_sequences[m.team_id].append(m.meeting_sequence)
        team_turns[m.team_id] += len(m.turns)

    registry: dict[str, TeamCoverage] = {}
    for team_id, available in team_sequences.items():
        available_sorted = sorted(available)

        # Always expect all 4 sequences (a, b, c, d).
        # Teams in INCOMPLETE_TEAMS are corpus-verified gaps — they ARE partial.
        # For all other teams, 4 available sequences = complete.
        expected = list(EXPECTED_SEQUENCES)
        missing = [s for s in expected if s not in available_sorted]

        registry[team_id] = TeamCoverage(
            team_id=team_id,
            expected_sequences=expected,
            available_sequences=available_sorted,
            missing_sequences=missing,
            coverage_status=CoverageStatus.COMPLETE if not missing else CoverageStatus.PARTIAL,
            earliest_available=available_sorted[0],
            latest_available=available_sorted[-1],
            total_turns=team_turns[team_id],
        )
    return registry


def run_gate1_checks(
    files: list[Path],
    meetings: list[ParsedMeeting],
    coverage: dict[str, TeamCoverage],
) -> list[str]:
    """
    Run all Gate 1 acceptance checks.

    Returns a list of failure messages. Empty list = gate passes.
    A parser that runs without crashing does NOT pass this gate.
    """
    failures: list[str] = []

    # 1. File count
    if len(files) != EXPECTED_FILE_COUNT:
        failures.append(
            f"Expected {EXPECTED_FILE_COUNT} files, found {len(files)}"
        )

    # 2. No parse failures (guaranteed by caller — any parse error surfaces as exception)

    # 3. No missing meeting IDs
    for m in meetings:
        if not m.meeting_id:
            failures.append(f"Missing meeting_id in {m.source_file}")

    # 4. No duplicate meeting IDs
    seen_ids: set[str] = set()
    for m in meetings:
        if m.meeting_id in seen_ids:
            failures.append(f"Duplicate meeting_id: {m.meeting_id}")
        seen_ids.add(m.meeting_id)

    # 5. All speaker labels preserved
    for m in meetings:
        actual_speakers = {t.speaker_id for t in m.turns}
        for sp in m.declared_speakers:
            if sp not in actual_speakers:
                failures.append(
                    f"{m.meeting_id}: declared speaker '{sp}' has no turns"
                )

    # 6. No empty turn texts
    for m in meetings:
        for t in m.turns:
            if not t.text.strip():
                failures.append(f"{m.meeting_id}: empty turn for speaker {t.speaker_id}")

    # 7. Byte offsets produce original text (spot check first and last turns across all meetings)
    for m in meetings:
        raw = Path(m.source_file).read_bytes()
        turns_to_check = m.turns[:2] + (m.turns[-2:] if len(m.turns) > 2 else [])
        for t in turns_to_check:
            excerpt = raw[t.byte_start:t.byte_end].decode("utf-8", errors="replace")
            words = t.text.split()
            if words and (words[0] not in excerpt or words[-1] not in excerpt):
                failures.append(
                    f"{m.meeting_id}: byte offset reconstruction mismatch "
                    f"for turn with speaker {t.speaker_id}"
                )

    # 8. Known incomplete teams documented correctly
    for team_id, expected_available in INCOMPLETE_TEAMS.items():
        if team_id not in coverage:
            failures.append(f"Known incomplete team {team_id} absent from coverage registry")
            continue
        cov = coverage[team_id]
        if cov.coverage_status != CoverageStatus.PARTIAL:
            failures.append(
                f"Team {team_id} should be PARTIAL coverage, got {cov.coverage_status}"
            )
        if sorted(cov.available_sequences) != sorted(expected_available):
            failures.append(
                f"Team {team_id} available sequences mismatch: "
                f"expected {expected_available}, got {cov.available_sequences}"
            )

    # 9. All turns have valid speaker IDs (A/B/C/D)
    valid_speakers = {"A", "B", "C", "D"}
    for m in meetings:
        for t in m.turns:
            if t.speaker_id not in valid_speakers:
                failures.append(
                    f"{m.meeting_id}: invalid speaker_id '{t.speaker_id}'"
                )

    return failures


def ingest_all(
    transcripts_dir: Path | None = None,
) -> tuple[list[ParsedMeeting], dict[str, TeamCoverage], list[str]]:
    """
    Full Gate 1 ingestion pipeline.

    Returns:
        (meetings, coverage_registry, gate1_failures)
        gate1_failures is empty on success.
    """
    directory = transcripts_dir or TRANSCRIPTS_DIR
    files = discover_transcripts(directory)

    meetings: list[ParsedMeeting] = []
    parse_errors: list[str] = []

    for f in files:
        try:
            meetings.append(parse_transcript(f))
        except Exception as exc:
            parse_errors.append(f"{f.name}: {exc}")

    coverage = build_coverage_registry(meetings)
    gate_failures = parse_errors + run_gate1_checks(files, meetings, coverage)

    return meetings, coverage, gate_failures
