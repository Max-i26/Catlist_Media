"""Source memory access layer.

Authoritative source of truth: turns and team_coverage tables.
Handles global turn_index sequencing and stable turn_id generation.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from meetingos.models import CoverageStatus, TeamCoverage, Turn


class SourceMemory:
    """Manages raw conversation turns and team coverage in SQLite."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save_meetings(
        self,
        meetings: list[Any],  # list[ParsedMeeting]
        coverage: dict[str, TeamCoverage],
    ) -> int:
        """
        Store parsed meetings into turns and team_coverage tables.

        Assigns a global, monotonically increasing turn_index across all turns,
        ordered by (team_id, meeting_sequence, turn_in_meeting).
        Generates deterministic turn_id: {meeting_id}_{speaker_id}_{seq_in_meeting:04d}.

        Idempotent: replaces existing records cleanly.
        Returns total number of inserted turns.
        """
        # Sort meetings deterministically
        sorted_meetings = sorted(
            meetings,
            key=lambda m: (m.team_id, m.meeting_sequence)
        )

        ingested_at = datetime.now(timezone.utc).isoformat()
        turns_to_insert = []
        global_idx = 0

        for m in sorted_meetings:
            for seq_in_meeting, pt in enumerate(m.turns, start=1):
                turn_id = f"{m.meeting_id}_{pt.speaker_id}_{seq_in_meeting:04d}"
                turns_to_insert.append((
                    turn_id,
                    global_idx,
                    m.meeting_id,
                    m.team_id,
                    m.meeting_sequence,
                    m.meeting_number,
                    pt.speaker_id,
                    pt.timestamp,
                    1 if pt.timestamp else 0,
                    pt.text,
                    pt.word_count,
                    pt.byte_start,
                    pt.byte_end,
                    m.source_file,
                    m.source_checksum,
                    ingested_at,
                ))
                global_idx += 1

        with self.conn:
            # Insert turns
            self.conn.executemany(
                """
                INSERT OR REPLACE INTO turns (
                    turn_id, turn_index, meeting_id, team_id, meeting_sequence,
                    meeting_number, speaker_id, timestamp, timestamp_valid,
                    text, word_count, byte_offset_start, byte_offset_end,
                    source_file, source_checksum, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                turns_to_insert,
            )

            # Insert team coverage
            coverage_to_insert = [
                (
                    cov.team_id,
                    json.dumps(cov.expected_sequences),
                    json.dumps(cov.available_sequences),
                    json.dumps(cov.missing_sequences),
                    cov.coverage_status.value,
                    cov.earliest_available,
                    cov.latest_available,
                    cov.total_turns,
                )
                for cov in coverage.values()
            ]

            self.conn.executemany(
                """
                INSERT OR REPLACE INTO team_coverage (
                    team_id, expected_sequences, available_sequences, missing_sequences,
                    coverage_status, earliest_available, latest_available, total_turns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                coverage_to_insert,
            )

        return len(turns_to_insert)

    def get_turn(self, turn_id: str) -> Optional[Turn]:
        """Fetch turn by ID."""
        row = self.conn.execute(
            "SELECT * FROM turns WHERE turn_id = ?",
            (turn_id,),
        ).fetchone()
        return self._row_to_turn(row) if row else None

    def get_turn_by_index(self, turn_index: int) -> Optional[Turn]:
        """Fetch turn by global turn_index."""
        row = self.conn.execute(
            "SELECT * FROM turns WHERE turn_index = ?",
            (turn_index,),
        ).fetchone()
        return self._row_to_turn(row) if row else None

    def get_turns_for_meeting(self, meeting_id: str) -> list[Turn]:
        """Fetch all turns for a meeting in chronological order."""
        rows = self.conn.execute(
            "SELECT * FROM turns WHERE meeting_id = ? ORDER BY turn_index ASC",
            (meeting_id,),
        ).fetchall()
        return [self._row_to_turn(r) for r in rows]

    def get_turns_for_team(self, team_id: str) -> list[Turn]:
        """Fetch all turns for a team across all its meetings in chronological order."""
        rows = self.conn.execute(
            "SELECT * FROM turns WHERE team_id = ? ORDER BY turn_index ASC",
            (team_id,),
        ).fetchall()
        return [self._row_to_turn(r) for r in rows]

    def get_context_window(
        self,
        meeting_id: str,
        turn_index: int,
        before: int = 2,
        after: int = 2,
    ) -> list[Turn]:
        """Fetch turns surrounding turn_index within the same meeting."""
        rows = self.conn.execute(
            """
            SELECT * FROM turns
            WHERE meeting_id = ?
              AND turn_index >= ? - ?
              AND turn_index <= ? + ?
            ORDER BY turn_index ASC
            """,
            (meeting_id, turn_index, before, turn_index, after),
        ).fetchall()
        return [self._row_to_turn(r) for r in rows]

    def get_team_coverage(self, team_id: str) -> Optional[TeamCoverage]:
        """Fetch coverage record for a team."""
        row = self.conn.execute(
            "SELECT * FROM team_coverage WHERE team_id = ?",
            (team_id,),
        ).fetchone()
        if not row:
            return None
        return TeamCoverage(
            team_id=row["team_id"],
            expected_sequences=json.loads(row["expected_sequences"]),
            available_sequences=json.loads(row["available_sequences"]),
            missing_sequences=json.loads(row["missing_sequences"]),
            coverage_status=CoverageStatus(row["coverage_status"]),
            earliest_available=row["earliest_available"],
            latest_available=row["latest_available"],
            total_turns=row["total_turns"],
        )

    def list_all_coverage(self) -> dict[str, TeamCoverage]:
        """Fetch all team coverage records."""
        rows = self.conn.execute(
            "SELECT * FROM team_coverage ORDER BY team_id ASC"
        ).fetchall()
        result = {}
        for row in rows:
            result[row["team_id"]] = TeamCoverage(
                team_id=row["team_id"],
                expected_sequences=json.loads(row["expected_sequences"]),
                available_sequences=json.loads(row["available_sequences"]),
                missing_sequences=json.loads(row["missing_sequences"]),
                coverage_status=CoverageStatus(row["coverage_status"]),
                earliest_available=row["earliest_available"],
                latest_available=row["latest_available"],
                total_turns=row["total_turns"],
            )
        return result

    def count_turns(self) -> int:
        """Count total turns stored in DB."""
        row = self.conn.execute("SELECT COUNT(*) AS cnt FROM turns").fetchone()
        return row["cnt"]

    def count_meetings(self) -> int:
        """Count unique meetings stored in DB."""
        row = self.conn.execute("SELECT COUNT(DISTINCT meeting_id) AS cnt FROM turns").fetchone()
        return row["cnt"]

    def count_teams(self) -> int:
        """Count unique teams stored in DB."""
        row = self.conn.execute("SELECT COUNT(DISTINCT team_id) AS cnt FROM turns").fetchone()
        return row["cnt"]

    def reconstruct_turn_text(self, turn: Turn) -> str:
        """
        Slice the raw source file using stored byte offsets and return decoded text.
        Guarantees 100% source traceability.
        """
        raw = Path(turn.source_file).read_bytes()
        return raw[turn.byte_offset_start:turn.byte_offset_end].decode("utf-8", errors="replace")

    @staticmethod
    def _row_to_turn(row: sqlite3.Row) -> Turn:
        return Turn(
            turn_id=row["turn_id"],
            turn_index=row["turn_index"],
            meeting_id=row["meeting_id"],
            team_id=row["team_id"],
            meeting_sequence=row["meeting_sequence"],
            meeting_number=row["meeting_number"],
            speaker_id=row["speaker_id"],
            timestamp=row["timestamp"],
            timestamp_valid=bool(row["timestamp_valid"]),
            text=row["text"],
            word_count=row["word_count"],
            byte_offset_start=row["byte_offset_start"],
            byte_offset_end=row["byte_offset_end"],
            source_file=row["source_file"],
            source_checksum=row["source_checksum"],
            ingested_at=row["ingested_at"],
        )
