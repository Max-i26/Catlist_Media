"""Ingestion Manifest generation and validation.

The manifest is an immutable record of what was ingested, file checksums,
counts, and coverage metadata. It acts as an audit trail for Gate 1.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from meetingos.config import EXPECTED_FILE_COUNT, INCOMPLETE_TEAMS
from meetingos.models import CoverageStatus, TeamCoverage


class FileManifestEntry(BaseModel):
    filename:         str
    meeting_id:       str
    team_id:          str
    meeting_sequence: str
    sha256:           str
    file_bytes:       int
    turn_count:       int
    word_count:       int


class TeamManifestEntry(BaseModel):
    team_id:             str
    coverage_status:     CoverageStatus
    available_sequences: list[str]
    missing_sequences:   list[str]
    total_turns:         int
    total_words:         int


class IngestionManifest(BaseModel):
    manifest_version:    str = "1.1"
    generated_at:        str
    corpus_source:       str = "AMI Meeting Corpus (Catalist reformatted)"
    total_files:         int
    total_meetings:      int
    total_teams:         int
    total_turns:         int
    total_words:         int
    expected_file_count: int = EXPECTED_FILE_COUNT
    incomplete_teams:    dict[str, list[str]] = Field(default_factory=lambda: INCOMPLETE_TEAMS)
    files:               list[FileManifestEntry]
    teams:               list[TeamManifestEntry]

    def to_json_file(self, path: Path) -> None:
        """Write manifest formatted as readable JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.model_dump(), indent=2),
            encoding="utf-8",
        )

    @classmethod
    def from_json_file(cls, path: Path) -> IngestionManifest:
        """Load manifest from JSON file."""
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)


def create_manifest(
    meetings: list[Any],  # list[ParsedMeeting]
    coverage: dict[str, TeamCoverage],
) -> IngestionManifest:
    """Create an IngestionManifest from parsed meetings and coverage registry."""
    files_entries: list[FileManifestEntry] = []
    total_words = 0
    total_turns = 0

    team_word_counts: dict[str, int] = {}

    for m in meetings:
        m_turns = len(m.turns)
        m_words = sum(t.word_count for t in m.turns)
        total_turns += m_turns
        total_words += m_words

        team_word_counts[m.team_id] = team_word_counts.get(m.team_id, 0) + m_words

        fpath = Path(m.source_file)
        files_entries.append(FileManifestEntry(
            filename=fpath.name,
            meeting_id=m.meeting_id,
            team_id=m.team_id,
            meeting_sequence=m.meeting_sequence,
            sha256=m.source_checksum,
            file_bytes=fpath.stat().st_size if fpath.exists() else 0,
            turn_count=m_turns,
            word_count=m_words,
        ))

    # Sort file entries deterministically
    files_entries.sort(key=lambda f: (f.team_id, f.meeting_sequence))

    team_entries: list[TeamManifestEntry] = []
    for team_id in sorted(coverage.keys()):
        cov = coverage[team_id]
        team_entries.append(TeamManifestEntry(
            team_id=team_id,
            coverage_status=cov.coverage_status,
            available_sequences=cov.available_sequences,
            missing_sequences=cov.missing_sequences,
            total_turns=cov.total_turns,
            total_words=team_word_counts.get(team_id, 0),
        ))

    return IngestionManifest(
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_files=len(files_entries),
        total_meetings=len(files_entries),
        total_teams=len(team_entries),
        total_turns=total_turns,
        total_words=total_words,
        files=files_entries,
        teams=team_entries,
    )
