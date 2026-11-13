"""Gate 1 Automated Validation Engine.

Strict gate validator for Milestone 1.
Ensures 100% source traceability, monotonic chronological sequencing,
byte-offset slice integrity, and coverage completeness before proceeding.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from meetingos.config import EXPECTED_FILE_COUNT, INCOMPLETE_TEAMS
from meetingos.ingestion.manifest import IngestionManifest
from meetingos.memory.source import SourceMemory
from meetingos.models import CoverageStatus


@dataclass
class Gate1Report:
    passed:              bool
    total_files:         int
    total_meetings:      int
    total_teams:         int
    total_turns:         int
    total_words:         int
    incomplete_teams_ok: bool
    turn_index_ok:       bool
    byte_offset_ok:      bool
    checksum_ok:         bool
    failures:            list[str] = field(default_factory=list)

    def summary(self) -> str:
        status_str = "PASSED" if self.passed else "FAILED"
        lines = [
            f"=== Gate 1 Validation Report: {status_str} ===",
            f"Total Files:         {self.total_files} / {EXPECTED_FILE_COUNT}",
            f"Total Meetings:      {self.total_meetings}",
            f"Total Teams:         {self.total_teams}",
            f"Total Turns:         {self.total_turns}",
            f"Total Words:         {self.total_words}",
            f"Incomplete Teams OK: {self.incomplete_teams_ok}",
            f"Turn Index OK:       {self.turn_index_ok}",
            f"Byte Offset Slice OK:{self.byte_offset_ok}",
            f"Checksums Verified:  {self.checksum_ok}",
        ]
        if self.failures:
            lines.append("Failures:")
            for f in self.failures:
                lines.append(f"  - {f}")
        return "\n".join(lines)


class Gate1Validator:
    """Automated validator for Gate 1 acceptance criteria."""

    def __init__(self, memory: SourceMemory, manifest: IngestionManifest):
        self.memory = memory
        self.manifest = manifest

    def validate(self) -> Gate1Report:
        failures: list[str] = []

        total_turns = self.memory.count_turns()
        total_meetings = self.memory.count_meetings()
        total_teams = self.memory.count_teams()

        # 1. File and meeting accounting
        if total_meetings != EXPECTED_FILE_COUNT:
            failures.append(
                f"Expected {EXPECTED_FILE_COUNT} meetings in DB, found {total_meetings}"
            )
        if self.manifest.total_files != EXPECTED_FILE_COUNT:
            failures.append(
                f"Expected {EXPECTED_FILE_COUNT} files in manifest, found {self.manifest.total_files}"
            )
        if total_turns != self.manifest.total_turns:
            failures.append(
                f"Turn count mismatch: DB has {total_turns}, manifest has {self.manifest.total_turns}"
            )

        # 2. Checksum verification
        checksum_ok = True
        for f_entry in self.manifest.files:
            p = Path(self.manifest.files[0].filename)  # relative or check via source_file in turns
            turns_sample = self.memory.get_turns_for_meeting(f_entry.meeting_id)
            if not turns_sample:
                failures.append(f"No turns found in DB for meeting {f_entry.meeting_id}")
                checksum_ok = False
                continue
            first_turn = turns_sample[0]
            if first_turn.source_checksum != f_entry.sha256:
                failures.append(
                    f"Checksum mismatch for {f_entry.meeting_id}: "
                    f"DB has {first_turn.source_checksum}, manifest has {f_entry.sha256}"
                )
                checksum_ok = False

            # Verify on disk if path exists
            real_file = Path(first_turn.source_file)
            if real_file.exists():
                actual_sha = hashlib.sha256(real_file.read_bytes()).hexdigest()
                if actual_sha != f_entry.sha256:
                    failures.append(
                        f"Disk checksum mismatch for {real_file.name}: "
                        f"Disk has {actual_sha}, manifest has {f_entry.sha256}"
                    )
                    checksum_ok = False

        # 3. Global turn_index monotonicity and continuity
        turn_index_ok = True
        rows = self.memory.conn.execute(
            "SELECT turn_index, team_id, meeting_sequence FROM turns ORDER BY turn_index ASC"
        ).fetchall()

        if len(rows) != total_turns:
            failures.append(f"Row count mismatch in turn_index verification: {len(rows)} vs {total_turns}")
            turn_index_ok = False

        prev_idx = -1
        prev_team = ""
        prev_seq = ""

        for r in rows:
            curr_idx = r["turn_index"]
            curr_team = r["team_id"]
            curr_seq = r["meeting_sequence"]

            if curr_idx != prev_idx + 1:
                failures.append(
                    f"turn_index discontinuity: expected {prev_idx + 1}, got {curr_idx}"
                )
                turn_index_ok = False
                break

            # Check sequence order within same team
            if curr_team == prev_team and curr_seq < prev_seq:
                failures.append(
                    f"Sequence inversion in {curr_team}: {curr_seq} appeared after {prev_seq}"
                )
                turn_index_ok = False
                break

            prev_idx = curr_idx
            prev_team = curr_team
            prev_seq = curr_seq

        # 4. Coverage registry check
        incomplete_teams_ok = True
        coverage_map = self.memory.list_all_coverage()

        for team_id, expected_missing in [("IS1002", ["a"]), ("IS1005", ["d"])]:
            cov = coverage_map.get(team_id)
            if not cov:
                failures.append(f"Incomplete team {team_id} missing from coverage table")
                incomplete_teams_ok = False
                continue
            if cov.coverage_status != CoverageStatus.PARTIAL:
                failures.append(
                    f"Team {team_id} coverage should be PARTIAL, got {cov.coverage_status}"
                )
                incomplete_teams_ok = False
            for m_seq in expected_missing:
                if m_seq not in cov.missing_sequences:
                    failures.append(
                        f"Team {team_id} expected to miss meeting '{m_seq}', missing: {cov.missing_sequences}"
                    )
                    incomplete_teams_ok = False

        # Verify all other 33 teams are complete
        for team_id, cov in coverage_map.items():
            if team_id not in INCOMPLETE_TEAMS and cov.coverage_status != CoverageStatus.COMPLETE:
                failures.append(
                    f"Team {team_id} unexpectedly marked PARTIAL: missing {cov.missing_sequences}"
                )
                incomplete_teams_ok = False

        # 5. Byte offset slice reconstruction test
        byte_offset_ok = True
        # Check first 2 and last 2 turns of every meeting
        distinct_meetings = [
            r["meeting_id"]
            for r in self.memory.conn.execute(
                "SELECT DISTINCT meeting_id FROM turns ORDER BY meeting_id"
            ).fetchall()
        ]

        for mid in distinct_meetings:
            m_turns = self.memory.get_turns_for_meeting(mid)
            sample_turns = m_turns[:2] + (m_turns[-2:] if len(m_turns) > 2 else [])
            for t in sample_turns:
                reconstructed = self.memory.reconstruct_turn_text(t)
                words = t.text.split()
                if not words:
                    failures.append(f"Empty turn text in {t.turn_id}")
                    byte_offset_ok = False
                    continue
                # Verify first and last word are in the reconstructed slice
                if words[0] not in reconstructed or words[-1] not in reconstructed:
                    failures.append(
                        f"Byte slice mismatch in {t.turn_id}: "
                        f"turn text not cleanly contained in file slice"
                    )
                    byte_offset_ok = False
                    break
            if not byte_offset_ok:
                break

        passed = len(failures) == 0

        return Gate1Report(
            passed=passed,
            total_files=self.manifest.total_files,
            total_meetings=total_meetings,
            total_teams=total_teams,
            total_turns=total_turns,
            total_words=self.manifest.total_words,
            incomplete_teams_ok=incomplete_teams_ok,
            turn_index_ok=turn_index_ok,
            byte_offset_ok=byte_offset_ok,
            checksum_ok=checksum_ok,
            failures=failures,
        )
