"""Integration tests for Gate 1 pipeline, SQLite persistence, and manifest.

Tests that Gate 1 passes end-to-end against the real corpus,
verifies byte offset slice accuracy, idempotency, and schema integrity.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from meetingos.config import EXPECTED_FILE_COUNT, TRANSCRIPTS_DIR
from meetingos.ingestion.manifest import IngestionManifest
from meetingos.ingestion.pipeline import run_ingestion_pipeline
from meetingos.models import CoverageStatus


@pytest.fixture(scope="module")
def gate1_artifacts(tmp_path_factory: pytest.TempPathFactory):
    """Run ingestion once for the integration test module."""
    if not TRANSCRIPTS_DIR.exists():
        pytest.skip("Real transcript corpus not present")

    tmp_dir = tmp_path_factory.mktemp("gate1_test")
    db_path = tmp_dir / "test_meetingos.db"
    manifest_path = tmp_dir / "test_manifest.json"

    memory, manifest, report = run_ingestion_pipeline(
        transcripts_dir=TRANSCRIPTS_DIR,
        db_path=db_path,
        manifest_path=manifest_path,
        raise_on_failure=True,
    )
    return memory, manifest, report, db_path, manifest_path


class TestGate1PipelineIntegration:

    def test_gate1_report_passes(self, gate1_artifacts) -> None:
        _, _, report, _, _ = gate1_artifacts
        assert report.passed, f"Gate 1 report failed:\n{report.summary()}"
        assert report.failures == []

    def test_meeting_and_file_counts(self, gate1_artifacts) -> None:
        memory, manifest, report, _, _ = gate1_artifacts
        assert report.total_files == EXPECTED_FILE_COUNT
        assert report.total_meetings == EXPECTED_FILE_COUNT
        assert report.total_teams == 35
        assert memory.count_meetings() == EXPECTED_FILE_COUNT
        assert memory.count_teams() == 35

    def test_turn_count_matches(self, gate1_artifacts) -> None:
        memory, manifest, report, _, _ = gate1_artifacts
        db_turns = memory.count_turns()
        assert db_turns == manifest.total_turns
        assert db_turns >= 40000, f"Expected >40K turns, got {db_turns}"

    def test_global_turn_index_continuity(self, gate1_artifacts) -> None:
        memory, _, _, _, _ = gate1_artifacts
        rows = memory.conn.execute(
            "SELECT turn_index FROM turns ORDER BY turn_index ASC"
        ).fetchall()
        indices = [r["turn_index"] for r in rows]
        assert indices == list(range(len(indices))), "turn_index has gaps or is not strictly contiguous"

    def test_coverage_registry_is1002_and_is1005(self, gate1_artifacts) -> None:
        memory, manifest, _, _, _ = gate1_artifacts
        cov = memory.list_all_coverage()

        # IS1002
        assert "IS1002" in cov
        assert cov["IS1002"].coverage_status == CoverageStatus.PARTIAL
        assert cov["IS1002"].available_sequences == ["b", "c", "d"]
        assert cov["IS1002"].missing_sequences == ["a"]

        # IS1005
        assert "IS1005" in cov
        assert cov["IS1005"].coverage_status == CoverageStatus.PARTIAL
        assert cov["IS1005"].available_sequences == ["a", "b", "c"]
        assert cov["IS1005"].missing_sequences == ["d"]

        # Other 33 teams are complete
        for team_id, c in cov.items():
            if team_id not in ("IS1002", "IS1005"):
                assert c.coverage_status == CoverageStatus.COMPLETE
                assert c.available_sequences == ["a", "b", "c", "d"]
                assert c.missing_sequences == []

    def test_byte_offset_slice_reconstruction(self, gate1_artifacts) -> None:
        """Every tested turn slice from the raw file contains the turn text."""
        memory, _, _, _, _ = gate1_artifacts
        # Sample turns from various meetings
        for meeting_id in ["ES2002a", "ES2008b", "IS1002b", "IS1005c", "TS3012d"]:
            turns = memory.get_turns_for_meeting(meeting_id)
            for t in [turns[0], turns[len(turns)//2], turns[-1]]:
                reconstructed = memory.reconstruct_turn_text(t)
                words = t.text.split()
                assert words[0] in reconstructed, f"First word {words[0]} not in slice for {t.turn_id}"
                assert words[-1] in reconstructed, f"Last word {words[-1]} not in slice for {t.turn_id}"

    def test_idempotent_reingestion(self, gate1_artifacts) -> None:
        """Re-running save_meetings produces identical counts and no duplicates."""
        memory, _, _, db_path, _ = gate1_artifacts
        count_before = memory.count_turns()

        from meetingos.ingestion.parser import discover_transcripts, parse_transcript, build_coverage_registry
        files = discover_transcripts(TRANSCRIPTS_DIR)
        meetings = [parse_transcript(f) for f in files]
        coverage = build_coverage_registry(meetings)

        # Re-save
        reinserted = memory.save_meetings(meetings, coverage)
        count_after = memory.count_turns()

        assert reinserted == count_before
        assert count_after == count_before, "Re-ingestion changed turn count"

    def test_manifest_file_validity(self, gate1_artifacts) -> None:
        _, manifest, _, _, manifest_path = gate1_artifacts
        assert manifest_path.exists()
        loaded = IngestionManifest.from_json_file(manifest_path)
        assert loaded.total_files == EXPECTED_FILE_COUNT
        assert loaded.total_meetings == EXPECTED_FILE_COUNT
        assert loaded.total_turns == manifest.total_turns
        assert len(loaded.files) == EXPECTED_FILE_COUNT
        assert len(loaded.teams) == 35

    def test_context_window_query(self, gate1_artifacts) -> None:
        memory, _, _, _, _ = gate1_artifacts
        turns = memory.get_turns_for_meeting("ES2008b")
        mid_turn = turns[len(turns)//2]
        window = memory.get_context_window("ES2008b", mid_turn.turn_index, before=2, after=2)
        assert len(window) == 5
        assert window[2].turn_id == mid_turn.turn_id
